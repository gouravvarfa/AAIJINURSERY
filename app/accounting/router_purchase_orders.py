from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
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
from app.supply_inventory import create_supply_bill, normalise_line

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


def _add_lines(db: Session, order: PurchaseOrder, lines, allow_plant: bool = False) -> float:
    """Validates and adds the given line items to `order`, returning their subtotal. Shared by create and edit so both apply the
    same checks. A Purchase Order is for seed packets, medicines, fertilizers and other supplies. Plants are not bought here
    ("plant" lines only survive on older orders that already had them)."""
    subtotal = 0.0
    order_day = (order.order_date or datetime.utcnow()).date()
    for n, line in enumerate(lines, 1):
        kind = line.item_kind or "seed_packet"
        if kind == "plant":
            if not allow_plant:
                raise HTTPException(status_code=400, detail=f"Line {n}: plants are not bought on a Purchase Order. Choose seed packet, medicine, fertilizer or other supply (plants are purchased from Admin, Purchases).")
            if line.plant_id is None:
                raise HTTPException(status_code=400, detail=f"Line {n}: unknown plant")
            plant = db.query(Plant).filter(Plant.id == line.plant_id).first()
            if not plant:
                raise HTTPException(status_code=400, detail=f"Unknown plant id(s): [{line.plant_id}]")
            if line.quantity <= 0:
                raise HTTPException(status_code=400, detail="Quantity must be greater than 0")
            tray_size = None
            if line.variant_id is not None:
                variant = db.query(PlantVariant).filter(PlantVariant.id == line.variant_id, PlantVariant.plant_id == plant.id).first()
                if not variant:
                    raise HTTPException(status_code=400, detail="Unknown tray-size option for this plant")
                tray_size = variant.tray_size
            line_total = round(line.quantity * line.unit_price, 2)
            subtotal += line_total
            db.add(PurchaseOrderItem(purchase_order_id=order.id, plant_id=plant.id, description=line.description or plant.name, quantity=line.quantity, unit_price=line.unit_price,
                                     tax_rate_id=line.tax_rate_id, line_total=line_total, variant_id=line.variant_id, tray_size=tray_size, item_kind="plant"))
            continue
        spec = normalise_line(db, {
            "item_kind": kind, "item_name": line.description, "plant_id": line.plant_id, "company": line.company, "lot_number": line.lot_number, "quantity": line.quantity,
            "unit": line.unit, "unit_cost": line.unit_price, "mfg_date": line.mfg_date, "expiry_date": line.expiry_date, "packet_size": line.packet_size, "packet_unit": line.packet_unit,
            "storage_location": line.storage_location, "notes": line.line_notes,
        }, order_day, label=f"Line {n}")
        line_total = round(spec["quantity"] * (spec["unit_cost"] or 0), 2)
        subtotal += line_total
        db.add(PurchaseOrderItem(
            purchase_order_id=order.id, plant_id=spec["plant_id"], description=spec["item_name"], quantity=spec["quantity"], unit_price=spec["unit_cost"] or 0, tax_rate_id=line.tax_rate_id,
            line_total=line_total, item_kind=spec["item_kind"], lot_number=spec["lot_number"], company=spec["company"], unit=spec["unit"], mfg_date=spec["mfg_date"],
            expiry_date=spec["expiry_date"], packet_size=spec["packet_size"], packet_unit=spec["packet_unit"], storage_location=spec["storage_location"], line_notes=spec["notes"],
        ))
    return subtotal


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

    subtotal = _add_lines(db, order, payload.items)
    order.subtotal = round(subtotal, 2)
    order.total_amount = round(subtotal, 2)
    db.commit()
    db.refresh(order)
    record_change(db, "accounting_purchase_orders", order.id, "create", changed_by=admin)
    db.commit()
    return get_purchase_order(order.id, admin, db)


