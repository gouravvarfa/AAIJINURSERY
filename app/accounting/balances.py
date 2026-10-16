"""The one place that knows how much a customer owes (or has paid in advance).

Every screen, report and PDF asks `position()`; nothing else adds up invoices and payments.

Definitions (for a customer = one contact, plus every contact it is Confirmed-linked to;
each invoice / payment / receipt belongs to exactly ONE contact, so adding contacts together
counts everything once):

    posted invoice      = status not Voided / Cancelled
    A    posted total   = sum of total_amount of posted invoices
    Pinv                = payments (accounting_payments_in) on posted invoices
    Alloc               = advance receipts applied to posted invoices
    Rcp                 = active customer receipts (advance / overpayment / void transfer)
    Ref                 = refunds given out of those receipts
    Hold                = payments on a voided invoice nobody has decided about yet
                          (kept as credit so nothing disappears, flagged for the admin)

    Net balance = A - Pinv - Rcp + Ref - Hold          (> 0 customer owes, < 0 customer has advance)
    Due         = sum over posted invoices of max(total - payments - allocations, 0)
    Credit      = Due - Net                            (advance money the customer has with us)

Allocating an advance to an invoice moves money from Credit to that invoice's payments, so Net
is unchanged: nothing is counted twice. Sales Orders never count.
"""
from collections import defaultdict
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.accounting.models import (
    Contact,
    ContactLink,
    CustomerReceipt,
    CustomerRefund,
    Invoice,
    PaymentIn,
    ReceiptAllocation,
)

DEAD = ("Voided", "Cancelled")


def money(v) -> float:
    return round(float(v or 0) + 0.0, 2)


def group_ids(db: Session, contact_id: int) -> list[int]:
    """The contact plus everything connected to it through Confirmed links (transitively)."""
    seen = {contact_id}
    frontier = [contact_id]
    while frontier:
        rows = (
            db.query(ContactLink.contact_a_id, ContactLink.contact_b_id)
            .filter(ContactLink.status == "Confirmed", (ContactLink.contact_a_id.in_(frontier)) | (ContactLink.contact_b_id.in_(frontier)))
            .all()
        )
        frontier = []
        for a, b in rows:
            for c in (a, b):
                if c not in seen:
                    seen.add(c)
                    frontier.append(c)
    return sorted(seen)


def _paid_maps(db: Session, invoice_ids: list[int]):
    pay, alloc = defaultdict(float), defaultdict(float)
    if not invoice_ids:
        return pay, alloc
    for inv_id, amt in db.query(PaymentIn.invoice_id, func.sum(PaymentIn.amount)).filter(PaymentIn.invoice_id.in_(invoice_ids)).group_by(PaymentIn.invoice_id):
        pay[inv_id] = float(amt or 0)
    for inv_id, amt in (
        db.query(ReceiptAllocation.invoice_id, func.sum(ReceiptAllocation.amount))
        .join(CustomerReceipt, CustomerReceipt.id == ReceiptAllocation.receipt_id)
        .filter(ReceiptAllocation.invoice_id.in_(invoice_ids), CustomerReceipt.status == "Active")
        .group_by(ReceiptAllocation.invoice_id)
    ):
        alloc[inv_id] = float(amt or 0)
    return pay, alloc


