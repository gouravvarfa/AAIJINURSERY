"""Accounting -> centralized WhatsApp, same rule as Orders/Delivery: never
call AiSensy directly, always go through app.communications.service, and
never pick a template name here -- that's resolved centrally by
WhatsAppEventTemplateMap. Covers BOTH online and offline contacts -- an
offline walk-in sale converted to an Invoice here gets exactly the same
WhatsApp treatment a website order does, which the auto-sync path
(app/accounting/sync.py) never triggers on its own.

Note: "Bill" in this codebase (app.models.Purchase) is a SUPPLIER/purchase
bill -- what the business owes a vendor -- not a customer-facing document,
so it is deliberately never sent to a customer over WhatsApp here.
"""
from app.accounting.public_pdf import invoice_pdf_url
from app.communications.service import queue_document_event, queue_event as queue_whatsapp_event


def _contact_mobile_name(contact):
    if not contact:
        return "", "Customer"
    return contact.phone, contact.name


def queue_sales_order_created(sales_order) -> None:
    mobile, name = _contact_mobile_name(sales_order.contact)
    if not mobile:
        return
    queue_whatsapp_event(
        event_type="SALES_ORDER_CREATED", mobile=mobile, customer_name=name,
        template_params=[name, sales_order.order_number, f"{sales_order.total_amount:.2f}"],
        source_module="accounting", source_id=f"SO-{sales_order.id}",
        customer_id=sales_order.contact.customer_id if sales_order.contact else None,
    )


def queue_invoice_created(invoice) -> None:
    mobile, name = _contact_mobile_name(invoice.contact)
    if not mobile:
        return
    due = invoice.due_date.strftime("%d %b %Y") if invoice.due_date else "-"
    queue_whatsapp_event(
        event_type="INVOICE_CREATED", mobile=mobile, customer_name=name,
        template_params=[name, invoice.invoice_number, f"Rs.{invoice.total_amount:.2f}", due, invoice_pdf_url(invoice.id)],
        source_module="accounting", source_id=f"INV-{invoice.id}",
        customer_id=invoice.contact.customer_id if invoice.contact else None,
    )
    # The invoice_link template already carries the PDF link, which works for any
    # customer. A direct PDF attachment only works inside WhatsApp's 24h window,
    # so it is sent only while the older text-only template is still in use.
    if not _link_template_active():
        _queue_invoice_pdf(invoice, mobile, name)


def _link_template_active() -> bool:
    from app.communications.service import resolve_event_template
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return resolve_event_template(db, "INVOICE_CREATED")[0] == "invoice_link"
    finally:
        db.close()


def _queue_invoice_pdf(invoice, mobile: str, name: str) -> None:
    """Sends the SAME PDF the "View PDF" admin button generates -- built
    once via app.accounting.pdf_builder, never regenerated separately for
    WhatsApp. A PDF-build failure here is caught and logged, never allowed
    to break invoice creation itself (fault isolation, same guarantee as
    every other WhatsApp call)."""
    try:
        from app.accounting.pdf_builder import build_invoice_pdf_bytes
        from app.database import SessionLocal
        from app.settings_helper import get_settings

        db = SessionLocal()
        try:
            settings = get_settings(db)
        finally:
            db.close()
        pdf_bytes = build_invoice_pdf_bytes(invoice, settings)
    except Exception:
        import logging
        logging.getLogger("accounting.notifications").exception("Failed to build invoice PDF for WhatsApp, invoice_id=%s", invoice.id)
        return

    queue_document_event(
        event_type="INVOICE_CREATED", mobile=mobile, customer_name=name,
        source_module="accounting", source_id=f"INV-{invoice.id}",
        pdf_bytes=pdf_bytes, filename=f"{invoice.invoice_number}.pdf",
        caption=f"Invoice {invoice.invoice_number}",
        customer_id=invoice.contact.customer_id if invoice.contact else None,
    )


def queue_payment_received(payment, invoice) -> None:
    mobile, name = _contact_mobile_name(invoice.contact)
    if not mobile:
        return
    queue_whatsapp_event(
        event_type="PAYMENT_RECEIVED", mobile=mobile, customer_name=name,
        template_params=[name, f"Rs.{payment.amount:.2f}", invoice.invoice_number],
        source_module="accounting", source_id=f"PAY-{payment.id}",
        customer_id=invoice.contact.customer_id if invoice.contact else None,
    )
