"""The tax invoice PDF (A4): clean, enterprise-style layout.

Only real data is printed. Every optional block (driver, vehicle, GSTIN, bank, terms, signature,
payment note, website ...) is left out when it has no value, and nothing is invented.

Balances come from what was FROZEN on the invoice when it was generated (previous_balance,
received_at_issue, advance_applied_at_issue). Invoices made before that existed have no snapshot, so
they never show a Previous / Current Balance; they print the plain Amount Paid / Balance Due as before.
"""
import base64
import re
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import CondPageBreak, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.accounting.invoice_words import amount_in_words, indian_number

ASSETS = Path(__file__).parent / "pdf_assets"
NAVY = colors.HexColor("#1b2a41")
RED = colors.HexColor("#c0182f")
GREEN = colors.HexColor("#1f7a45")
GREY = colors.HexColor("#6b7885")
LINE = colors.HexColor("#e1e6ea")
SURFACE = colors.HexColor("#f5f7f9")
HEAD_BG = colors.HexColor("#edf1f5")

_fonts_ready: Optional[bool] = None
PAGE_W, PAGE_H = A4
MARGIN = 14 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def _setup_fonts() -> bool:
    """Noto Sans (Latin, rupee sign) and Noto Sans Devanagari (Hindi). Falls back to Helvetica if the files are missing."""
    global _fonts_ready
    if _fonts_ready is not None:
        return _fonts_ready
    try:
        d = ASSETS / "fonts"
        pdfmetrics.registerFont(TTFont("AJ", str(d / "NotoSans-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("AJ-B", str(d / "NotoSans-Bold.ttf")))
        pdfmetrics.registerFont(TTFont("AJH", str(d / "NotoSansDevanagari-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("AJH-B", str(d / "NotoSansDevanagari-Bold.ttf")))
        registerFontFamily("AJ", normal="AJ", bold="AJ-B", italic="AJ", boldItalic="AJ-B")
        registerFontFamily("AJH", normal="AJH", bold="AJH-B", italic="AJH", boldItalic="AJH-B")
        _fonts_ready = True
    except Exception:
        _fonts_ready = False
    return _fonts_ready


def _f(bold: bool = False, hindi: bool = False) -> str:
    if not _setup_fonts():
        return "Helvetica-Bold" if bold else "Helvetica"
    return ("AJH" if hindi else "AJ") + ("-B" if bold else "")


def _has_hindi(text: str) -> bool:
    return bool(re.search(r"[ऀ-ॿ]", text or ""))


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _style(size=8.6, bold=False, color=NAVY, align=TA_LEFT, leading=None, hindi=False) -> ParagraphStyle:
    return ParagraphStyle("x", fontName=_f(bold, hindi), fontSize=size, leading=leading or size * 1.38, textColor=color, alignment=align, shaping=1 if hindi else 0)


def P(text: str, size=8.6, bold=False, color=NAVY, align=TA_LEFT, leading=None) -> Paragraph:
    """A paragraph; Hindi text automatically gets the Devanagari font with proper letter shaping."""
    hindi = _has_hindi(text)
    return Paragraph(_esc(text).replace("\n", "<br/>"), _style(size, bold, color, align, leading, hindi))


def rupee(value: float) -> str:
    sign = "₹ " if _setup_fonts() else "Rs "
    return sign + indian_number(value)


def pretty_address(raw: str) -> str:
    """Presentation only: 'Raipuriya distict jhabua ' -> 'Raipuriya, District Jhabua'. Nothing is added."""
    text = re.sub(r"\s+", " ", (raw or "").replace("\n", ", ")).strip(" ,")
    if not text:
        return ""
    text = re.sub(r"\bdist(?:r)?ict\b", "District", text, flags=re.I)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"(?<!,)\s+District\b", ", District", text)
    words = [w if (w.isupper() and len(w) > 1) or any(c.isdigit() for c in w) else w[:1].upper() + w[1:].lower() if w.islower() or w.istitle() or w.isupper() else w for w in text.split(" ")]
    return " ".join(words)


def _invoice_settings(invoice) -> dict:
    try:
        from sqlalchemy.orm import object_session

        from app.accounting.models import InvoiceSetting

        db = object_session(invoice)
        if db is None:
            return {}
        return {r.key: (r.value or "").strip() for r in db.query(InvoiceSetting).all() if (r.value or "").strip()}
    except Exception:
        return {}


def _delivery(invoice) -> tuple[str, str]:
    """Driver / vehicle, only when the delivery for this invoice already has them. Read only."""
    try:
        from sqlalchemy.orm import object_session

        from app.delivery.models import Delivery

        db = object_session(invoice)
        d = db.query(Delivery).filter(Delivery.invoice_id == invoice.id).order_by(Delivery.id.desc()).first() if db is not None else None
        if not d:
            return "", ""
        return (d.driver.name if d.driver and d.driver.name else ""), (d.vehicle.registration_number if d.vehicle and d.vehicle.registration_number else "")
    except Exception:
        return "", ""


def _payment_mode(invoice) -> str:
    """The method(s) actually recorded. For a bill with a frozen snapshot only what was received at billing counts, so a reprint never changes."""
    try:
        from sqlalchemy.orm import object_session

        from app.accounting.models import PaymentIn

        db = object_session(invoice)
        if db is None:
            return ""
        q = db.query(PaymentIn.method).filter(PaymentIn.invoice_id == invoice.id)
        if invoice.previous_balance is not None:
            q = q.filter(PaymentIn.notes == "Received when billing")
        seen = []
        for (m,) in q.order_by(PaymentIn.id):
            if m and m.upper() not in seen:
                seen.append(m.upper())
        return ", ".join(seen)
    except Exception:
        return ""


def _units_and_names(invoice) -> list[dict]:
    """Per line: item name, description, unit. 'Tray' for tray sales, 'Pcs' otherwise (the sales order knows the tray size)."""
    so_items = []
    try:
        so_items = sorted(invoice.sales_order.items, key=lambda x: x.id) if invoice.sales_order else []
    except Exception:
        pass
    lines = []
    for idx, it in enumerate(sorted(invoice.items, key=lambda x: x.id)):
        src = so_items[idx] if idx < len(so_items) and (so_items[idx].description or "") == (it.description or "") else None
        plant_name = it.plant.name if getattr(it, "plant", None) else ""
        desc = (it.description or "").strip()
        if plant_name and desc and plant_name.strip().lower() != desc.lower():
            name, detail = plant_name, desc
        else:
            name, detail = (desc or plant_name or "Item"), ""
        if src is not None and src.tray_size:
            detail = detail or f"Tray of {src.tray_size} plants"
        lines.append({"name": name, "detail": detail, "qty": it.quantity or 0, "unit": "Tray" if (src is not None and src.tray_size) else "Pcs", "price": it.unit_price or 0, "amount": it.line_total or 0})
    return lines


def _signature_image(value: str, max_w=36 * mm, max_h=13 * mm):
    m = re.match(r"data:image/(png|jpe?g);base64,(.+)", value or "", re.S)
    if not m:
        return None
    try:
        from PIL import Image as PILImage

        raw = base64.b64decode(m.group(2))
        im = PILImage.open(BytesIO(raw))
        w, h = im.size
        scale = min(max_w / w, max_h / h)
        img = Image(BytesIO(raw), width=w * scale, height=h * scale, mask="auto")
        img.hAlign = "RIGHT"
        return img
    except Exception:
        return None


def _right(flowable, width=82 * mm):
    t = Table([[flowable]], colWidths=[width])
    t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _logo(width=22 * mm):
    p = ASSETS / "logo.png"
    if not p.exists():
        return None
    try:
        from PIL import Image as PILImage

        w, h = PILImage.open(p).size
        return Image(str(p), width=width, height=width * h / w, mask="auto")
    except Exception:
        return None


def _kv(rows: list[tuple[str, str]], label_w=24 * mm, width=54 * mm):
    if not rows:
        return None
    data = [[P(k, 7.6, color=GREY), P(v, 8.4, bold=False)] for k, v in rows]
    t = Table(data, colWidths=[label_w, width - label_w])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 1.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2)]))
    return t


def _card(title: str, content: list, width: float) -> Table:
    inner = [P(title.upper(), 7.2, bold=True, color=GREY)] + [Spacer(1, 3)] + [c for c in content if c is not None]
    t = Table([[inner]], colWidths=[width], cornerRadii=[5, 5, 5, 5])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SURFACE), ("BOX", (0, 0), (-1, -1), 0.5, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


class _NumberedCanvas(rl_canvas.Canvas):
    """Draws 'Page x of y' and the footer once the page count is known."""

    footer_text = ""
    ack_parts: list = []  # the cut-line + acknowledgement slip, drawn at the bottom of the LAST page only

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for number, state in enumerate(self._pages, 1):
            self.__dict__.update(state)
            self._footer(total)
            if number == total:
                y = 18 * mm
                for part in reversed(self.ack_parts):
                    _, h = part.wrapOn(self, CONTENT_W, 10000)
                    part.drawOn(self, MARGIN, y)
                    y += h + 2 * mm
            super().showPage()
        super().save()

    def _footer(self, total):
        self.setStrokeColor(LINE)
        self.setLineWidth(0.6)
        self.line(MARGIN, 14 * mm, PAGE_W - MARGIN, 14 * mm)
        self.setFont(_f(), 7.4)
        self.setFillColor(GREY)
        if self.footer_text:
            self.drawString(MARGIN, 9.5 * mm, self.footer_text)
        self.drawRightString(PAGE_W - MARGIN, 9.5 * mm, f"Page {self._pageNumber} of {total}")


def build_invoice_pdf(invoice, settings: dict) -> bytes:
    _setup_fonts()
    inv_set = _invoice_settings(invoice)
    business = (settings.get("business_name") or "").strip() or "Invoice"
    address = pretty_address(settings.get("address", ""))
    phone, email = (settings.get("phone") or "").strip(), (settings.get("email") or "").strip()
    website = inv_set.get("invoice_website", "")
    tagline = (settings.get("tagline") or "").strip()
    proprietor = inv_set.get("invoice_proprietor", "")
    contact = invoice.contact
    gstin = (inv_set.get("invoice_gstin") or "").strip()
    local = invoice.invoice_date + timedelta(hours=5, minutes=30)
    stamped = invoice.previous_balance is not None

    story = []
    # ------------------------------------------------------------ header
    logo = _logo()
    name_block = [P(business, 17, bold=True, color=NAVY, leading=20)]
    if tagline:
        name_block.append(P(tagline, 8, color=GREY))
    if proprietor:
        name_block.append(P(f"Proprietor: {proprietor}", 8, color=NAVY))
    contact_lines = [P(x, 8, color=NAVY) for x in (address, f"Phone: {phone}" if phone else "", email, website) if x]
    head = Table([[logo or "", name_block, contact_lines]], colWidths=[26 * mm, CONTENT_W - 26 * mm - 62 * mm, 62 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story += [head, Spacer(1, 5)]
    rule = Table([["", ""]], colWidths=[CONTENT_W * 0.24, CONTENT_W * 0.76], rowHeights=[1.2 * mm])
    rule.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), RED), ("BACKGROUND", (1, 0), (1, 0), NAVY), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story += [rule, Spacer(1, 9)]

    # ------------------------------------------------------------ title + number
    title = Table([[[P("TAX INVOICE", 19, bold=True, leading=22), P("Sales of plants, seeds and nursery materials", 8, color=GREY)],
                    Table([[P("Invoice No.", 8, color=GREY), P(invoice.invoice_number or f"INV-{invoice.id}", 12, bold=True, color=NAVY)]], colWidths=[22 * mm, 38 * mm], cornerRadii=[5, 5, 5, 5],
                          style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), SURFACE), ("BOX", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))]],
                  colWidths=[CONTENT_W - 64 * mm, 64 * mm])
    title.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "RIGHT"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [title, Spacer(1, 9)]

    # ------------------------------------------------------------ cards
    driver, vehicle = _delivery(invoice)
    mode = _payment_mode(invoice)
    bill = []
    if contact:
        bill.append(P(contact.name or "-", 10, bold=True))
        if (contact.address or "").strip():
            bill.append(P(re.sub(r"\s+", " ", contact.address).strip(), 8.2, leading=11))
        if (contact.phone or "").strip():
            bill.append(P(f"Contact No.: {contact.phone.strip()}", 8.2))
        if contact.email:
            bill.append(P(contact.email, 8.2))
        if (contact.gstin or "").strip():
            bill.append(P(f"GSTIN: {contact.gstin.strip()}", 8.2))
    details = [("Invoice Date", local.strftime("%d %b %Y")), ("Invoice Time", local.strftime("%I:%M %p"))]
    if invoice.due_date:
        details.append(("Due Date", invoice.due_date.strftime("%d %b %Y")))
    if mode:
        details.append(("Payment Mode", mode))
    transport = [(k, v) for k, v in (("Driver Name", driver), ("Vehicle No.", vehicle)) if v]
    cards = [("Bill To", bill)]
    if transport:
        cards.append(("Transportation Details", [_kv(transport, 22 * mm, 50 * mm)]))
    cards.append(("Invoice Details", [_kv(details, 24 * mm, 50 * mm)]))
    gap = 4 * mm
    cw = (CONTENT_W - gap * (len(cards) - 1)) / len(cards)
    row, widths = [], []
    for i, (t, c) in enumerate(cards):
        row.append(_card(t, c, cw))
        widths.append(cw)
        if i < len(cards) - 1:
            row.append("")
            widths.append(gap)
    ct = Table([row], colWidths=widths)
    ct.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story += [ct, Spacer(1, 10)]

    # ------------------------------------------------------------ items
    lines = _units_and_names(invoice)
    show_desc = any(l["detail"] for l in lines)
    if show_desc:
        widths = [8 * mm, 46 * mm, 44 * mm, 16 * mm, 16 * mm, 24 * mm, 28 * mm]
        header = ["#", "Item Name", "Description", "Qty", "Unit", "Price", "Amount"]
    else:
        widths = [8 * mm, 90 * mm, 16 * mm, 16 * mm, 24 * mm, 28 * mm]
        header = ["#", "Item Name", "Qty", "Unit", "Price", "Amount"]
    widths[1] += CONTENT_W - sum(widths)

    def hdr(text, idx):
        return P(text, 7.6, bold=True, color=NAVY, align=TA_RIGHT if idx >= len(header) - 4 else TA_LEFT)

    data = [[hdr(h, i) for i, h in enumerate(header)]]
    for n, l in enumerate(lines, 1):
        cells = [P(str(n), 8.4, color=GREY), P(l["name"], 8.8, bold=True)]
        if show_desc:
            cells.append(P(l["detail"] or "", 8.2, color=GREY))
        cells += [P(str(l["qty"]), 8.6, align=TA_RIGHT), P(l["unit"], 8.4, color=GREY, align=TA_RIGHT), P(indian_number(l["price"]), 8.6, align=TA_RIGHT), P(indian_number(l["amount"]), 8.8, bold=True, align=TA_RIGHT)]
        data.append(cells)
    total_qty = sum(l["qty"] for l in lines)
    last = [P("", 8), P("Total", 9, bold=True)] + ([P("", 8)] if show_desc else []) + [P(str(total_qty), 8.8, bold=True, align=TA_RIGHT), P("", 8), P("", 8), P(rupee(sum(l["amount"] for l in lines)), 9.4, bold=True, align=TA_RIGHT)]
    data.append(last)
    it = Table(data, colWidths=widths, repeatRows=1)
    it.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG), ("LINEBELOW", (0, 0), (-1, 0), 0.8, NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, LINE), ("LINEABOVE", (0, -1), (-1, -1), 0.8, NAVY), ("BACKGROUND", (0, -1), (-1, -1), SURFACE),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [it, Spacer(1, 10)]

    # ------------------------------------------------------------ totals (right)
    total = float(invoice.total_amount or 0)
    rows = [("Sub Total", rupee(invoice.subtotal or 0), "n")]
    if invoice.discount_total:
        rows.append(("Discount", "-" + rupee(invoice.discount_total), "n"))
    if invoice.tax_total:
        rows.append(("Tax", rupee(invoice.tax_total), "n"))
    rows.append(("Total Invoice Amount", rupee(total), "total"))
    if stamped:
        received = float(invoice.received_at_issue or 0)
        adv = float(invoice.advance_applied_at_issue or 0)
        previous = float(invoice.previous_balance or 0)
        balance_here = max(total - adv - received, 0)
        current = previous + total - received
        rows.append(("Previous Balance" if previous >= 0 else "Previous Advance Credit", rupee(abs(previous)), "red" if previous > 0 else "n"))
        rows.append(("Received", rupee(received), "n"))
        if adv > 0:
            rows.append(("Advance adjusted", rupee(adv), "n"))
        rows.append(("Balance Due (Invoice)", rupee(balance_here), "red" if balance_here > 0 else "n"))
        rows.append(("Current Balance" if current >= 0 else "Current Advance Credit", rupee(abs(current)), "strong-red" if current > 0 else "strong-green"))
    else:
        rows.append(("Amount Paid", rupee(invoice.amount_paid or 0), "n"))
        rows.append(("Balance Due", rupee(invoice.balance_due or 0), "red" if (invoice.balance_due or 0) > 0 else "n"))
    tdata, styles = [], [("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("BOX", (0, 0), (-1, -1), 0.5, LINE)]
    for i, (label, val, kind) in enumerate(rows):
        if kind == "total":
            tdata.append([P(label, 9.2, bold=True, color=colors.white), P(val, 10.4, bold=True, color=colors.white, align=TA_RIGHT)])
            styles += [("BACKGROUND", (0, i), (-1, i), NAVY)]
        elif kind in ("strong-red", "strong-green"):
            c = RED if kind == "strong-red" else GREEN
            tdata.append([P(label, 9, bold=True, color=c), P(val, 10.6, bold=True, color=c, align=TA_RIGHT)])
            styles += [("LINEABOVE", (0, i), (-1, i), 1.2, c)]
        else:
            c = RED if kind == "red" else NAVY
            tdata.append([P(label, 8.6, color=GREY if kind == "n" else c), P(val, 8.8, bold=(kind == "red"), color=c, align=TA_RIGHT)])
    totals = Table(tdata, colWidths=[50 * mm, 36 * mm])
    totals.setStyle(TableStyle(styles))
    right = [totals]

    bank_rows = [(k, inv_set[key]) for k, key in (("Bank Name", "invoice_bank_name"), ("A/C No.", "invoice_bank_account"), ("IFSC Code", "invoice_bank_ifsc"), ("Account Holder", "invoice_bank_holder")) if inv_set.get(key)]
    sig = _signature_image(inv_set.get("invoice_signature", ""))
    sign_block = [P(f"For {business}", 7.8, bold=True, align=TA_RIGHT)] + ([Spacer(1, 3), _right(sig)] if sig else [Spacer(1, 18)]) + [P("Authorized Signatory", 7.8, color=GREY, align=TA_RIGHT)]
    if bank_rows:
        bt = Table([[[P("BANK DETAILS", 7.2, bold=True, color=GREY), Spacer(1, 3), _kv(bank_rows, 25 * mm, 86 * mm - 18 * mm)]]], colWidths=[86 * mm], cornerRadii=[5, 5, 5, 5])
        bt.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, LINE), ("BACKGROUND", (0, 0), (-1, -1), SURFACE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
        right += [Spacer(1, 7), bt]
    sg = Table([[sign_block]], colWidths=[86 * mm])
    sg.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 0)]))
    right += [Spacer(1, 10), sg]

    # ------------------------------------------------------------ left: words, note, terms
    left = [_card("Amount In Words", [P(amount_in_words(total), 8.6)], 88 * mm)]
    if inv_set.get("invoice_payment_note"):
        left += [Spacer(1, 6), _card("Payment Note", [P(inv_set["invoice_payment_note"], 8.2)], 88 * mm)]
    terms = [t.strip() for t in (inv_set.get("invoice_terms") or "").splitlines() if t.strip()]
    extra = [t.strip() for t in (inv_set.get("invoice_extra_phones") or "").splitlines() if t.strip()]
    if terms or extra:
        content = [P(f"{i}. {t}", 8.2, leading=11.5) for i, t in enumerate(terms, 1)] + ([Spacer(1, 4)] if terms and extra else []) + [P(x, 8.2, leading=11.5) for x in extra]
        left += [Spacer(1, 6), _card("Terms & Conditions" if terms else "Contact", content, 88 * mm)]
    summary = Table([[left, "", right]], colWidths=[88 * mm, CONTENT_W - 88 * mm - 86 * mm, 86 * mm])
    summary.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))

    # ------------------------------------------------------------ acknowledgement slip
    cut = Table([[P("Acknowledgement Slip (Customer Copy)", 7.8, bold=True, color=GREY), P("Detach here and return with payment", 7.4, color=GREY, align=TA_RIGHT)]],
                colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5])
    cut.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.7, GREY, 0, (3, 2)), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    ack_logo = _logo(14 * mm)
    ack_name = [P(business, 9, bold=True)]
    cust_lines = [P(f"Customer: {contact.name if contact else '-'}", 8.2, bold=True)]
    if contact and (contact.address or "").strip():
        cust_lines.append(P(re.sub(r"\s+", " ", contact.address).strip(), 7.8, color=GREY, leading=10.5))
    inv_lines = _kv([("Invoice No.", invoice.invoice_number or ""), ("Invoice Date", local.strftime("%d %b %Y")), ("Invoice Amount", rupee(total))], 22 * mm, 46 * mm)
    seal = Table([[P("Receiver's Seal & Signature", 7.2, color=GREY)]], colWidths=[40 * mm], rowHeights=[14 * mm])
    seal.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 4)]))
    ack = Table([[[ack_logo or "", ack_name], cust_lines, inv_lines, seal]], colWidths=[34 * mm, 54 * mm, 52 * mm, 42 * mm], cornerRadii=[5, 5, 5, 5])
    ack.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))

    ack_h = sum(part.wrap(CONTENT_W, 10000)[1] for part in (cut, ack)) + 6 * mm
    story += [KeepTogether([summary]), CondPageBreak(ack_h + 12 * mm)]

    # ------------------------------------------------------------ page chrome
    foot_bits = [x for x in (f"Phone: {phone}" if phone else "", email, website) if x]
    footer = "   |   ".join(foot_bits)
    canvas_cls = type("InvoiceCanvas", (_NumberedCanvas,), {"footer_text": footer, "ack_parts": [cut, ack]})
    inv_no = invoice.invoice_number or f"INV-{invoice.id}"

    def later_pages(c, doc):
        c.saveState()
        c.setFont(_f(True), 8.5)
        c.setFillColor(NAVY)
        c.drawString(MARGIN, PAGE_H - 10 * mm, business)
        c.setFont(_f(), 8.5)
        c.setFillColor(GREY)
        c.drawRightString(PAGE_W - MARGIN, PAGE_H - 10 * mm, f"Tax Invoice {inv_no}")
        c.setStrokeColor(LINE)
        c.line(MARGIN, PAGE_H - 12 * mm, PAGE_W - MARGIN, PAGE_H - 12 * mm)
        c.restoreState()

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=16 * mm, bottomMargin=20 * mm, title=f"Invoice {inv_no}", author=business)
    # continuation pages start lower so the running header never overlaps the content
    doc.build(story, onFirstPage=lambda c, d: None, onLaterPages=later_pages, canvasmaker=canvas_cls)
    buf.seek(0)
    return buf.read()
