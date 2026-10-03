"""Bridges real website Order events into the accounting module.

This must NEVER be able to break, roll back, or slow down the customer-facing
checkout/payment/cancel flow it's called from. Three independent guarantees
make that true:

  1. Temporal separation -- every call site invokes this strictly AFTER its
     own db.commit() has already durably saved the website-side change.
  2. Session separation -- this opens its own SessionLocal() rather than
     reusing the caller's session, so it can never flush/rollback anything
     belonging to the caller.
  3. Exception containment -- the public entry point wraps everything in a
     bare try/except that only logs; it never re-raises, so even a totally
     broken accounting schema surfaces as a log line, never an HTTP error.

Idempotency: every syncable table has a (source, source_id) unique
constraint, and every step here does a lookup-before-insert on that pair, so
calling sync_order_to_accounting() any number of times for the same order
produces exactly the same end state (safe to call from all 6 order-mutation
call sites unconditionally, including ones that don't need to change
anything, like mark_payment_failed).
"""

import logging
from datetime import datetime

from app.accounting.audit import record_change
from app.accounting.models import Contact, Invoice, InvoiceItem, PaymentIn, SalesOrder, SalesOrderItem
from app.database import SessionLocal

logger = logging.getLogger("accounting.sync")


def sync_order_to_accounting(order_id: int) -> None:
    db = SessionLocal()
    try:
        _sync(db, order_id)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "accounting sync failed for order_id=%s (website order itself is unaffected)", order_id
        )
    finally:
        db.close()


def _sync(db, order_id: int) -> None:
    # Local imports: keeps app/models.py's own import graph completely
    # untouched by the accounting module's existence.
    from app.models import Order

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return

    contact = _get_or_create_contact(db, order)
    sales_order = _get_or_create_sales_order(db, order, contact)
    invoice = _get_or_create_invoice(db, order, sales_order, contact)
    _sync_payment(db, order, invoice, contact)
    _sync_cancellation(db, order, sales_order, invoice)


def _get_or_create_contact(db, order):
    from app.models import Customer

    source_id = str(order.customer_id)
    contact = (
        db.query(Contact).filter(Contact.source == "online", Contact.source_id == source_id).first()
    )
    if contact:
        return contact

    customer = db.query(Customer).filter(Customer.id == order.customer_id).first()
    contact = Contact(
        contact_type="customer",
        name=customer.name if customer else f"Customer #{order.customer_id}",
        email=customer.email if customer else "",
        phone=customer.mobile if customer else "",
        source="online",
        source_id=source_id,
        customer_id=order.customer_id,
        created_by="system",
    )
    db.add(contact)
    db.flush()
    record_change(db, "accounting_contacts", contact.id, "create", changed_by="system")
    return contact


def _get_or_create_sales_order(db, order, contact):
    source_id = str(order.id)
    sales_order = (
        db.query(SalesOrder)
        .filter(SalesOrder.source == "online", SalesOrder.source_id == source_id)
        .first()
    )
    if sales_order:
        return sales_order

    sales_order = SalesOrder(
        contact_id=contact.id,
        order_number=f"SO-{order.id}",
        status="Confirmed",
        order_date=order.created_at,
        subtotal=order.subtotal,
        tax_total=0,
        total_amount=order.total_amount,
        notes=f"Auto-synced from website Order #{order.id}",
        source="online",
        source_id=source_id,
        order_ref_id=order.id,
        created_by="system",
    )
    db.add(sales_order)
    db.flush()

    for item in order.items:
        db.add(
            SalesOrderItem(
                sales_order_id=sales_order.id,
                plant_id=item.plant_id,
                description=item.plant_name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
        )
    record_change(db, "accounting_sales_orders", sales_order.id, "create", changed_by="system")
    return sales_order


def _get_or_create_invoice(db, order, sales_order, contact):
    source_id = str(order.id)
    invoice = (
        db.query(Invoice).filter(Invoice.source == "online", Invoice.source_id == source_id).first()
    )
    if invoice:
        return invoice

    invoice = Invoice(
        sales_order_id=sales_order.id,
        contact_id=contact.id,
        invoice_number=f"INV-{order.id}",
        status="Sent",
        invoice_date=order.created_at,
        subtotal=order.subtotal,
        tax_total=0,
        discount_total=0,
        total_amount=order.total_amount,
        amount_paid=0,
        balance_due=order.total_amount,
        source="online",
        source_id=source_id,
    )
    db.add(invoice)
    db.flush()

    for item in order.items:
        db.add(
            InvoiceItem(
                invoice_id=invoice.id,
                plant_id=item.plant_id,
                description=item.plant_name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
        )
    record_change(db, "accounting_invoices", invoice.id, "create", changed_by="system")
    return invoice


def _sync_payment(db, order, invoice, contact):
    if order.payment_status != "Paid":
        return

    source_id = f"order:{order.id}:payment"
    existing = (
        db.query(PaymentIn).filter(PaymentIn.source == "online", PaymentIn.source_id == source_id).first()
    )
    if not existing:
        payment = PaymentIn(
            invoice_id=invoice.id,
            contact_id=contact.id,
            amount=order.total_amount,
            method="Online" if order.payment_method == "Razorpay" else "Cash",
            payment_date=datetime.utcnow(),
            reference=order.razorpay_payment_id or "",
            source="online",
            source_id=source_id,
            recorded_by="system",
        )
        db.add(payment)
        db.flush()
        record_change(db, "accounting_payments_in", payment.id, "create", changed_by="system")

    total_paid = sum(
        p.amount
        for p in db.query(PaymentIn).filter(PaymentIn.invoice_id == invoice.id).all()
    )
    old_status = invoice.status
    invoice.amount_paid = total_paid
    invoice.balance_due = max(invoice.total_amount - total_paid, 0)
    if invoice.status not in ("Cancelled", "Voided"):
        invoice.status = "Paid" if invoice.balance_due <= 0 else "PartiallyPaid"
        if invoice.status != old_status:
            record_change(
                db,
                "accounting_invoices",
                invoice.id,
                "update",
                changed_by="system",
                changes={"status": (old_status, invoice.status)},
            )


def _sync_cancellation(db, order, sales_order, invoice):
    if order.status != "Cancelled":
        return

    if sales_order.status != "Voided":
        old = sales_order.status
        sales_order.status = "Voided"
        record_change(
            db,
            "accounting_sales_orders",
            sales_order.id,
            "void",
            changed_by="system",
            changes={"status": (old, "Voided")},
        )
    if invoice.status != "Voided":
        old = invoice.status
        invoice.status = "Voided"
        record_change(
            db,
            "accounting_invoices",
            invoice.id,
            "void",
            changed_by="system",
            changes={"status": (old, "Voided")},
        )
