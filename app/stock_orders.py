"""Stock team's view of offline Sales Orders.

As soon as a Sales Order is saved its lines show up here with the customer's
name and quantities -- no prices, invoices or payments. For each line the stock
team decides how many to grow ("prepare quantity", which may be more than what
is pending to cover plants lost while growing) and later records how many came
out good:

  * the part the customer still needs is given to the order line (allocated),
  * whatever is left over goes into general stock.

Example: customer wants 100, 40 are already in stock, 60 are pending. Stock team
sets prepare quantity to 80. When all 80 come out good they record 80 good / 60
for the customer -> the order is complete and 20 land in general stock.

The customer's order quantity, price and invoice are never changed here.

Also holds the list of WhatsApp numbers that get a "new order" alert when a Sales
Order is saved (see queue_stock_team_new_order).
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import Session, joinedload

from app.accounting.audit import record_change
from app.accounting.models import SalesOrder, SalesOrderItem
from app.communications.phone import normalize_mobile
from app.database import Base, get_db
from app.deps import get_current_admin
from app.inventory import MAX_ORDER_QUANTITY, allocate_stock, restore_stock
from app.inventory_router import _open_offline_lines
from app.models import Plant, PlantVariant
from app.permissions import require_permission

logger = logging.getLogger("stock_orders")

router = APIRouter(prefix="/api/admin/stock-orders", tags=["stock-orders"])

STOCK_ALERT_EVENT = "SALES_ORDER_STOCK_ALERT"


class StockAlertRecipient(Base):
    """A stock-team member who gets a WhatsApp message for every new Sales Order."""

    __tablename__ = "stock_alert_recipients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(80), nullable=False, default="")
    mobile = Column(String(20), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------- WhatsApp alert ----------

def _items_summary(order: SalesOrder) -> str:
    parts = []
    for line in order.items:
        name = (line.plant.name if line.plant else line.description) or "Item"
        if line.variant_id and line.tray_size:
            parts.append(f"{name} - {line.quantity} tray (of {line.tray_size})")
        else:
            parts.append(f"{name} - {line.quantity}")
    return "; ".join(parts)[:900]


def queue_stock_team_new_order(order: SalesOrder, db: Session) -> None:
    """Tells every active stock-team number that a new order needs attention.
    Never raises: a messaging problem must not affect saving the order."""
    try:
        from app.communications.service import queue_event

        recipients = db.query(StockAlertRecipient).filter(StockAlertRecipient.is_active.is_(True)).all()
        if not recipients:
            return
        customer = order.contact.name if order.contact else "Customer"
        items = _items_summary(order)
        for r in recipients:
            queue_event(
                event_type=STOCK_ALERT_EVENT, mobile=r.mobile, customer_name=r.name or "Stock team",
                template_params=[customer, order.order_number, items],
                source_module="stock", source_id=f"SO-{order.id}-R{r.id}",
                recipient_type="STAFF", recipient_id=r.id,
            )
    except Exception:  # noqa: BLE001
        logger.exception("Stock team alert failed for sales order id=%s", getattr(order, "id", None))


# ---------- Alert recipients ----------

class RecipientIn(BaseModel):
    name: str = Field(default="", max_length=80)
    mobile: str = Field(min_length=1, max_length=20)


def _recipient_out(r: StockAlertRecipient) -> dict:
    return {"id": r.id, "name": r.name, "mobile": r.mobile}


@router.get("/alert-recipients", dependencies=[Depends(require_permission("inventory", "VIEW"))])
def list_recipients(db: Session = Depends(get_db)):
    rows = db.query(StockAlertRecipient).filter(StockAlertRecipient.is_active.is_(True)).order_by(StockAlertRecipient.id).all()
    return [_recipient_out(r) for r in rows]


@router.post("/alert-recipients", status_code=201, dependencies=[Depends(require_permission("inventory", "EDIT"))])
def add_recipient(payload: RecipientIn, db: Session = Depends(get_db)):
    mobile = normalize_mobile(payload.mobile)
    if not mobile:
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit Indian mobile number.")
    existing = db.query(StockAlertRecipient).filter(StockAlertRecipient.mobile == mobile).first()
    if existing:
        existing.is_active = True
        existing.name = payload.name.strip() or existing.name
        row = existing
    else:
        row = StockAlertRecipient(name=payload.name.strip(), mobile=mobile)
        db.add(row)
    db.commit()
    db.refresh(row)
    return _recipient_out(row)


@router.delete("/alert-recipients/{recipient_id}", dependencies=[Depends(require_permission("inventory", "EDIT"))])
def remove_recipient(recipient_id: int, db: Session = Depends(get_db)):
    row = db.query(StockAlertRecipient).filter(StockAlertRecipient.id == recipient_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Number not found")
    row.is_active = False
    db.commit()
    return {"ok": True}


# ---------- Order lines ----------

def _line_row(line: SalesOrderItem, available: int) -> dict:
    order = line.sales_order
    is_tray = bool(line.variant_id)
    name = (line.plant.name if line.plant else line.description) or "Item"
    return {
        "line_id": line.id,
        "sales_order_id": order.id,
        "order_number": order.order_number,
        "customer_name": order.contact.name if order.contact else "-",
        "order_date": order.order_date,
        "delivery_date": order.delivery_date,
        "order_notes": order.notes or "",
        "product": name + (f" - tray of {line.tray_size}" if is_tray and line.tray_size else ""),
        "unit": "trays" if is_tray else "plants",
        "quantity": line.quantity or 0,
        "allocated": line.allocated,
        "pending": line.pending,
        "available_stock": available,
        "shortage": max(0, line.pending - available),
        "prepare_quantity": line.prepare_quantity,
        "prepared_quantity": line.prepared_quantity or 0,
        "to_prepare": bool(line.to_prepare),
    }


@router.get("", dependencies=[Depends(require_permission("inventory", "VIEW"))])
def list_stock_orders(
    q: Optional[str] = Query(None, description="Search by customer name, order # or plant"),
    only_pending: bool = False,
    db: Session = Depends(get_db),
):
    lines = (
        _open_offline_lines(db)
        .options(joinedload(SalesOrderItem.sales_order).joinedload(SalesOrder.contact), joinedload(SalesOrderItem.plant))
        .order_by(SalesOrder.delivery_date.is_(None), SalesOrder.delivery_date, SalesOrder.id.desc(), SalesOrderItem.id)
        .all()
    )
    plant_stock = {p.id: p.stock_quantity or 0 for p in db.query(Plant.id, Plant.stock_quantity).all()}
    variant_stock = {v.id: v.stock_quantity or 0 for v in db.query(PlantVariant.id, PlantVariant.stock_quantity).all()}

    rows = []
    needle = (q or "").strip().lower()
    for line in lines:
        available = variant_stock.get(line.variant_id, 0) if line.variant_id else plant_stock.get(line.plant_id, 0)
        row = _line_row(line, available)
        if only_pending and row["pending"] <= 0:
            continue
        if needle and needle not in f'{row["customer_name"]} {row["order_number"]} {row["product"]}'.lower():
            continue
        rows.append(row)
    return {
        "items": rows,
        "totals": {
            "lines": len(rows),
            "pending": sum(r["pending"] for r in rows),
            "shortage": sum(r["shortage"] for r in rows),
        },
    }


def _open_line(db: Session, line_id: int) -> SalesOrderItem:
    line = _open_offline_lines(db).filter(SalesOrderItem.id == line_id).first()
    if not line:
        raise HTTPException(status_code=404, detail="Order line not found, or its order is closed (cancelled or delivered)")
    return line


class PrepareIn(BaseModel):
    # None / 0 clears the target.
    prepare_quantity: Optional[int] = Field(default=None, ge=0, le=MAX_ORDER_QUANTITY)


@router.put("/lines/{line_id}/prepare")
def set_prepare_quantity(
    line_id: int,
    payload: PrepareIn,
    admin: str = Depends(get_current_admin),
    _perm: str = Depends(require_permission("inventory", "EDIT")),
    db: Session = Depends(get_db),
):
    line = _open_line(db, line_id)
    before = line.prepare_quantity
    if payload.prepare_quantity:
        if line.pending <= 0:
            raise HTTPException(status_code=400, detail="Nothing is pending on this line")
        line.prepare_quantity = payload.prepare_quantity
        line.to_prepare = True
    else:
        line.prepare_quantity = None
        line.to_prepare = False
    record_change(db, "accounting_sales_orders", line.sales_order_id, "fulfilment", changed_by=admin,
                  changes={"line": (None, f"{line.id}: prepare target {before} -> {line.prepare_quantity}")})
    db.commit()
    return {"line_id": line.id, "prepare_quantity": line.prepare_quantity, "to_prepare": bool(line.to_prepare)}


class ReadyIn(BaseModel):
    good: int = Field(ge=1, le=MAX_ORDER_QUANTITY, description="How many came out good")
    to_customer: int = Field(ge=0, le=MAX_ORDER_QUANTITY, description="How many of those go to this customer's order")


@router.post("/lines/{line_id}/ready")
def record_ready(
    line_id: int,
    payload: ReadyIn,
    admin: str = Depends(get_current_admin),
    _perm: str = Depends(require_permission("inventory", "EDIT")),
    db: Session = Depends(get_db),
):
    """Good plants come into stock; the customer's share is then given to the
    order line straight away, so the leftover stays in general stock."""
    line = _open_line(db, line_id)
    if payload.to_customer > payload.good:
        raise HTTPException(status_code=400, detail="Customer's share can't be more than the good plants.")
    if payload.to_customer > line.pending:
        raise HTTPException(status_code=400, detail=f"This order only needs {line.pending} more.")

    prepared_before = line.prepared_quantity or 0
    allocated_before = line.allocated
    # References make a double click / retry a no-op instead of counting twice.
    restore_stock(
        db,
        plant_id=line.plant_id,
        variant_id=line.variant_id,
        quantity=payload.good,
        source_type="STOCK_PREPARED",
        source_id=line.sales_order_id,
        reference=f"PREP_READY:{line.id}:{prepared_before}",
        transaction_type="PRODUCTION_READY",
        created_by=admin,
        notes="Prepared by stock team",
    )
    taken = 0
    if payload.to_customer:
        taken = allocate_stock(
            db,
            plant_id=line.plant_id,
            variant_id=line.variant_id,
            quantity=payload.to_customer,
            source_type="SALES_ORDER_ALLOCATION",
            source_id=line.sales_order_id,
            reference=f"PREP_ALLOC:{line.id}:{allocated_before}",
            created_by=admin,
            notes="Given from freshly prepared plants",
        )
        if taken < payload.to_customer:
            db.rollback()
            raise HTTPException(status_code=409, detail="Stock changed while saving. Please refresh and try again.")

    line.prepared_quantity = prepared_before + payload.good
    line.allocated_quantity = allocated_before + taken
    if line.pending <= 0:
        line.to_prepare = False
    record_change(db, "accounting_sales_orders", line.sales_order_id, "fulfilment", changed_by=admin,
                  changes={"line": (None, f"{line.id}: ready {payload.good}, to customer {taken}, to stock {payload.good - taken}")})
    db.commit()
    return {
        "line_id": line.id,
        "allocated": line.allocated,
        "pending": line.pending,
        "prepared_quantity": line.prepared_quantity,
        "to_general_stock": payload.good - taken,
    }