def position(db: Session, contact_ids: list[int]) -> dict:
    ids = list(contact_ids)
    posted = db.query(Invoice.id, Invoice.total_amount).filter(Invoice.contact_id.in_(ids), Invoice.status.notin_(DEAD)).all()
    pay, alloc = _paid_maps(db, [i for i, _ in posted])
    A = sum(float(t or 0) for _, t in posted)
    Pinv = sum(pay[i] for i, _ in posted)
    Alloc = sum(alloc[i] for i, _ in posted)
    Due = sum(max(float(t or 0) - pay[i] - alloc[i], 0) for i, t in posted)
    Rcp = float(db.query(func.coalesce(func.sum(CustomerReceipt.amount), 0)).filter(CustomerReceipt.contact_id.in_(ids), CustomerReceipt.status == "Active").scalar() or 0)
    Ref = float(
        db.query(func.coalesce(func.sum(CustomerRefund.amount), 0))
        .join(CustomerReceipt, CustomerReceipt.id == CustomerRefund.receipt_id)
        .filter(CustomerRefund.contact_id.in_(ids), CustomerReceipt.status == "Active")
        .scalar() or 0
    )
    Hold = float(
        db.query(func.coalesce(func.sum(PaymentIn.amount), 0))
        .join(Invoice, Invoice.id == PaymentIn.invoice_id)
        .filter(Invoice.contact_id.in_(ids), Invoice.status.in_(DEAD), Invoice.void_disposition.is_(None))
        .scalar() or 0
    )
    net = A - Pinv - Rcp + Ref - Hold
    return {
        "contact_ids": ids,
        "invoiced": money(A),
        "due": money(Due),
        "advance": money(Due - net),
        "net": money(net),
        "unresolved_void_amount": money(Hold),
    }


def contact_position(db: Session, contact_id: int) -> dict:
    out = position(db, group_ids(db, contact_id))
    own = position(db, [contact_id]) if len(out["contact_ids"]) > 1 else out
    out["own_net"] = own["net"]
    return out


def recompute_invoice(db: Session, invoice: Invoice) -> None:
    """Invoice.amount_paid / balance_due / status always come from its payments and allocations."""
    pay, alloc = _paid_maps(db, [invoice.id])
    paid = pay[invoice.id] + alloc[invoice.id]
    invoice.amount_paid = round(paid, 2)
    invoice.balance_due = round(max((invoice.total_amount or 0) - paid, 0), 2)
    if invoice.status in DEAD:
        return
    if invoice.balance_due <= 0:
        invoice.status = "Paid"
    elif paid > 0:
        invoice.status = "PartiallyPaid"
    elif invoice.status in ("Paid", "PartiallyPaid"):
        invoice.status = "Sent"


def receipt_remaining(db: Session, receipt: CustomerReceipt) -> float:
    if receipt.status != "Active":
        return 0.0
    used = float(
        db.query(func.coalesce(func.sum(ReceiptAllocation.amount), 0))
        .join(Invoice, Invoice.id == ReceiptAllocation.invoice_id)
        .filter(ReceiptAllocation.receipt_id == receipt.id, Invoice.status.notin_(DEAD))
        .scalar() or 0
    )
    refunded = float(db.query(func.coalesce(func.sum(CustomerRefund.amount), 0)).filter(CustomerRefund.receipt_id == receipt.id).scalar() or 0)
    return money(max(receipt.amount - used - refunded, 0))


def open_receipts(db: Session, contact_ids: list[int]) -> list[tuple[CustomerReceipt, float]]:
    out = []
    for r in db.query(CustomerReceipt).filter(CustomerReceipt.contact_id.in_(contact_ids), CustomerReceipt.status == "Active").order_by(CustomerReceipt.payment_date, CustomerReceipt.id):
        rem = receipt_remaining(db, r)
        if rem > 0:
            out.append((r, rem))
    return out


def available_credit(db: Session, contact_ids: list[int]) -> float:
    return money(sum(rem for _, rem in open_receipts(db, contact_ids)))


def apply_advance(db: Session, invoice: Invoice, amount: float, admin: str) -> float:
    """Applies up to `amount` of the customer group's open advance to the invoice, oldest first.
    Never more than the invoice still needs. Returns what was applied."""
    pay, alloc = _paid_maps(db, [invoice.id])
    need = max((invoice.total_amount or 0) - pay[invoice.id] - alloc[invoice.id], 0)
    want = min(amount, need)
    applied = 0.0
    for receipt, rem in open_receipts(db, group_ids(db, invoice.contact_id)):
        if want - applied <= 0.004:
            break
        take = money(min(rem, want - applied))
        if take > 0:
            db.add(ReceiptAllocation(receipt_id=receipt.id, invoice_id=invoice.id, amount=take, created_by=admin, created_at=datetime.utcnow()))
            applied = money(applied + take)
    db.flush()
    recompute_invoice(db, invoice)
    return applied
