from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.accounting.audit import record_change
from app.accounting.models import (
    Contact,
    Expense,
    Invoice,
    PaymentIn,
    PaymentOut,
    PurchaseOrder,
    SalesOrder,
)
from app.accounting.permissions import CONTACT_WRITE_ROLES, require_accounting_action
from app.accounting.schemas import ContactIn, ContactOut
from app.database import get_db
from app.deps import get_current_admin
from app.models import Purchase

router = APIRouter(prefix="/contacts", tags=["accounting-contacts"])


def _get_or_404(db: Session, item_id: int) -> Contact:
    item = db.query(Contact).filter(Contact.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Contact not found")
    return item


def _with_summary(db: Session, contact: Contact) -> ContactOut:
    total_sales = (
        db.query(func.coalesce(func.sum(Invoice.total_amount), 0))
        .filter(Invoice.contact_id == contact.id, Invoice.status != "Voided")
        .scalar()
        or 0
    )
    total_paid = (
        db.query(func.coalesce(func.sum(PaymentIn.amount), 0))
        .filter(PaymentIn.contact_id == contact.id)
        .scalar()
        or 0
    )
    total_purchases = (
        db.query(func.coalesce(func.sum(Purchase.total_cost), 0))
        .filter(Purchase.contact_id == contact.id)
        .scalar()
        or 0
    )
    total_paid_out = (
        db.query(func.coalesce(func.sum(PaymentOut.amount), 0))
        .filter(PaymentOut.contact_id == contact.id)
        .scalar()
        or 0
    )

    out = ContactOut.model_validate(contact)
    out.total_sales = round(total_sales, 2)
    out.total_paid = round(total_paid, 2)
    out.outstanding = round(total_sales - total_paid, 2)
    out.total_purchases = round(total_purchases, 2)
    out.total_paid_out = round(total_paid_out, 2)
    out.payable = round(total_purchases - total_paid_out, 2)

    out.orders_count = db.query(SalesOrder).filter(SalesOrder.contact_id == contact.id).count()
    out.invoices_count = db.query(Invoice).filter(Invoice.contact_id == contact.id).count()
    out.bills_count = db.query(Purchase).filter(Purchase.contact_id == contact.id).count()
    out.payments_count = (
        db.query(PaymentIn).filter(PaymentIn.contact_id == contact.id).count()
        + db.query(PaymentOut).filter(PaymentOut.contact_id == contact.id).count()
    )

    online_sales, offline_sales = _channel_sales(db, contact.id)
    out.online_sales = online_sales
    out.offline_sales = offline_sales

    channels = set()
    online_count = 0
    offline_count = 0
    for model, date_col in _CHANNEL_SOURCES:
        rows = (
            db.query(model.source, func.count(model.id), func.max(date_col))
            .filter(model.contact_id == contact.id)
            .group_by(model.source)
            .all()
        )
        for source_value, count, max_date in rows:
            if source_value == "online":
                channels.add("online")
                online_count += count
            elif source_value == "offline":
                channels.add("offline")
                offline_count += count
    out.channels = sorted(channels)  # ["offline"] < ["offline", "online"] alpha order is fine, UI re-labels
    out.online_transaction_count = online_count
    out.offline_transaction_count = offline_count
    out.last_transaction_date = _last_transaction_date(db, contact.id)
    return out


# (model, date_column) pairs for every document type that carries both a
# contact_id and a source -- used to compute a party's *actual* channel mix
# (never a fixed label) and combined transaction counts.
_CHANNEL_SOURCES = [
    (SalesOrder, SalesOrder.order_date),
    (Invoice, Invoice.invoice_date),
    (PaymentIn, PaymentIn.payment_date),
    (Purchase, Purchase.purchase_date),
    (PurchaseOrder, PurchaseOrder.order_date),
    (PaymentOut, PaymentOut.payment_date),
    (Expense, Expense.expense_date),
]


def _channel_sales(db: Session, contact_id: int):
    online = (
        db.query(func.coalesce(func.sum(Invoice.total_amount), 0))
        .filter(Invoice.contact_id == contact_id, Invoice.status != "Voided", Invoice.source == "online")
        .scalar()
        or 0
    )
    offline = (
        db.query(func.coalesce(func.sum(Invoice.total_amount), 0))
        .filter(Invoice.contact_id == contact_id, Invoice.status != "Voided", Invoice.source == "offline")
        .scalar()
        or 0
    )
    return round(online, 2), round(offline, 2)


def _last_transaction_date(db: Session, contact_id: int):
    dates = []
    for model, date_col in _CHANNEL_SOURCES:
        d = db.query(func.max(date_col)).filter(model.contact_id == contact_id).scalar()
        if d:
            dates.append(d)
    return max(dates) if dates else None


@router.get("", response_model=list[ContactOut])
def list_contacts(
    source: Optional[str] = Query(None, description="online|offline"),
    contact_type: Optional[str] = Query(None, description="customer|supplier|both"),
    q: Optional[str] = Query(None, description="Search by name, email, or phone"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Contact)
    if source in ("online", "offline"):
        query = query.filter(Contact.source == source)
    if contact_type:
        query = query.filter(Contact.contact_type == contact_type)
    if q:
        like = f"%{q}%"
        query = query.filter(Contact.name.ilike(like) | Contact.email.ilike(like) | Contact.phone.ilike(like))
    contacts = query.order_by(Contact.name).all()
    return [_with_summary(db, c) for c in contacts]


@router.get("/{item_id}", response_model=ContactOut)
def get_contact(
    item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    return _with_summary(db, _get_or_404(db, item_id))


@router.post("", response_model=ContactOut, status_code=201)
def create_contact(
    payload: ContactIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("CREATE", CONTACT_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    item = Contact(**payload.model_dump(), source="offline", created_by=admin)
    db.add(item)
    db.commit()
    db.refresh(item)
    record_change(db, "accounting_contacts", item.id, "create", changed_by=admin)
    db.commit()
    return _with_summary(db, item)


@router.put("/{item_id}", response_model=ContactOut)
def update_contact(
    item_id: int,
    payload: ContactIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("EDIT", CONTACT_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    if item.source == "online":
        raise HTTPException(
            status_code=400,
            detail="This contact is linked to a real website customer and can't be edited here.",
        )
    changes = {}
    for field, value in payload.model_dump().items():
        old = getattr(item, field)
        if old != value:
            changes[field] = (old, value)
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    if changes:
        record_change(db, "accounting_contacts", item.id, "update", changed_by=admin, changes=changes)
        db.commit()
    return _with_summary(db, item)


@router.delete("/{item_id}", status_code=204)
def delete_contact(
    item_id: int,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("DELETE", CONTACT_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    if item.source == "online":
        raise HTTPException(
            status_code=400,
            detail="This contact is linked to a real website customer and can't be deleted.",
        )
    has_docs = (
        db.query(Invoice).filter(Invoice.contact_id == item.id).first()
        or db.query(PaymentIn).filter(PaymentIn.contact_id == item.id).first()
        or db.query(Purchase).filter(Purchase.contact_id == item.id).first()
        or db.query(PaymentOut).filter(PaymentOut.contact_id == item.id).first()
        or db.query(PurchaseOrder).filter(PurchaseOrder.contact_id == item.id).first()
        or db.query(SalesOrder).filter(SalesOrder.contact_id == item.id).first()
    )
    if has_docs:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a contact with existing sales/purchase orders, invoices, bills, or payments.",
        )
    db.delete(item)
    db.commit()