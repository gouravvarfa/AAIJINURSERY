"""Stock vs. demand, and the admin's per-line decision.

An order (website or Sales Order) always keeps the full quantity the customer
asked for -- stock is never a limit and nothing is taken from stock
automatically. For each order line the admin chooses:

  * "stock"   -> give some / all of the pending quantity from nursery stock now
                 (stock goes down by that amount and it becomes *allocated*);
  * "prepare" -> the nursery will prepare the pending quantity (no stock used);
  * "clear"   -> undo a "prepare" decision.

Quantities (per plant, or per tray size for tray products):

  available stock    = the stock number (Plant / PlantVariant.stock_quantity)
  reserved stock     = sum of ALLOCATED on open orders (taken from stock, not yet delivered)
  physical stock     = available + reserved
  outstanding demand = sum of PENDING (ordered - allocated) on open orders
      undecided        pending lines the admin has not decided on yet
      to prepare       pending lines marked "prepare"
  shortage           = max(0, outstanding demand - available)   (what must be produced / bought)

Demand is counted once: website orders from the Orders table, and only
*offline* Sales Orders from the accounting table (an online order's Sales
Order is a mirror of the same demand).
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, func
from sqlalchemy.orm import Session

from app.accounting.audit import record_change
from app.accounting.models import SalesOrder, SalesOrderItem
from app.database import get_db
from app.deps import get_current_admin
from app.inventory import allocate_stock
from app.models import Order, OrderItem, Plant, PlantVariant
from app.permissions import require_permission

router = APIRouter(prefix="/api/admin/inventory", tags=["inventory-demand"])

OPEN_ORDER_STATUSES = ("Pending", "Confirmed", "Processing", "Packed", "Shipped", "Out For Delivery")
OPEN_SO_STATUSES = ("Draft", "Confirmed", "Invoiced")


def _delivery_done(so_id_col):
    from app.delivery.models import Delivery

    return exists().where(and_(Delivery.sales_order_id == so_id_col, Delivery.status.in_(("Delivered", "Partially Delivered"))))


def _open_online_lines(db: Session):
    return (
        db.query(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status.in_(OPEN_ORDER_STATUSES), OrderItem.plant_id.isnot(None))
    )


def _open_offline_lines(db: Session):
    return (
        db.query(SalesOrderItem)
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.sales_order_id)
        .filter(
            SalesOrder.source == "offline",
            SalesOrder.status.in_(OPEN_SO_STATUSES),
            SalesOrderItem.plant_id.isnot(None),
            ~_delivery_done(SalesOrder.id),
        )
    )


def demand_by_target(db: Session, plant_id: Optional[int] = None) -> dict:
    """{(plant_id, variant_id|None): {reserved, pending, prepare, orders}}"""
    out: dict = {}

    def bucket(plant, variant):
        return out.setdefault((plant, variant or None), {"reserved": 0, "pending": 0, "prepare": 0, "orders": 0})

    online, offline = _open_online_lines(db), _open_offline_lines(db)
    if plant_id:
        online = online.filter(OrderItem.plant_id == plant_id)
        offline = offline.filter(SalesOrderItem.plant_id == plant_id)
    for lines in (online, offline):
        for line in lines.all():
            b = bucket(line.plant_id, line.variant_id)
            b["reserved"] += line.allocated
            if line.pending > 0:
                b["pending"] += line.pending
                b["orders"] += 1
                if line.to_prepare:
                    b["prepare"] += line.pending
    return out


def _row(plant: Plant, variant: Optional[PlantVariant], demand: dict, in_production: Optional[dict] = None) -> dict:
    d = demand.get((plant.id, variant.id if variant else None), {"reserved": 0, "pending": 0, "prepare": 0, "orders": 0})
    available = (variant.stock_quantity if variant else plant.stock_quantity) or 0
    pending = d["pending"]
    making = (in_production or {}).get((plant.id, variant.id if variant else None), 0)
    return {
        "plant_id": plant.id,
        "variant_id": variant.id if variant else None,
        "name": plant.name + (f" - tray of {variant.tray_size}" if variant else ""),
        "unit": "trays" if variant else "plants",
        "physical_stock": available + d["reserved"],
        "reserved_stock": d["reserved"],
        "available_stock": available,
        "outstanding_demand": pending,
        "undecided": pending - d["prepare"],
        "to_prepare": d["prepare"],
        "shortage": max(0, pending - available),
        "in_production": making,  # planned output of batches not finished yet (never counted as ready stock)
        "to_produce": max(0, pending - available - making),  # still to be put into a batch
        "open_lines": d["orders"],
    }


def stock_position(db: Session, plant_id: int, variant_id: Optional[int]) -> dict:
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        return {}
    variant = db.query(PlantVariant).filter(PlantVariant.id == variant_id).first() if variant_id else None
    return _row(plant, variant, demand_by_target(db, plant_id))


@router.get("/stock-demand", dependencies=[Depends(require_permission("products", "VIEW"))])
def stock_demand(only_shortage: bool = False, db: Session = Depends(get_db)):
    from app.production_router import planned_by_target

    demand = demand_by_target(db)
    making = planned_by_target(db)
    rows = []
    for plant in db.query(Plant).order_by(Plant.name).all():
        variants = db.query(PlantVariant).filter(PlantVariant.plant_id == plant.id).all()
        if variants:
            rows.extend(_row(plant, v, demand, making) for v in variants)
        else:
            rows.append(_row(plant, None, demand, making))
    if only_shortage:
        rows = [r for r in rows if r["shortage"] > 0 or r["to_produce"] > 0]
    totals = {
        "outstanding_demand": sum(r["outstanding_demand"] for r in rows),
        "shortage": sum(r["shortage"] for r in rows),
        "undecided": sum(r["undecided"] for r in rows),
        "to_prepare": sum(r["to_prepare"] for r in rows),
        "in_production": sum(r["in_production"] for r in rows),
        "to_produce": sum(r["to_produce"] for r in rows),
    }
    return {
        "items": rows,
        "totals": totals,
        "note": "Physical = available + reserved. Demand counts website orders and offline Sales Orders once; delivered and cancelled orders are not counted.",
    }


class FulfilIn(BaseModel):
    kind: Literal["order", "sales_order"]
    item_id: int
    action: Literal["stock", "prepare", "clear"]
    quantity: Optional[int] = Field(default=None, ge=1)


@router.post("/fulfil")
def fulfil(payload: FulfilIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    from app.models import AdminUser
    from app.permissions import check_permission

    module = "orders" if payload.kind == "order" else "accounting"
    user = db.query(AdminUser).filter(AdminUser.username == admin).first()
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not check_permission(db, user, module, "EDIT"):
        raise HTTPException(status_code=403, detail="You do not have permission to do this")

    if payload.kind == "order":
        line = db.query(OrderItem).filter(OrderItem.id == payload.item_id).first()
        parent = db.query(Order).filter(Order.id == line.order_id).first() if line else None
        is_open = bool(parent) and parent.status in OPEN_ORDER_STATUSES
        parent_id, source_type = (parent.id if parent else None), "ORDER_STOCK_ALLOCATION"
    else:
        line = db.query(SalesOrderItem).filter(SalesOrderItem.id == payload.item_id).first()
        parent = db.query(SalesOrder).filter(SalesOrder.id == line.sales_order_id).first() if line else None
        is_open = bool(parent) and parent.status in OPEN_SO_STATUSES
        parent_id, source_type = (parent.id if parent else None), "SALES_ORDER_ALLOCATION"
    if not line or not parent:
        raise HTTPException(status_code=404, detail="Order line not found")
    if not is_open:
        raise HTTPException(status_code=400, detail="This order is closed (cancelled or delivered), so its stock can't be changed")
    if not line.plant_id:
        raise HTTPException(status_code=400, detail="This line is not linked to a plant, so it has no stock")

    if payload.action == "clear":
        line.to_prepare = False
    elif payload.action == "prepare":
        if line.pending <= 0:
            raise HTTPException(status_code=400, detail="Nothing is pending on this line")
        line.to_prepare = True
    else:
        want = payload.quantity or line.pending
        if line.pending <= 0:
            raise HTTPException(status_code=400, detail="Nothing is pending on this line")
        if want > line.pending:
            raise HTTPException(status_code=400, detail=f"Only {line.pending} still pending on this line")
        target = db.query(PlantVariant).filter(PlantVariant.id == line.variant_id).first() if line.variant_id else db.query(Plant).filter(Plant.id == line.plant_id).first()
        in_stock = (target.stock_quantity if target else 0) or 0
        if in_stock < want:
            raise HTTPException(status_code=400, detail=f"Only {in_stock} in stock right now, so {want} can't be given from stock")
        taken = allocate_stock(
            db,
            plant_id=line.plant_id,
            variant_id=line.variant_id,
            quantity=want,
            source_type=source_type,
            source_id=parent_id,
            reference=f"ALLOC:{payload.kind}:{line.id}:{line.allocated}",
            created_by=admin,
            notes="Given from stock by admin",
        )
        if taken <= 0:
            raise HTTPException(status_code=400, detail="Stock ran out just now, nothing was taken")
        line.allocated_quantity = line.allocated + taken
        if line.pending <= 0:
            line.to_prepare = False

    if payload.kind == "sales_order":
        record_change(db, "accounting_sales_orders", parent_id, "fulfilment", changed_by=admin,
                      changes={"line": (None, f"{line.id}: {payload.action} {payload.quantity or ''}".strip())})
    db.commit()
    if payload.action == "prepare":
        from app.notifications import notify_order_preparing, notify_sales_order_preparing

        (notify_order_preparing if payload.kind == "order" else notify_sales_order_preparing)(parent)
    return {"item_id": line.id, "quantity": line.quantity, "allocated": line.allocated, "pending": line.pending, "to_prepare": bool(line.to_prepare)}