@router.put("/purchase-orders/{item_id}", response_model=PurchaseOrderOut)
def update_purchase_order(
    item_id: int,
    payload: PurchaseOrderIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("EDIT", PURCHASE_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """Edit a Purchase Order that is still a Draft. Once it has been billed
    the bill and the stock it received depend on its lines, so it is locked."""
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == item_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if order.status != "Draft" or db.query(Purchase.id).filter(Purchase.purchase_order_id == order.id).first():
        raise HTTPException(status_code=400, detail="Only a Draft purchase order that has no bill yet can be edited")
    if not payload.items:
        raise HTTPException(status_code=400, detail="At least one line item is required")
    contact = db.query(Contact).filter(Contact.id == payload.contact_id).first()
    if not contact:
        raise HTTPException(status_code=400, detail="Unknown contact")

    before = {"contact_id": order.contact_id, "order_date": str(order.order_date), "notes": order.notes, "total_amount": order.total_amount}
    had_plants = any(i.item_kind == "plant" for i in order.items)
    order.items.clear()
    db.flush()
    order.order_date = payload.order_date
    subtotal = _add_lines(db, order, payload.items, allow_plant=had_plants)
    order.contact_id = contact.id
    order.order_date = payload.order_date
    order.notes = payload.notes
    order.subtotal = round(subtotal, 2)
    order.total_amount = round(subtotal, 2)
    after = {"contact_id": order.contact_id, "order_date": str(order.order_date), "notes": order.notes, "total_amount": order.total_amount}
    changes = {k: (v, after[k]) for k, v in before.items() if v != after[k]}
    changes["line_items"] = ("replaced", f"{len(payload.items)} line(s)")
    db.commit()
    record_change(db, "accounting_purchase_orders", order.id, "edit", changed_by=admin, changes=changes)
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

    today = date.today()
    bill_number = (payload.supplier_bill_number or "").strip()
    bill = Purchase(
        purchase_date=datetime.utcnow(),
        supplier=order.contact.name if order.contact else "",
        invoice_number=bill_number or f"BILL-{order.order_number}",
        notes=f"Auto-created from Purchase Order {order.order_number}",
        status="Unpaid",
        due_date=payload.due_date,
        source="offline",
        contact_id=order.contact_id,
        purchase_order_id=order.id,
        request_id=f"PO:{order.id}",  # a second bill for the same order is impossible, even if two clicks race
        created_by=admin,
    )
    db.add(bill)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="This purchase order already has a bill")

    plant_total = 0.0
    supply_specs = []
    for n, line in enumerate(order.items, 1):
        if line.item_kind != "plant":
            supply_specs.append(normalise_line(db, {
                "item_kind": line.item_kind, "item_name": line.description, "plant_id": line.plant_id, "company": line.company, "lot_number": line.lot_number, "quantity": line.quantity,
                "unit": line.unit, "unit_cost": line.unit_price, "total_cost": line.line_total, "mfg_date": line.mfg_date, "expiry_date": line.expiry_date,
                "packet_size": line.packet_size, "packet_unit": line.packet_unit, "storage_location": line.storage_location, "notes": line.line_notes,
            }, today, label=f"Line {n} ({line.description})"))
            continue
        # older orders only: a plant line is received into plant stock exactly as before
        plant = db.query(Plant).filter(Plant.id == line.plant_id).first()
        db.add(
            PurchaseItem(
                purchase_id=bill.id,
                plant_id=line.plant_id,
                plant_name=line.description or (plant.name if plant else ""),
                quantity=int(round(line.quantity)),
                unit_cost=line.unit_price,
                total_cost=line.line_total,
            )
        )
        if plant:
            # A tray-size line credits that variant's own stock (quantity = number of trays received), exactly how a tray sale
            # deducts it on the website -- never the plant's plain per-unit stock.
            adjust_stock(
                db,
                plant_id=plant.id,
                variant_id=line.variant_id,
                quantity_delta=int(round(line.quantity)),
                transaction_type="PURCHASE_RECEIVED",
                source_type="PURCHASE_ORDER",
                source_id=order.id,
                reference=f"PURCHASE_ORDER:{order.id}:PURCHASE_RECEIVED:{line.variant_id or plant.id}",
                created_by=admin,
            )
        plant_total += line.line_total

    if supply_specs:
        # supplies go to their lot batches (never to plant stock); duplicate supplier bill numbers are stopped here
        create_supply_bill(db, contact=order.contact, bill_number=bill_number, fallback_number=f"BILL-{order.order_number}", purchase_date=today, lines=supply_specs, admin=admin,
                           request_id=None, override_duplicate=payload.allow_duplicate_bill, override_reason=payload.duplicate_reason, purchase=bill, extra_total=plant_total)
    else:
        from app.supply_inventory import check_duplicate_bill

        reason = check_duplicate_bill(db, order.contact, bill_number, payload.allow_duplicate_bill, payload.duplicate_reason, exclude_id=bill.id)
        if reason:
            bill.duplicate_override_reason, bill.duplicate_override_by = reason, admin
        bill.total_cost = round(plant_total, 2)

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
