"""Party 360 -- a centralized view over EXISTING Contact/SalesOrder/
Invoice/Purchase(Bill)/PurchaseOrder/PaymentIn/PaymentOut/Expense records.
No new business-logic tables here; every endpoint below just aggregates
data that already lives in those tables via their existing contact_id
foreign keys. Source (online/offline) is read per-transaction from each
document's own `source` column -- never inferred from or stored as a
fixed label on the Contact/Party itself, since one party can legitimately
have both online and offline history."""
from datetime import datetime
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.accounting.models import (
    Contact,
    CustomerReceipt,
    CustomerRefund,
    Expense,
    Invoice,
    PaymentIn,
    PaymentOut,
    PurchaseOrder,
    SalesOrder,
    SalesOrderItem,
)
from app.accounting.schemas import (
    PartyDashboardSummaryOut,
    PartyDuplicateCheckOut,
    PartyDuplicateMatch,
    PartyItemRow,
    PartyItemsOut,
    PartyStatementOut,
    PartyStatementRow,
    PartyTimelineOut,
    PartyTimelineRow,
)
from app.database import get_db
from app.deps import get_current_admin
from app.models import Purchase, PurchaseItem

router = APIRouter(prefix="/parties", tags=["accounting-parties"])

# (model, date_column) -- every document type that carries a contact_id
# and a source column, reused across timeline/dashboard/channel computation.
_SOURCE_DOCS = [
    (SalesOrder, SalesOrder.order_date),
    (Invoice, Invoice.invoice_date),
    (PaymentIn, PaymentIn.payment_date),
    (Purchase, Purchase.purchase_date),
    (PurchaseOrder, PurchaseOrder.order_date),
    (PaymentOut, PaymentOut.payment_date),
    (Expense, Expense.expense_date),
]


def _get_contact_or_404(db: Session, contact_id: int) -> Contact:
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Party not found")
    return contact


