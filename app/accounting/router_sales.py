from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.accounting.audit import record_change
from app.accounting.notifications import queue_invoice_created, queue_payment_received, queue_sales_order_created
from app.accounting.models import (
    Contact,
    Invoice,
    InvoiceItem,
    PaymentIn,
    SalesOrder,
    SalesOrderItem,
)
from app.accounting.permissions import SALES_WRITE_ROLES, require_accounting_action
from app.models import Plant, PlantVariant
from app.accounting.schemas import (
    InvoiceConvertIn,
    InvoiceOut,
    PaymentInIn,
    PaymentInOut,
    SalesOrderIn,
    SalesOrderOut,
)
from app.database import get_db
from app.deps import get_current_admin
from app.inventory import allocate_stock, restore_stock
from app.models import InventoryTransaction
from app.stock_orders import queue_stock_team_new_order

router = APIRouter(tags=["accounting-sales"])


def _attach_delivery_status(db: Session, sales_orders) -> None:
    """Sets `delivery_status` on each sales order from its latest delivery,
    in one query for the whole list (no per-row lookups)."""
    from app.delivery.models import Delivery

    orders = [o for o in sales_orders if o is not None]
    if not orders:
        return
    latest: dict[int, str] = {}
    rows = (
        db.query(Delivery.sales_order_id, Delivery.status)
        .filter(Delivery.sales_order_id.in_([o.id for o in orders]))
        .order_by(Delivery.id)
        .all()
    )
    for sales_order_id, status in rows:
        latest[sales_order_id] = status
    for o in orders:
        o.delivery_status = latest.get(o.id)


def _sale_reference(order_id: int, kind: str, line) -> str:
    """Idempotency key for a sales-order line's stock movement. Tray lines
    get their own key so they hit the tray's stock, not the plant's."""
    base = f"SALES_ORDER:{order_id}:{kind}:{line.plant_id}"
    return f"{base}:V{line.variant_id}" if line.variant_id else base


# ---------- Sales Orders ----------

