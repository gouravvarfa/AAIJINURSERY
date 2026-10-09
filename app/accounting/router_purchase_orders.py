from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.accounting.audit import record_change
from app.accounting.models import Contact, PurchaseOrder, PurchaseOrderItem
from app.accounting.permissions import PURCHASE_WRITE_ROLES, require_accounting_action
from app.accounting.router_bills import _with_summary as _bill_with_summary
from app.accounting.schemas import (
    BillOut,
    BillRef,
    PurchaseOrderConvertIn,
    PurchaseOrderIn,
    PurchaseOrderOut,
)
from app.database import get_db
from app.deps import get_current_admin
from app.inventory import adjust_stock
from app.models import Plant, PlantVariant, Purchase, PurchaseItem

router = APIRouter(tags=["accounting-purchase-orders"])


def _with_bill_ref(db: Session, item: PurchaseOrder) -> PurchaseOrderOut:
    out = PurchaseOrderOut.model_validate(item)
    bill = db.query(Purchase).filter(Purchase.purchase_order_id == item.id).first()
    if bill:
        out.bill = BillRef.model_validate(bill)
    return out


@router.get("/purchase-orders", response_model=list[PurchaseOrderOut])
def list_purchase_orders(
    status: Optional[str] = Query(None),
    contact_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None, description="Search by order # or supplier name"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(PurchaseOrder).options(
        joinedload(PurchaseOrder.contact), joinedload(PurchaseOrder.items)
    )
    if status:
        query = query.filter(PurchaseOrder.status == status)
    if contact_id:
        query = query.filter(PurchaseOrder.contact_id == contact_id)
    if q:
        like = f"%{q}%"
        query = query.join(Contact, Contact.id == PurchaseOrder.contact_id).filter(
            PurchaseOrder.order_number.ilike(like) | Contact.name.ilike(like)
        )
    orders = query.order_by(PurchaseOrder.order_date.desc()).all()
    return [_with_bill_ref(db, o) for o in orders]


@router.get("/purchase-orders/{item_id}", response_model=PurchaseOrderOut)
def get_purchase_order(
    item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = (
        db.query(PurchaseOrder)
        .options(joinedload(PurchaseOrder.contact), joinedload(PurchaseOrder.items))
        .filter(PurchaseOrder.id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return _with_bill_ref(db, item)


@router.post("/purchase-orders", response_model=PurchaseOrderOut, status_code=201)
def create_purchase_order(
    payload: PurchaseOrderIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("CREATE", PURCHASE_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    if not payload.items:
        raise HTTPException(status_code=400, detail="At least one line item is required")
    contact = db.query(Contact).filter(Contact.id == payload.contact_id).first()
    if not contact:
        raise HTTPException(status_code=400, detail="Unknown contact")

    plant_ids = {i.plant_id for i in payload.items}
    plants = {p.id: p for p in db.query(Plant).filter(Plant.id.in_(plant_ids)).all()}
    missing = plant_ids - plants.keys()
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown plant id(s): {sorted(missing)}")

    order = PurchaseOrder(
        contact_id=contact.id,
        order_number="",
        status="Draft",
        order_date=payload.order_date,
        notes=payload.notes,
        source="offline",
        created_by=admin,
    )
    db.add(order)
    db.flush()
    order.order_number = f"PO-{order.id}"

    subtotal = 0.0
    for line in payload.items:
        if line.quantity <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be greater than 0")
        plant = plants[line.plant_id]
        tray_size = None
        if line.variant_id is not None:
            variant = db.query(PlantVariant).filter(PlantVariant.id == line.variant_id, PlantVariant.plant_id == plant.id).first()
            if not variant:
                raise HTTPException(status_code=400, detail="Unknown tray-size option for this plant")
            tray_size = variant.tray_size
        line_total = round(line.quantity * line.unit_price, 2)
        subtotal += line_total
        db.add(
            PurchaseOrderItem(
                purchase_order_id=order.id,
                plant_id=plant.id,
                description=line.description or plant.name,
                quantity=line.quantity,
                unit_price=line.unit_price,
                tax_rate_id=line.tax_rate_id,
                line_total=line_total,
                variant_id=line.variant_id,
                tray_size=tray_size,
            )
        )

    order.subtotal = round(subtotal, 2)
    order.total_amount = round(subtotal, 2)
    db.commit()
    db.refresh(order)
    record_change(db, "accounting_purchase_orders", order.id, "create", changed_by=admin)
    db.commit()
    return get_purchase_order(order.id, admin, db)


@router.post("/purchase-orders/{item_id}/convert-to-bill", response_model=BillOut)
def convert_to_bill(
    item_id: int,
    payload: PurchaseOrderConvertIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("CREATE", PURCHASE_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """Converts a Purchase Order into a Bill (the existing Purchase table).
    The original Purchase Order is NEVER deleted or overwritten -- it stays
    exactly as-is, with its status flipped to "Billed" and a new, separate
    Purchase row created alongside it, linked back via
    Purchase.purchase_order_id. Receiving the bill increments live plant
    stock, same as logging a standalone Purchase does."""
    order = (
        db.query(PurchaseOrder)
        .options(joinedload(PurchaseOrder.items), joinedload(PurchaseOrder.contact))
        .filter(PurchaseOrder.id == item_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if order.status in ("Cancelled", "Voided"):
        raise HTTPException(status_code=400, detail=f"Cannot bill a {order.status} purchase order")

    existing = db.query(Purchase).filter(Purchase.purchase_order_id == order.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="This purchase order already has a bill")

    bill = Purchase(
        purchase_date=datetime.utcnow(),
        supplier=order.contact.name if order.contact else "",
        invoice_number=f"BILL-{order.order_number}",
        notes=f"Auto-created from Purchase Order {order.order_number}",
        status="Unpaid",
        due_date=payload.due_date,
        source="offline",
        contact_id=order.contact_id,
        purchase_order_id=order.id,
        created_by=admin,
    )
    db.add(bill)
    db.flush()

    total = 0.0
    for line in order.items:
        plant = db.query(Plant).filter(Plant.id == line.plant_id).first()
        db.add(
            PurchaseItem(
                purchase_id=bill.id,
                plant_id=line.plant_id,
                plant_name=line.description or (plant.name if plant else ""),
                quantity=line.quantity,
                unit_cost=line.unit_price,
                total_cost=line.line_total,
            )
        )
        if plant:
            # A tray-size line credits that variant's own stock (quantity =
            # number of trays received), exactly how a tray sale deducts it
            # on the website -- never the plant's plain per-unit stock.
            adjust_stock(
                db,
                plant_id=plant.id,
                variant_id=line.variant_id,
                quantity_delta=line.quantity,
                transaction_type="PURCHASE_RECEIVED",
                source_type="PURCHASE_ORDER",
                source_id=order.id,
                reference=f"PURCHASE_ORDER:{order.id}:PURCHASE_RECEIVED:{line.variant_id or plant.id}",
                created_by=admin,
            )
        total += line.line_total

    bill.total_cost = round(total, 2)

    old_status = order.status
    order.status = "Billed"
    db.commit()
    db.refresh(bill)
    record_change(
        db,
        "accounting_purchase_orders",
        order.id,
        "convert",
        changed_by=admin,
        changes={"status": (old_status, "Billed")},
    )
    record_change(db, "purchases", bill.id, "create", changed_by=admin)
    db.commit()
    return _bill_with_summary(db, bill)
