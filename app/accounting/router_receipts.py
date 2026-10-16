"""Customer advance money, refunds, voided-invoice payment decisions and linked contacts.

All balances come from app.accounting.balances. Nothing here deletes a payment or an
invoice; every decision is its own dated record with the admin's name."""
import re
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounting.audit import record_change
from app.accounting.balances import (
    DEAD,
    apply_advance,
    contact_position,
    group_ids,
    money,
    open_receipts,
    receipt_remaining,
    recompute_invoice,
)
from app.accounting.models import (
    Contact,
    ContactLink,
    CustomerReceipt,
    CustomerRefund,
    Invoice,
    PaymentIn,
    ReceiptAllocation,
)
from app.accounting.permissions import SALES_WRITE_ROLES, require_accounting_action
from app.database import get_db
from app.deps import get_current_admin

router = APIRouter(tags=["accounting-receipts"])
MAX_AMOUNT = 1_000_000_000
METHODS = ("Cash", "Bank", "UPI", "Card", "Online", "Other")
CREATE = Depends(require_accounting_action("CREATE", SALES_WRITE_ROLES))
EDIT = Depends(require_accounting_action("EDIT", SALES_WRITE_ROLES))


def _contact(db: Session, contact_id: int) -> Contact:
    c = db.query(Contact).filter(Contact.id == contact_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found")
    return c


def _receipt_out(db: Session, r: CustomerReceipt) -> dict:
    refunds = [{"id": f.id, "amount": f.amount, "method": f.method, "date": f.refund_date, "reason": f.reason, "by": f.created_by}
               for f in db.query(CustomerRefund).filter(CustomerRefund.receipt_id == r.id).order_by(CustomerRefund.id)]
    allocs = [{"id": a.id, "invoice_id": a.invoice_id, "invoice_number": inv.invoice_number if inv else "", "amount": a.amount, "live": bool(inv and inv.status not in DEAD), "date": a.created_at}
              for a, inv in (db.query(ReceiptAllocation, Invoice).join(Invoice, Invoice.id == ReceiptAllocation.invoice_id).filter(ReceiptAllocation.receipt_id == r.id).order_by(ReceiptAllocation.id))]
    return {
        "id": r.id, "contact_id": r.contact_id, "amount": r.amount, "method": r.method, "payment_date": r.payment_date, "reference": r.reference or "", "notes": r.notes or "",
        "kind": r.kind, "invoice_id": r.invoice_id, "status": r.status, "recorded_by": r.recorded_by, "remaining": receipt_remaining(db, r), "refunds": refunds, "allocations": allocs,
    }


def unresolved_void_payments(db: Session, ids: list[int]) -> list[dict]:
    rows = []
    for inv in db.query(Invoice).filter(Invoice.contact_id.in_(ids), Invoice.status.in_(DEAD), Invoice.void_disposition.is_(None)).order_by(Invoice.id):
        amount = float(db.query(func.coalesce(func.sum(PaymentIn.amount), 0)).filter(PaymentIn.invoice_id == inv.id).scalar() or 0)
        if amount > 0:
            rows.append({"invoice_id": inv.id, "invoice_number": inv.invoice_number, "status": inv.status, "amount": money(amount), "contact_id": inv.contact_id})
    return rows


# ------------------------------------------------------------------ position
@router.get("/customers/{contact_id}/position")
def customer_position(contact_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    contact = _contact(db, contact_id)
    pos = contact_position(db, contact.id)
    ids = pos["contact_ids"]
    members = [{"id": c.id, "name": c.name, "phone": c.phone or "", "source": c.source} for c in db.query(Contact).filter(Contact.id.in_(ids)).order_by(Contact.id)]
    receipts = db.query(CustomerReceipt).filter(CustomerReceipt.contact_id.in_(ids)).order_by(CustomerReceipt.payment_date.desc(), CustomerReceipt.id.desc()).limit(100).all()
    return {**pos, "linked_contacts": members, "receipts": [_receipt_out(db, r) for r in receipts], "unresolved_void_payments": unresolved_void_payments(db, ids)}


# ------------------------------------------------------------------ receipts (advance)
class ReceiptIn(BaseModel):
    amount: float = Field(gt=0, le=MAX_AMOUNT)
    method: str = "Cash"
    payment_date: Optional[datetime] = None
    reference: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=1000)
    request_id: str = Field(min_length=8, max_length=60)


@router.post("/customers/{contact_id}/receipts", status_code=201, dependencies=[CREATE])
def create_receipt(contact_id: int, payload: ReceiptIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    contact = _contact(db, contact_id)
    if payload.method not in METHODS:
        raise HTTPException(status_code=400, detail="Unknown payment method")
    done = db.query(CustomerReceipt).filter(CustomerReceipt.request_id == payload.request_id).first()
    if done:
        return {**_receipt_out(db, done), "already_saved": True}
    r = CustomerReceipt(contact_id=contact.id, amount=money(payload.amount), method=payload.method, payment_date=payload.payment_date or datetime.utcnow(), reference=payload.reference.strip(),
                        notes=payload.notes.strip(), kind="advance", request_id=payload.request_id, recorded_by=admin)
    db.add(r)
    try:
        db.flush()
        record_change(db, "accounting_customer_receipts", r.id, "create", changed_by=admin)
        db.commit()
    except IntegrityError:
        db.rollback()
        done = db.query(CustomerReceipt).filter(CustomerReceipt.request_id == payload.request_id).first()
        if done:
            return {**_receipt_out(db, done), "already_saved": True}
        raise
    db.refresh(r)
    return {**_receipt_out(db, r), "already_saved": False}


class RefundIn(BaseModel):
    amount: float = Field(gt=0, le=MAX_AMOUNT)
    method: str = "Cash"
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/receipts/{receipt_id}/refund", dependencies=[EDIT])
def refund_receipt(receipt_id: int, payload: RefundIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    r = db.query(CustomerReceipt).filter(CustomerReceipt.id == receipt_id).first()
    if not r or r.status != "Active":
        raise HTTPException(status_code=404, detail="Advance not found")
    if payload.method not in METHODS:
        raise HTTPException(status_code=400, detail="Unknown payment method")
    remaining = receipt_remaining(db, r)
    if payload.amount > remaining + 0.004:
        raise HTTPException(status_code=400, detail=f"Only {remaining:,.2f} of this advance is left to refund")
    f = CustomerRefund(receipt_id=r.id, contact_id=r.contact_id, amount=money(payload.amount), method=payload.method, reason=payload.reason.strip(), created_by=admin)
    db.add(f)
    db.flush()
    record_change(db, "accounting_customer_refunds", f.id, "create", changed_by=admin)
    db.commit()
    return _receipt_out(db, r)


@router.post("/receipts/{receipt_id}/reverse", dependencies=[EDIT])
def reverse_receipt(receipt_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """For an advance entered by mistake. Only possible while nothing has been used or refunded."""
    r = db.query(CustomerReceipt).filter(CustomerReceipt.id == receipt_id).first()
    if not r or r.status != "Active":
        raise HTTPException(status_code=404, detail="Advance not found")
    if r.kind == "void_transfer":
        raise HTTPException(status_code=400, detail="This advance came from a voided invoice and cannot be reversed")
    used = db.query(ReceiptAllocation.id).filter(ReceiptAllocation.receipt_id == r.id).first() or db.query(CustomerRefund.id).filter(CustomerRefund.receipt_id == r.id).first()
    if used:
        raise HTTPException(status_code=400, detail="This advance was already used or refunded, so it cannot be reversed")
    r.status = "Reversed"
    record_change(db, "accounting_customer_receipts", r.id, "update", changed_by=admin, changes={"status": ("Active", "Reversed")})
    db.commit()
    return _receipt_out(db, r)


# ------------------------------------------------------------------ apply advance to an invoice
class ApplyAdvanceIn(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0, le=MAX_AMOUNT)  # default: as much as the invoice needs


@router.post("/invoices/{invoice_id}/apply-advance", dependencies=[EDIT])
def apply_advance_to_invoice(invoice_id: int, payload: ApplyAdvanceIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv.status in DEAD:
        raise HTTPException(status_code=400, detail=f"Cannot use an advance on a {inv.status} invoice")
    if inv.balance_due <= 0:
        raise HTTPException(status_code=400, detail="This invoice is already fully paid")
    ids = group_ids(db, inv.contact_id)
    avail = sum(rem for _, rem in open_receipts(db, ids))
    if avail <= 0:
        raise HTTPException(status_code=400, detail="This customer has no advance left")
    want = payload.amount if payload.amount is not None else avail
    if want > avail + 0.004:
        raise HTTPException(status_code=400, detail=f"Only {avail:,.2f} of advance is available")
    applied = apply_advance(db, inv, want, admin)
    record_change(db, "accounting_invoices", inv.id, "update", changed_by=admin, changes={"advance_applied": (0, applied)})
    db.commit()
    return {"applied": applied, "amount_paid": inv.amount_paid, "balance_due": inv.balance_due, "status": inv.status}


# ------------------------------------------------------------------ what to do with payments on a voided invoice
def resolve_void_payments(db: Session, inv: Invoice, action: str, admin: str, method: str = "Cash", notes: str = "") -> float:
    """Explicit, one-time decision. 'advance' keeps the money as the customer's advance; 'refund'
    records that it was handed back (the advance and the refund are both written, so history is
    complete). Payment rows are never touched. Returns the amount decided."""
    amount = money(db.query(func.coalesce(func.sum(PaymentIn.amount), 0)).filter(PaymentIn.invoice_id == inv.id).scalar())
    if amount <= 0:
        inv.void_disposition = inv.void_disposition or "advance"
        return 0.0
    if inv.void_disposition:
        raise HTTPException(status_code=400, detail="The payments of this invoice were already decided")
    receipt = CustomerReceipt(contact_id=inv.contact_id, amount=amount, method=method if method in METHODS else "Cash", payment_date=datetime.utcnow(), reference=f"Voided {inv.invoice_number}",
                              notes=(notes or "").strip(), kind="void_transfer", invoice_id=inv.id, request_id=f"void:{inv.id}", recorded_by=admin)
    db.add(receipt)
    db.flush()
    if action == "refund":
        db.add(CustomerRefund(receipt_id=receipt.id, contact_id=inv.contact_id, amount=amount, method=receipt.method, reason=(notes or f"Refund for voided {inv.invoice_number}").strip(), created_by=admin))
    inv.void_disposition = action
    record_change(db, "accounting_customer_receipts", receipt.id, "create", changed_by=admin, changes={"from_voided_invoice": (None, inv.invoice_number), "action": (None, action), "amount": (0, amount)})
    return amount


class ResolveVoidIn(BaseModel):
    action: Literal["advance", "refund"]
    method: str = "Cash"
    notes: str = Field(default="", max_length=1000)


@router.post("/invoices/{invoice_id}/resolve-void-payments", dependencies=[EDIT])
def resolve_void_endpoint(invoice_id: int, payload: ResolveVoidIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not inv or inv.status not in DEAD:
        raise HTTPException(status_code=404, detail="Voided invoice not found")
    amount = resolve_void_payments(db, inv, payload.action, admin, payload.method, payload.notes)
    db.commit()
    return {"invoice_id": inv.id, "action": payload.action, "amount": amount}


# ------------------------------------------------------------------ linked contacts
def _last10(phone: str) -> str:
    d = re.sub(r"\D", "", phone or "")
    return d[-10:] if len(d) >= 10 else ""


def _link_out(db: Session, link: ContactLink) -> dict:
    a = db.query(Contact).filter(Contact.id == link.contact_a_id).first()
    b = db.query(Contact).filter(Contact.id == link.contact_b_id).first()
    pa = contact_position(db, a.id)["own_net"] if a else 0
    pb = contact_position(db, b.id)["own_net"] if b else 0
    card = lambda c, net: {"id": c.id, "name": c.name, "phone": c.phone or "", "source": c.source, "net": net} if c else None
    return {"id": link.id, "status": link.status, "a": card(a, pa), "b": card(b, pb), "reviewed_by": link.reviewed_by, "reviewed_at": link.reviewed_at}


@router.get("/contact-links")
def list_links(status: Optional[str] = Query(None), admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    q = db.query(ContactLink)
    if status:
        q = q.filter(ContactLink.status == status)
    return [_link_out(db, link) for link in q.order_by(ContactLink.id.desc()).limit(200)]


@router.get("/contact-links/suggestions")
def link_suggestions(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Customers that share the same mobile number but are not linked yet. Suggestions only:
    nothing is linked until an admin confirms."""
    by_phone: dict[str, list[Contact]] = {}
    for c in db.query(Contact).filter(Contact.contact_type.in_(("customer", "both")), Contact.is_active.is_(True)):
        key = _last10(c.phone)
        if key:
            by_phone.setdefault(key, []).append(c)
    known = {(l.contact_a_id, l.contact_b_id) for l in db.query(ContactLink)}
    out = []
    for key, contacts in by_phone.items():
        contacts.sort(key=lambda c: c.id)
        for i in range(len(contacts)):
            for j in range(i + 1, len(contacts)):
                a, b = contacts[i], contacts[j]
                if (a.id, b.id) in known:
                    continue
                out.append({"phone": key, "a": {"id": a.id, "name": a.name, "source": a.source, "net": contact_position(db, a.id)["own_net"]},
                            "b": {"id": b.id, "name": b.name, "source": b.source, "net": contact_position(db, b.id)["own_net"]}})
    return out


class LinkIn(BaseModel):
    contact_a_id: int
    contact_b_id: int


def _get_or_make_link(db: Session, a_id: int, b_id: int, admin: str) -> ContactLink:
    if a_id == b_id:
        raise HTTPException(status_code=400, detail="Choose two different customers")
    a, b = sorted((a_id, b_id))
    _contact(db, a)
    _contact(db, b)
    link = db.query(ContactLink).filter(ContactLink.contact_a_id == a, ContactLink.contact_b_id == b).first()
    if not link:
        link = ContactLink(contact_a_id=a, contact_b_id=b, status="Suggested", created_by=admin)
        db.add(link)
        db.flush()
    return link


@router.post("/contact-links/confirm", dependencies=[EDIT])
def confirm_pair(payload: LinkIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    link = _get_or_make_link(db, payload.contact_a_id, payload.contact_b_id, admin)
    link.status, link.reviewed_by, link.reviewed_at = "Confirmed", admin, datetime.utcnow()
    record_change(db, "accounting_contact_links", link.id, "update", changed_by=admin, changes={"status": (None, "Confirmed")})
    db.commit()
    return _link_out(db, link)


@router.post("/contact-links/reject", dependencies=[EDIT])
def reject_pair(payload: LinkIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    link = _get_or_make_link(db, payload.contact_a_id, payload.contact_b_id, admin)
    link.status, link.reviewed_by, link.reviewed_at = "Rejected", admin, datetime.utcnow()
    record_change(db, "accounting_contact_links", link.id, "update", changed_by=admin, changes={"status": (None, "Rejected")})
    db.commit()
    return _link_out(db, link)


@router.post("/contact-links/{link_id}/unlink", dependencies=[EDIT])
def unlink(link_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Takes a confirmed link back. Balances separate again; no record is changed."""
    link = db.query(ContactLink).filter(ContactLink.id == link_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    old = link.status
    link.status, link.reviewed_by, link.reviewed_at = "Rejected", admin, datetime.utcnow()
    record_change(db, "accounting_contact_links", link.id, "update", changed_by=admin, changes={"status": (old, "Rejected")})
    db.commit()
    return _link_out(db, link)