@router.get("/check-duplicate", response_model=PartyDuplicateCheckOut)
def check_duplicate_party(
    phone: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    gstin: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Mobile-number-first duplicate suggestion (never auto-merge -- the
    caller decides whether to reuse an existing party or create a new
    one). Duplicate parties are legitimately allowed to coexist."""
    matches: dict[int, PartyDuplicateMatch] = {}

    def _add(contacts, field: str):
        for c in contacts:
            if c.id not in matches:
                matches[c.id] = PartyDuplicateMatch(
                    id=c.id, name=c.name, phone=c.phone, email=c.email,
                    source=c.source, contact_type=c.contact_type, matched_on=field,
                )

    phone = (phone or "").strip()
    email = (email or "").strip()
    gstin = (gstin or "").strip()
    name = (name or "").strip()

    if phone:
        _add(db.query(Contact).filter(Contact.phone == phone).all(), "phone")
    if email:
        _add(db.query(Contact).filter(Contact.email == email).all(), "email")
    if gstin:
        _add(db.query(Contact).filter(Contact.gstin == gstin).all(), "gstin")
    if name and not matches:
        _add(db.query(Contact).filter(Contact.name.ilike(f"%{name}%")).limit(10).all(), "name")

    return PartyDuplicateCheckOut(matches=list(matches.values()))


@router.get("/dashboard-summary", response_model=PartyDashboardSummaryOut)
def party_dashboard_summary(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    contacts = db.query(Contact.id, Contact.contact_type).all()
    total_parties = len(contacts)
    customers = sum(1 for _, ct in contacts if ct in ("customer", "both"))
    suppliers = sum(1 for _, ct in contacts if ct in ("supplier", "both"))
    both_types = sum(1 for _, ct in contacts if ct == "both")

    channel_map: dict[int, set] = {}
    for model, _ in _SOURCE_DOCS:
        rows = (
            db.query(model.contact_id, model.source)
            .filter(model.contact_id.isnot(None))
            .distinct()
            .all()
        )
        for cid, src in rows:
            channel_map.setdefault(cid, set()).add(src)

    online_only = sum(1 for s in channel_map.values() if s == {"online"})
    offline_only = sum(1 for s in channel_map.values() if s == {"offline"})
    both_channels = sum(1 for s in channel_map.values() if len(s) > 1)

    return PartyDashboardSummaryOut(
        total_parties=total_parties, online_only=online_only, offline_only=offline_only,
        both_channels=both_channels, customers=customers, suppliers=suppliers, both_types=both_types,
    )


@router.get("/{contact_id}/timeline", response_model=PartyTimelineOut)
def party_timeline(
    contact_id: int,
    source: Optional[str] = Query(None, description="online|offline"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    contact = _get_contact_or_404(db, contact_id)
    rows: list[PartyTimelineRow] = []

    def _matches_source(doc_source: str) -> bool:
        return not source or doc_source == source

    for so in db.query(SalesOrder).filter(SalesOrder.contact_id == contact.id).all():
        if _matches_source(so.source):
            rows.append(PartyTimelineRow(
                date=so.order_date, type="sales_order", label=f"Sales Order {so.order_number}",
                reference=so.order_number, source=so.source, amount=so.total_amount,
                link_type="sales-orders", link_id=so.id,
            ))
    for inv in db.query(Invoice).filter(Invoice.contact_id == contact.id).all():
        if _matches_source(inv.source):
            rows.append(PartyTimelineRow(
                date=inv.invoice_date, type="invoice", label=f"Invoice {inv.invoice_number}",
                reference=inv.invoice_number, source=inv.source, amount=inv.total_amount,
                link_type="invoices", link_id=inv.id,
            ))
    for p in db.query(PaymentIn).filter(PaymentIn.contact_id == contact.id).all():
        if _matches_source(p.source):
            rows.append(PartyTimelineRow(
                date=p.payment_date, type="payment_in", label="Payment Received",
                reference=p.reference or f"PAY-IN-{p.id}", source=p.source, amount=p.amount,
                link_type="invoices", link_id=p.invoice_id,
            ))
    for po in db.query(PurchaseOrder).filter(PurchaseOrder.contact_id == contact.id).all():
        if _matches_source(po.source):
            rows.append(PartyTimelineRow(
                date=po.order_date, type="purchase_order", label=f"Purchase Order {po.order_number}",
                reference=po.order_number, source=po.source, amount=po.total_amount,
                link_type="purchase-orders", link_id=po.id,
            ))
    for b in db.query(Purchase).filter(Purchase.contact_id == contact.id).all():
        if _matches_source(b.source):
            rows.append(PartyTimelineRow(
                date=b.purchase_date, type="bill", label=f"Bill {b.invoice_number or ('#' + str(b.id))}",
                reference=b.invoice_number or f"BILL-{b.id}", source=b.source, amount=b.total_cost,
                link_type="bills", link_id=b.id,
            ))
    for p in db.query(PaymentOut).filter(PaymentOut.contact_id == contact.id).all():
        if _matches_source(p.source):
            rows.append(PartyTimelineRow(
                date=p.payment_date, type="payment_out", label="Payment Out",
                reference=p.reference or f"PAY-OUT-{p.id}", source=p.source, amount=p.amount,
                link_type="bills", link_id=p.purchase_id or 0,
            ))
    for e in db.query(Expense).filter(Expense.contact_id == contact.id).all():
        if _matches_source(e.source):
            rows.append(PartyTimelineRow(
                date=e.expense_date, type="expense", label=f"Expense -- {e.category}",
                reference=f"EXP-{e.id}", source=e.source, amount=e.total_amount,
                link_type="expenses", link_id=e.id,
            ))

    rows.sort(key=lambda r: r.date, reverse=True)
    return PartyTimelineOut(rows=rows)


@router.get("/{contact_id}/statement", response_model=PartyStatementOut)
def party_statement(
    contact_id: int,
    source: Optional[str] = Query(None, description="online|offline"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """A Receivable statement for customer/both parties, a Payable
    statement for supplier-only parties -- a single combined ledger isn't
    meaningful when a party is simultaneously owed money and owing money
    in two different senses, so this picks the dominant, more useful one
    for the party's type."""
    contact = _get_contact_or_404(db, contact_id)
    is_supplier_only = contact.contact_type == "supplier"

    raw_rows = []
    if not is_supplier_only:
        inv_q = db.query(Invoice).filter(Invoice.contact_id == contact.id, Invoice.status.notin_(("Voided", "Cancelled")))
        if source:
            inv_q = inv_q.filter(Invoice.source == source)
        if date_from:
            inv_q = inv_q.filter(Invoice.invoice_date >= date_from)
        if date_to:
            inv_q = inv_q.filter(Invoice.invoice_date <= date_to)
        for inv in inv_q.all():
            raw_rows.append((inv.invoice_date, f"Invoice {inv.invoice_number}", inv.invoice_number, inv.source, inv.total_amount, 0))

        # Payments on live invoices, plus payments on a voided invoice that nobody has decided
        # about yet (held as credit). Decided ones appear below as an advance (and a refund).
        pay_q = (
            db.query(PaymentIn, Invoice)
            .join(Invoice, Invoice.id == PaymentIn.invoice_id)
            .filter(PaymentIn.contact_id == contact.id)
            .filter(Invoice.status.notin_(("Voided", "Cancelled")) | Invoice.void_disposition.is_(None))
        )
        if source:
            pay_q = pay_q.filter(PaymentIn.source == source)
        if date_from:
            pay_q = pay_q.filter(PaymentIn.payment_date >= date_from)
        if date_to:
            pay_q = pay_q.filter(PaymentIn.payment_date <= date_to)
        for p, inv in pay_q.all():
            label = "Payment Received" if inv.status not in ("Voided", "Cancelled") else f"Payment on voided {inv.invoice_number} (held as credit)"
            raw_rows.append((p.payment_date, label, p.reference or f"PAY-IN-{p.id}", p.source, 0, p.amount))
        if not source or source == "offline":
            rc_q = db.query(CustomerReceipt).filter(CustomerReceipt.contact_id == contact.id, CustomerReceipt.status == "Active")
            if date_from:
                rc_q = rc_q.filter(CustomerReceipt.payment_date >= date_from)
            if date_to:
                rc_q = rc_q.filter(CustomerReceipt.payment_date <= date_to)
            names = {"advance": "Advance Received", "overpayment": "Extra Payment (kept as advance)", "void_transfer": "Voided invoice payment (kept as advance)"}
            for r in rc_q.all():
                raw_rows.append((r.payment_date, names.get(r.kind, "Advance Received"), r.reference or f"ADV-{r.id}", "offline", 0, r.amount))
            rf_q = db.query(CustomerRefund).join(CustomerReceipt, CustomerReceipt.id == CustomerRefund.receipt_id).filter(CustomerRefund.contact_id == contact.id, CustomerReceipt.status == "Active")
            if date_from:
                rf_q = rf_q.filter(CustomerRefund.refund_date >= date_from)
            if date_to:
                rf_q = rf_q.filter(CustomerRefund.refund_date <= date_to)
            for f in rf_q.all():
                raw_rows.append((f.refund_date, "Refund to customer", f"REFUND-{f.id}", "offline", f.amount, 0))
    else:
        bill_q = db.query(Purchase).filter(Purchase.contact_id == contact.id)
        if source:
            bill_q = bill_q.filter(Purchase.source == source)
        if date_from:
            bill_q = bill_q.filter(Purchase.purchase_date >= date_from)
        if date_to:
            bill_q = bill_q.filter(Purchase.purchase_date <= date_to)
        for b in bill_q.all():
            raw_rows.append((b.purchase_date, f"Bill {b.invoice_number or ('#' + str(b.id))}", b.invoice_number or f"BILL-{b.id}", b.source, b.total_cost, 0))

        pay_q = db.query(PaymentOut).filter(PaymentOut.contact_id == contact.id)
        if source:
            pay_q = pay_q.filter(PaymentOut.source == source)
        if date_from:
            pay_q = pay_q.filter(PaymentOut.payment_date >= date_from)
        if date_to:
            pay_q = pay_q.filter(PaymentOut.payment_date <= date_to)
        for p in pay_q.all():
            raw_rows.append((p.payment_date, "Payment Out", p.reference or f"PAY-OUT-{p.id}", p.source, 0, p.amount))

    raw_rows.sort(key=lambda r: r[0])
    rows = []
    running = 0.0
    for date, transaction, reference, src, debit, credit in raw_rows:
        running = round(running + debit - credit, 2)
        rows.append(PartyStatementRow(
            date=date, transaction=transaction, reference=reference, source=src,
            debit=round(debit, 2), credit=round(credit, 2), balance=running,
        ))

    return PartyStatementOut(opening_balance=0, rows=rows, closing_balance=running)


@router.get("/{contact_id}/items", response_model=PartyItemsOut)
def party_items(contact_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    contact = _get_contact_or_404(db, contact_id)

    sold_rows = (
        db.query(
            SalesOrderItem.plant_id, SalesOrderItem.description,
            func.sum(SalesOrderItem.quantity), func.sum(SalesOrderItem.line_total),
            func.max(SalesOrder.order_date),
        )
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.sales_order_id)
        .filter(SalesOrder.contact_id == contact.id)
        .group_by(SalesOrderItem.plant_id, SalesOrderItem.description)
        .order_by(func.sum(SalesOrderItem.line_total).desc())
        .all()
    )
    sold = [
        PartyItemRow(plant_id=pid, name=desc or "Unknown item", quantity=int(qty or 0), total_value=round(val or 0, 2), last_transaction=last)
        for pid, desc, qty, val, last in sold_rows
    ]

    purchased_rows = (
        db.query(
            PurchaseItem.plant_id, PurchaseItem.plant_name,
            func.sum(PurchaseItem.quantity), func.sum(PurchaseItem.total_cost),
            func.max(Purchase.purchase_date),
        )
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .filter(Purchase.contact_id == contact.id)
        .group_by(PurchaseItem.plant_id, PurchaseItem.plant_name)
        .order_by(func.sum(PurchaseItem.total_cost).desc())
        .all()
    )
    purchased = [
        PartyItemRow(plant_id=pid, name=name or "Unknown item", quantity=int(qty or 0), total_value=round(val or 0, 2), last_transaction=last)
        for pid, name, qty, val, last in purchased_rows
    ]

    return PartyItemsOut(sold=sold, purchased=purchased)


@router.get("/{contact_id}/export-statement.xlsx")
def export_party_statement(
    contact_id: int,
    source: Optional[str] = Query(None),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    contact = _get_contact_or_404(db, contact_id)
    statement = party_statement(contact_id, source, None, None, admin, db)

    wb = Workbook()
    ws = wb.active
    ws.append(["Date", "Transaction", "Reference", "Source", "Debit", "Credit", "Balance"])
    for r in statement.rows:
        ws.append([r.date, r.transaction, r.reference, r.source, r.debit, r.credit, r.balance])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"{contact.name.replace(' ', '_')}_statement.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
