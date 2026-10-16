"""Shared PDF-building logic, extracted from router_pdf.py so the exact
same bytes used for the downloadable "View PDF" link are also what gets
sent as a WhatsApp document -- the PDF is built ONCE, never regenerated
twice for two different call sites."""
from datetime import timedelta
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _business_header(settings: dict, styles) -> list:
    return [
        Paragraph(f"<b>{settings['business_name']}</b>", styles["Title"]),
        Paragraph(settings.get("address", ""), styles["Normal"]),
        Paragraph(
            f"Phone: {settings.get('phone', '')} &nbsp;&nbsp; Email: {settings.get('email', '')}",
            styles["Normal"],
        ),
        Spacer(1, 14),
    ]


def _totals_table(rows: list) -> Table:
    t = Table(rows, colWidths=[100 * mm, 40 * mm])
    t.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return t


def _items_table(header: list, rows: list) -> Table:
    t = Table([header] + rows, colWidths=[80 * mm, 25 * mm, 30 * mm, 35 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#40916c")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return t


def _delivery_lines(invoice) -> list:
    """Driver / vehicle, only when the delivery for this invoice already has them. Read only."""
    try:
        from sqlalchemy.orm import object_session

        from app.delivery.models import Delivery

        db = object_session(invoice)
        if db is None:
            return []
        d = db.query(Delivery).filter(Delivery.invoice_id == invoice.id).order_by(Delivery.id.desc()).first()
        if not d:
            return []
        out = []
        if d.driver and d.driver.name:
            out.append(f"<b>Driver Name:</b> {d.driver.name}")
        if d.vehicle and d.vehicle.registration_number:
            out.append(f"<b>Vehicle Number:</b> {d.vehicle.registration_number}")
        return out
    except Exception:
        return []


def build_invoice_pdf_bytes(invoice, settings: dict) -> bytes:
    styles = getSampleStyleSheet()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    story = _business_header(settings, styles)

    story.append(Paragraph(f"<b>INVOICE {invoice.invoice_number}</b>", styles["Heading1"]))
    story.append(
        Paragraph(
            f"Date: {invoice.invoice_date.strftime('%d %b %Y')}" + (f" &nbsp;&nbsp; Time: {(invoice.invoice_date + timedelta(hours=5, minutes=30)).strftime('%I:%M %p')}" if invoice.previous_balance is not None else "")
            + (f" &nbsp;&nbsp; Due: {invoice.due_date.strftime('%d %b %Y')}" if invoice.due_date else "")
            + f" &nbsp;&nbsp; Status: {invoice.status}",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 10))

    if invoice.contact:
        story.append(Paragraph("<b>Bill To</b>", styles["Heading3"]))
        story.append(Paragraph(invoice.contact.name, styles["Normal"]))
        if invoice.contact.email:
            story.append(Paragraph(invoice.contact.email, styles["Normal"]))
        if invoice.contact.phone:
            story.append(Paragraph(invoice.contact.phone, styles["Normal"]))
        story.append(Spacer(1, 14))

    item_rows = [
        [item.description, str(item.quantity), f"Rs {item.unit_price:,.2f}", f"Rs {item.line_total:,.2f}"]
        for item in invoice.items
    ]
    story.append(_items_table(["Description", "Qty", "Unit Price", "Line Total"], item_rows))
    story.append(Spacer(1, 14))

    totals_rows = [
        ["Subtotal", f"Rs {invoice.subtotal:,.2f}"],
        ["Tax", f"Rs {invoice.tax_total:,.2f}"],
    ]
    if invoice.discount_total:
        totals_rows.append(["Discount", f"Rs {invoice.discount_total:,.2f}"])
    if invoice.previous_balance is None:
        # Invoice made before balances were frozen on the bill: the old layout, unchanged.
        totals_rows += [
            ["Amount Paid", f"Rs {invoice.amount_paid:,.2f}"],
            ["Balance Due", f"Rs {invoice.balance_due:,.2f}"],
            ["Total", f"Rs {invoice.total_amount:,.2f}"],
        ]
        story.append(_totals_table(totals_rows))
    else:
        # Everything below was fixed when the invoice was generated, so printing it again later
        # gives exactly the same numbers. (Money received afterwards shows in the customer's
        # current outstanding, not on this old bill.)
        total = float(invoice.total_amount or 0)
        received = float(invoice.received_at_issue or 0)
        advance_used = float(invoice.advance_applied_at_issue or 0)
        previous = float(invoice.previous_balance or 0)
        balance_here = max(total - advance_used - received, 0)
        current = previous + total - received
        totals_rows.append(["Total", f"Rs {total:,.2f}"])
        totals_rows.append(["Received", f"Rs {received:,.2f}"])
        if advance_used > 0:
            totals_rows.append(["Advance adjusted (already in Previous Balance)", f"Rs {advance_used:,.2f}"])
        totals_rows.append(["Balance on this invoice", f"Rs {balance_here:,.2f}"])
        totals_rows.append(["Previous Balance" if previous >= 0 else "Previous Advance Credit", f"Rs {abs(previous):,.2f}"])
        totals_rows.append(["Current Balance" if current >= 0 else "Current Advance Credit", f"Rs {abs(current):,.2f}"])
        t = _totals_table(totals_rows)
        t.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.black), ("LINEABOVE", (0, 3 if not invoice.discount_total else 4), (-1, 3 if not invoice.discount_total else 4), 0.5, colors.HexColor("#999999"))]))
        story.append(t)
    delivery_lines = _delivery_lines(invoice)
    if delivery_lines:
        story.append(Spacer(1, 10))
        for line in delivery_lines:
            story.append(Paragraph(line, styles["Normal"]))
    story.append(Spacer(1, 20))
    story.append(Paragraph("Thank you for your business.", styles["Italic"]))

    doc.build(story)
    buf.seek(0)
    return buf.read()


def build_bill_pdf_bytes(bill, settings: dict) -> bytes:
    styles = getSampleStyleSheet()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    story = _business_header(settings, styles)

    bill_number = bill.invoice_number or f"Bill #{bill.id}"
    story.append(Paragraph(f"<b>BILL {bill_number}</b>", styles["Heading1"]))
    story.append(
        Paragraph(
            f"Date: {bill.purchase_date.strftime('%d %b %Y')}"
            + (f" &nbsp;&nbsp; Due: {bill.due_date.strftime('%d %b %Y')}" if bill.due_date else "")
            + f" &nbsp;&nbsp; Status: {bill.status}",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 10))

    if bill.supplier:
        story.append(Paragraph("<b>Supplier</b>", styles["Heading3"]))
        story.append(Paragraph(bill.supplier, styles["Normal"]))
        story.append(Spacer(1, 14))

    item_rows = [
        [item.plant_name, str(item.quantity), f"Rs {item.unit_cost:,.2f}", f"Rs {item.total_cost:,.2f}"]
        for item in bill.items
    ]
    story.append(_items_table(["Item", "Qty", "Unit Cost", "Line Total"], item_rows))
    story.append(Spacer(1, 14))

    story.append(_totals_table([["Total Cost", f"Rs {bill.total_cost:,.2f}"]]))
    story.append(Spacer(1, 20))
    if bill.notes:
        story.append(Paragraph(f"Notes: {bill.notes}", styles["Normal"]))

    doc.build(story)
    buf.seek(0)
    return buf.read()