@router.get("/sales-orders", response_model=list[SalesOrderOut])
def list_sales_orders(
    source: Optional[str] = Query(None, description="online|offline"),
    status: Optional[str] = Query(None),
    contact_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None, description="Search by order # or contact name"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(SalesOrder).options(
        joinedload(SalesOrder.contact), joinedload(SalesOrder.items), joinedload(SalesOrder.invoices)
    )
    if source in ("online", "offline"):
        query = query.filter(SalesOrder.source == source)
    if status:
        query = query.filter(SalesOrder.status == status)
    if contact_id:
        query = query.filter(SalesOrder.contact_id == contact_id)
    if q:
        like = f"%{q}%"
        query = query.join(Contact, Contact.id == SalesOrder.contact_id).filter(
            SalesOrder.order_number.ilike(like) | Contact.name.ilike(like)
        )
    orders = query.order_by(SalesOrder.order_date.desc()).all()
    _attach_delivery_status(db, orders)
    return orders


@router.get("/sales-orders/{item_id}", response_model=SalesOrderOut)
def get_sales_order(
    item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = (
        db.query(SalesOrder)
        .options(joinedload(SalesOrder.contact), joinedload(SalesOrder.items), joinedload(SalesOrder.invoices))
        .filter(SalesOrder.id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Sales order not found")
    from app.inventory_router import stock_position

    for line in item.items:
        if line.plant_id:
            pos = stock_position(db, line.plant_id, line.variant_id)
            line.physical_stock = pos.get("physical_stock")
            line.reserved_stock = pos.get("reserved_stock")
            line.available_stock = pos.get("available_stock")
    return item


def _add_lines(db: Session, order: SalesOrder, lines) -> float:
    """Adds the given line items to `order` and returns their subtotal.
    Shared by create and edit so both apply exactly the same checks."""
    subtotal = 0.0
    for line in lines:
        if line.plant_id is not None and not db.query(Plant.id).filter(Plant.id == line.plant_id).first():
            raise HTTPException(status_code=400, detail=f"Unknown plant id {line.plant_id}")
        tray_size = None
        if line.variant_id is not None:
            variant = db.query(PlantVariant).filter(PlantVariant.id == line.variant_id, PlantVariant.plant_id == line.plant_id).first()
            if not variant:
                raise HTTPException(status_code=400, detail="Unknown tray-size option for this plant")
            tray_size = variant.tray_size
        line_total = round(line.quantity * line.unit_price, 2)
        subtotal += line_total
        db.add(
            SalesOrderItem(
                sales_order_id=order.id,
                plant_id=line.plant_id,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                tax_rate_id=line.tax_rate_id,
                line_total=line_total,
                variant_id=line.variant_id,
                tray_size=tray_size,
                to_prepare=bool(line.to_prepare),
                allocated_quantity=0,
            )
        )
    return subtotal


@router.post("/sales-orders", response_model=SalesOrderOut, status_code=201)
def create_sales_order(
    payload: SalesOrderIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("CREATE", SALES_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    if not payload.items:
        raise HTTPException(status_code=400, detail="At least one line item is required")
    contact = db.query(Contact).filter(Contact.id == payload.contact_id).first()
    if not contact:
        raise HTTPException(status_code=400, detail="Unknown contact")

    subtotal = 0.0
    tax_total = 0.0
    order = SalesOrder(
        contact_id=contact.id,
        order_number="",  # set after flush once we have the id
        status="Draft",
        order_date=payload.order_date,
        delivery_date=payload.delivery_date,
        notes=payload.notes,
        source="offline",
        created_by=admin,
    )
    db.add(order)
    db.flush()
    order.order_number = f"SO-{order.id}"

    subtotal = _add_lines(db, order, payload.items)
    order.subtotal = round(subtotal, 2)
    order.tax_total = round(tax_total, 2)
    order.total_amount = round(subtotal + tax_total, 2)
    db.commit()
    db.refresh(order)
    record_change(db, "accounting_sales_orders", order.id, "create", changed_by=admin)
    db.commit()
    queue_sales_order_created(order)
    queue_stock_team_new_order(order, db)
    return get_sales_order(order.id, admin, db)


@router.put("/sales-orders/{item_id}", response_model=SalesOrderOut)
def update_sales_order(
    item_id: int,
    payload: SalesOrderIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("EDIT", SALES_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """Edit an offline Sales Order that is still a Draft. Once it has been
    converted to an invoice (or cancelled/voided) the invoice, payments and
    stock already depend on its lines, so it is locked -- void the invoice
    instead."""
    order = db.query(SalesOrder).filter(SalesOrder.id == item_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Sales order not found")
    if order.source != "offline":
        raise HTTPException(status_code=400, detail="Website orders mirror the customer's order and can't be edited here")
    if order.status != "Draft" or db.query(Invoice.id).filter(Invoice.sales_order_id == order.id).first():
        raise HTTPException(status_code=400, detail="Only a Draft sales order that has no invoice yet can be edited")
    if not payload.items:
        raise HTTPException(status_code=400, detail="At least one line item is required")
    contact = db.query(Contact).filter(Contact.id == payload.contact_id).first()
    if not contact:
        raise HTTPException(status_code=400, detail="Unknown contact")

    before = {"contact_id": order.contact_id, "order_date": str(order.order_date), "notes": order.notes, "total_amount": order.total_amount}
    order.items.clear()
    db.flush()
    subtotal = _add_lines(db, order, payload.items)
    order.contact_id = contact.id
    order.order_date = payload.order_date
    previous_delivery_date = order.delivery_date
    order.delivery_date = payload.delivery_date
    order.notes = payload.notes
    order.subtotal = round(subtotal, 2)
    order.tax_total = 0.0
    order.total_amount = round(subtotal, 2)
    changes = {k: (v, {"contact_id": order.contact_id, "order_date": str(order.order_date), "notes": order.notes, "total_amount": order.total_amount}[k]) for k, v in before.items()}
    changes = {k: v for k, v in changes.items() if v[0] != v[1]}
    changes["line_items"] = ("replaced", f"{len(payload.items)} line(s)")
    db.commit()
    record_change(db, "accounting_sales_orders", order.id, "edit", changed_by=admin, changes=changes)
    db.commit()
    if order.delivery_date and (not previous_delivery_date or previous_delivery_date.date() != order.delivery_date.date()):
        from app.notifications import notify_sales_order_delivery_date

        notify_sales_order_delivery_date(order)
    return get_sales_order(order.id, admin, db)


@router.post("/sales-orders/{item_id}/convert-to-invoice", response_model=InvoiceOut)
def convert_to_invoice(
    item_id: int,
    payload: InvoiceConvertIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("CREATE", SALES_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """Converts an (offline) Sales Order into an Invoice. The original Sales
    Order is NEVER deleted or overwritten -- it stays exactly as-is, with its
    status flipped to "Invoiced" and a new, separate Invoice row created
    alongside it, linked back via invoice.sales_order_id."""
    order = (
        db.query(SalesOrder).options(joinedload(SalesOrder.items)).filter(SalesOrder.id == item_id).first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Sales order not found")
    if order.status in ("Cancelled", "Voided"):
        raise HTTPException(status_code=400, detail=f"Cannot invoice a {order.status} sales order")

    existing = db.query(Invoice).filter(Invoice.sales_order_id == order.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="This sales order already has an invoice")

    invoice = Invoice(
        sales_order_id=order.id,
        contact_id=order.contact_id,
        invoice_number="",
        status="Draft",
        invoice_date=datetime.utcnow(),
        due_date=payload.due_date,
        subtotal=order.subtotal,
        tax_total=order.tax_total,
        total_amount=order.total_amount,
        balance_due=order.total_amount,
        source="offline",
    )
    db.add(invoice)
    db.flush()
    invoice.invoice_number = f"INV-{invoice.id}"
    invoice.status = "Sent"

    for line in order.items:
        db.add(
            InvoiceItem(
                invoice_id=invoice.id,
                plant_id=line.plant_id,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                tax_rate_id=line.tax_rate_id,
                tax_amount=line.tax_amount,
                line_total=line.line_total,
            )
        )
        # This is the one clear "the sale is now real and committed" event
        # in the offline flow (a Draft Sales Order can still be edited/
        # abandoned without ever costing inventory) -- deducts the SAME
        # shared Plant.stock_quantity the website's own checkout uses, so
        # an offline sale reduces what the website shows as available too.
        if line.plant_id:
            # Take what is in stock for the part not already allocated; the
            # rest stays pending (the invoice is never blocked by stock).
            need = 0 if line.to_prepare else max(0, (line.quantity or 0) - line.allocated)
            if need:
                line.allocated_quantity = line.allocated + allocate_stock(
                    db,
                    plant_id=line.plant_id,
                    variant_id=line.variant_id,
                    quantity=need,
                    source_type="SALES_ORDER",
                    source_id=order.id,
                    reference=_sale_reference(order.id, "SALE", line),
                    created_by=admin,
                )

    old_status = order.status
    order.status = "Invoiced"
    db.commit()
    db.refresh(invoice)
    record_change(
        db,
        "accounting_sales_orders",
        order.id,
        "convert",
        changed_by=admin,
        changes={"status": (old_status, "Invoiced")},
    )
    record_change(db, "accounting_invoices", invoice.id, "create", changed_by=admin)
    db.commit()
    queue_invoice_created(invoice)
    return get_invoice(invoice.id, admin, db)


# ---------- Invoices ----------

@router.get("/invoices", response_model=list[InvoiceOut])
def list_invoices(
    source: Optional[str] = Query(None, description="online|offline"),
    status: Optional[str] = Query(None),
    contact_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None, description="Search by invoice # or contact name"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Invoice).options(
        joinedload(Invoice.contact), joinedload(Invoice.items), joinedload(Invoice.sales_order)
    )
    if source in ("online", "offline"):
        query = query.filter(Invoice.source == source)
    if status:
        query = query.filter(Invoice.status == status)
    if contact_id:
        query = query.filter(Invoice.contact_id == contact_id)
    if q:
        like = f"%{q}%"
        query = query.join(Contact, Contact.id == Invoice.contact_id).filter(
            Invoice.invoice_number.ilike(like) | Contact.name.ilike(like)
        )
    invoices = query.order_by(Invoice.invoice_date.desc()).all()
    _attach_delivery_status(db, [i.sales_order for i in invoices])
    return invoices


@router.get("/invoices/{item_id}", response_model=InvoiceOut)
def get_invoice(
    item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = (
        db.query(Invoice)
        .options(joinedload(Invoice.contact), joinedload(Invoice.items), joinedload(Invoice.sales_order))
        .filter(Invoice.id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Invoice not found")
    _attach_delivery_status(db, [item.sales_order])
    return item


@router.post("/invoices/{item_id}/void", response_model=InvoiceOut)
def void_invoice(
    item_id: int,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("CANCEL", SALES_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """Never a hard delete -- financial documents are Voided, not removed."""
    item = (
        db.query(Invoice)
        .options(joinedload(Invoice.sales_order).joinedload(SalesOrder.items))
        .filter(Invoice.id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if item.source == "online":
        raise HTTPException(
            status_code=400,
            detail="This invoice was auto-generated from a real website order and can't be voided here "
            "-- cancel the order itself from the Orders page instead.",
        )
    old_status = item.status
    already_voided = old_status == "Voided"
    item.status = "Voided"
    if not already_voided:
        item.voided_by = admin
        item.voided_at = datetime.utcnow()

    # convert_to_invoice deducted stock for this sale -- voiding it reverses
    # that exactly once (the `reference` below makes a second void attempt,
    # or voiding an already-Voided invoice, a safe no-op).
    if not already_voided and item.sales_order:
        for line in item.sales_order.items:
            if line.plant_id and line.allocated > 0:
                # Invoices made before tray lines deducted tray stock took it
                # from the plant itself -- give it back to wherever it came from.
                legacy_plant_level = bool(line.variant_id) and db.query(InventoryTransaction.id).filter(
                    InventoryTransaction.reference == f"SALES_ORDER:{item.sales_order_id}:SALE:{line.plant_id}"
                ).first() is not None
                from_tray = bool(line.variant_id) and not legacy_plant_level
                restore_stock(
                    db,
                    plant_id=line.plant_id,
                    variant_id=line.variant_id if from_tray else None,
                    quantity=line.allocated,
                    source_type="SALES_ORDER_VOID",
                    source_id=item.sales_order_id,
                    reference=(
                        _sale_reference(item.sales_order_id, "SALE_REVERSAL", line)
                        if from_tray
                        else f"SALES_ORDER:{item.sales_order_id}:SALE_REVERSAL:{line.plant_id}"
                    ),
                    created_by=admin,
                )
                line.allocated_quantity = 0

    db.commit()
    record_change(
        db,
        "accounting_invoices",
        item.id,
        "void",
        changed_by=admin,
        changes={"status": (old_status, "Voided")},
    )
    db.commit()
    return get_invoice(item.id, admin, db)


# ---------- Payments In ----------

@router.get("/payments-in", response_model=list[PaymentInOut])
def list_payments_in(
    source: Optional[str] = Query(None, description="online|offline"),
    contact_id: Optional[int] = Query(None),
    invoice_id: Optional[int] = Query(None),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(PaymentIn)
    if source in ("online", "offline"):
        query = query.filter(PaymentIn.source == source)
    if contact_id:
        query = query.filter(PaymentIn.contact_id == contact_id)
    if invoice_id:
        query = query.filter(PaymentIn.invoice_id == invoice_id)
    return query.order_by(PaymentIn.payment_date.desc()).all()


@router.post("/payments-in", response_model=PaymentInOut, status_code=201)
def create_payment_in(
    payload: PaymentInIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("CREATE", SALES_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    invoice = db.query(Invoice).filter(Invoice.id == payload.invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=400, detail="Unknown invoice")
    if invoice.status in ("Cancelled", "Voided"):
        raise HTTPException(status_code=400, detail=f"Cannot record a payment against a {invoice.status} invoice")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    payment = PaymentIn(
        invoice_id=invoice.id,
        contact_id=invoice.contact_id,
        amount=payload.amount,
        method=payload.method,
        payment_date=payload.payment_date,
        reference=payload.reference,
        notes=payload.notes,
        source="offline",
        recorded_by=admin,
    )
    db.add(payment)
    db.flush()

    total_paid = (
        db.query(func.coalesce(func.sum(PaymentIn.amount), 0))
        .filter(PaymentIn.invoice_id == invoice.id)
        .scalar()
        or 0
    )
    invoice.amount_paid = round(total_paid, 2)
    invoice.balance_due = round(max(invoice.total_amount - total_paid, 0), 2)
    old_status = invoice.status
    invoice.status = "Paid" if invoice.balance_due <= 0 else "PartiallyPaid"

    db.commit()
    db.refresh(payment)
    record_change(db, "accounting_payments_in", payment.id, "create", changed_by=admin)
    if invoice.status != old_status:
        record_change(
            db,
            "accounting_invoices",
            invoice.id,
            "update",
            changed_by=admin,
            changes={"status": (old_status, invoice.status)},
        )
    db.commit()
    queue_payment_received(payment, invoice)
    return payment
