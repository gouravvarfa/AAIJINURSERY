"""Tax invoice PDF: real data only, frozen balances, optional blocks, Hindi, many pages."""
import base64
import os
import random
from io import BytesIO

import pypdf
from fastapi.testclient import TestClient

from app.accounting import pdf_builder
from app.accounting.invoice_pdf import pretty_address
from app.accounting.invoice_words import amount_in_words, indian_number
from app.accounting.models import Invoice, InvoiceSetting
from app.accounting.pdf_builder import build_invoice_pdf_bytes
from app.database import SessionLocal
from app.main import app
from app.settings_helper import get_settings

A = "/api/admin/accounting"
SETTINGS = {"business_name": "Shree Aaiji High Tech Nursery", "phone": "9754315722", "email": "hightechaaijinursery@gmail.com", "address": "Raipuriya distict jhabua ", "tagline": "Bringing Green Life to Every Home"}
PNG = base64.b64encode(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")).decode()


def _admin():
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"identifier": os.environ["DEFAULT_ADMIN_USERNAME"], "password": os.environ["DEFAULT_ADMIN_PASSWORD"]}).status_code == 200
    return c


def _set(values):
    db = SessionLocal()
    try:
        db.query(InvoiceSetting).delete()
        for k, v in values.items():
            db.add(InvoiceSetting(key=k, value=v))
        db.commit()
    finally:
        db.close()


def _invoice(c, items=None, name="PDF Cust", phone=None, address="Ringol, District Jhabua", **convert):
    ct = c.post(f"{A}/contacts", json={"name": name, "phone": phone or f"9{random.randint(10**8, 10**9 - 1)}", "address": address}).json()
    so = c.post(f"{A}/sales-orders", json={"contact_id": ct["id"], "order_date": "2026-10-14T00:00:00", "items": items or [{"description": "Tomato tray", "quantity": 2, "unit_price": 500}]}).json()
    r = c.post(f"{A}/sales-orders/{so['id']}/convert-to-invoice", json=convert)
    assert r.status_code == 200, r.text
    return ct, r.json()


def _pdf(invoice_id):
    db = SessionLocal()
    try:
        inv = db.query(Invoice).filter(Invoice.id == invoice_id).first()
        data = build_invoice_pdf_bytes(inv, get_settings(db) | SETTINGS)
    finally:
        db.close()
    reader = pypdf.PdfReader(BytesIO(data))
    return data, reader, "\n".join(p.extract_text() for p in reader.pages)


def test_words_and_indian_numbers_and_address():
    assert indian_number(1234567.5) == "12,34,567.50" and indian_number(999) == "999.00" and indian_number(0) == "0.00"
    assert amount_in_words(9920) == "Rupees Nine Thousand Nine Hundred Twenty Only"
    assert amount_in_words(100000) == "Rupees One Lakh Only" and amount_in_words(10.5) == "Rupees Ten and Fifty Paise Only"
    assert pretty_address("Raipuriya distict jhabua ") == "Raipuriya, District Jhabua"
    assert pretty_address("") == "" and pretty_address("12 Main Road, Indore") == "12 Main Road, Indore"


def test_invoice_has_all_sections_and_real_numbers():
    c = _admin()
    _set({})
    ct, inv = _invoice(c, items=[{"description": "Brinjal seedlings", "quantity": 3, "unit_price": 250}], received_amount=300, received_method="UPI")
    data, reader, text = _pdf(inv["id"])
    assert data[:4] == b"%PDF" and len(reader.pages) == 1
    for needle in ("Shree Aaiji High Tech Nursery", "Raipuriya, District Jhabua", "9754315722", "hightechaaijinursery@gmail.com", "TAX INVOICE", f"INV-{inv['id']}", "Brinjal seedlings",
                   "750.00", "Total Invoice Amount", "Previous Balance", "Received", "300.00", "Balance Due (Invoice)", "450.00", "Current Balance", "Rupees Seven Hundred Fifty Only",
                   "Acknowledgement Slip", "Authorized Signatory", "Payment Mode", "UPI", ct["name"], "Ringol, District Jhabua"):
        assert needle in text, needle
    assert b"NotoSans" in data  # real fonts embedded (rupee sign, Hindi)


def test_optional_blocks_are_left_out_when_not_configured():
    c = _admin()
    _set({})
    _, inv = _invoice(c, address="")
    _, _, text = _pdf(inv["id"])
    for absent in ("BANK DETAILS", "Terms & Conditions", "TERMS & CONDITIONS", "GSTIN", "Driver Name", "Vehicle No", "Payment Note", "PAYMENT NOTE", "Proprietor", "Payment Mode", "TRANSPORTATION"):
        assert absent not in text, absent


def test_bank_terms_hindi_phones_signature_and_gstin_only_when_set():
    c = _admin()
    _set({"invoice_bank_name": "HDFC BANK", "invoice_bank_account": "50200104537837", "invoice_bank_ifsc": "HDFC0006696", "invoice_bank_holder": "YOGESH JI SEPTA",
          "invoice_terms": "भूल चूक लेन देनी ।", "invoice_extra_phones": "Booking office: 9754315710", "invoice_signature": "data:image/png;base64," + PNG, "invoice_gstin": "24AABCR1234F1Z5",
          "invoice_proprietor": "Yogesh Septa", "invoice_payment_note": "Pay within the due date."})
    ct, inv = _invoice(c)
    data, _, text = _pdf(inv["id"])
    for needle in ("BANK DETAILS", "HDFC BANK", "50200104537837", "HDFC0006696", "YOGESH JI SEPTA", "Booking office: 9754315710", "Proprietor: Yogesh Septa", "Pay within the due date."):
        assert needle in text, needle
    assert b"NotoSansDevanagari" in data  # the Hindi font is in the file
    assert "GSTIN" not in text.split("BILL TO")[0]  # business GSTIN is not printed by mistake into the header
    _set({})


def test_balances_follow_the_frozen_snapshot_and_old_invoices_show_none():
    c = _admin()
    _set({})
    ct, old = _invoice(c, items=[{"description": "Old bill", "quantity": 1, "unit_price": 6000}])
    _, new = _invoice.__wrapped__(c) if False else (None, None)
    so = c.post(f"{A}/sales-orders", json={"contact_id": ct["id"], "order_date": "2026-10-14T00:00:00", "items": [{"description": "New bill", "quantity": 1, "unit_price": 1500}]}).json()
    new = c.post(f"{A}/sales-orders/{so['id']}/convert-to-invoice", json={}).json()
    _, _, before = _pdf(new["id"])
    assert "6,000.00" in before and "7,500.00" in before  # previous 6,000, current 7,500
    c.post(f"{A}/payments-in", json={"invoice_id": old["id"], "amount": 4000, "method": "Cash", "payment_date": "2026-10-16T00:00:00"})
    _, _, after = _pdf(new["id"])
    assert "6,000.00" in after and "7,500.00" in after  # a later payment never rewrites the printed bill
    assert c.get(f"{A}/customers/{ct['id']}/position").json()["net"] == 3500  # but today's outstanding moved
    # an invoice from before balances were frozen: no Previous / Current Balance at all, no fake zeros
    db = SessionLocal()
    try:
        row = db.query(Invoice).filter(Invoice.id == old["id"]).first()
        row.previous_balance = None
        db.commit()
    finally:
        db.close()
    _, _, legacy = _pdf(old["id"])
    assert "Previous Balance" not in legacy and "Current Balance" not in legacy and "Amount Paid" in legacy and "Balance Due" in legacy


def test_payment_mode_is_the_recorded_one_and_never_assumed():
    c = _admin()
    _set({})
    _, unpaid = _invoice(c)
    _, _, t1 = _pdf(unpaid["id"])
    assert "Payment Mode" not in t1
    _, paid = _invoice(c, received_amount=100, received_method="Bank")
    _, _, t2 = _pdf(paid["id"])
    assert "Payment Mode" in t2 and "BANK" in t2 and "CASH" not in t2.upper().replace("CASHIER", "")


def test_advance_credit_is_labelled_not_shown_as_a_balance():
    c = _admin()
    _set({})
    ct = c.post(f"{A}/contacts", json={"name": "Adv PDF", "phone": f"9{random.randint(10**8, 10**9 - 1)}"}).json()
    c.post(f"{A}/customers/{ct['id']}/receipts", json={"amount": 2000, "method": "Cash", "request_id": f"pdf-adv-{random.randint(1, 10**9)}"})
    so = c.post(f"{A}/sales-orders", json={"contact_id": ct["id"], "order_date": "2026-10-14T00:00:00", "items": [{"description": "Bill", "quantity": 1, "unit_price": 500}]}).json()
    inv = c.post(f"{A}/sales-orders/{so['id']}/convert-to-invoice", json={"use_advance": True}).json()
    _, _, text = _pdf(inv["id"])
    assert "Previous Advance Credit" in text and "Advance adjusted" in text and "Current Advance Credit" in text and "1,500.00" in text


def test_many_items_make_more_pages_with_repeated_headers():
    c = _admin()
    _set({"invoice_terms": "One term"})
    items = [{"description": f"Seedling item {i} with a long descriptive name that needs wrapping inside the table", "quantity": i + 1, "unit_price": 3 + i} for i in range(55)]
    _, inv = _invoice(c, items=items)
    data, reader, _ = _pdf(inv["id"])
    assert len(reader.pages) >= 3
    assert all("Item Name" in p.extract_text() for p in reader.pages[:-1]) or "Item Name" in reader.pages[1].extract_text()
    assert "Page 2 of" in reader.pages[1].extract_text()
    assert "Acknowledgement Slip" in reader.pages[-1].extract_text()  # the slip sits on the last page only
    assert all("Acknowledgement Slip" not in p.extract_text() for p in reader.pages[:-1])
    _set({})


def test_new_layout_failure_falls_back_to_the_plain_pdf(monkeypatch):
    import app.accounting.invoice_pdf as new

    c = _admin()
    _, inv = _invoice(c)
    monkeypatch.setattr(new, "build_invoice_pdf", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    data, _, text = _pdf(inv["id"])
    assert data[:4] == b"%PDF" and "INVOICE" in text


def test_invoice_settings_api_rules_and_privacy():
    c = _admin()
    _set({})
    ok = c.put(f"{A}/invoice-settings", json={"values": {"invoice_bank_account": "50200104537837", "invoice_bank_ifsc": "hdfc0006696", "invoice_terms": "Line one\nLine two"}})
    assert ok.status_code == 200
    got = {f["key"]: f["value"] for f in ok.json()["fields"]}
    assert got["invoice_bank_ifsc"] == "HDFC0006696" and got["invoice_terms"] == "Line one\nLine two"
    assert c.put(f"{A}/invoice-settings", json={"values": {"invoice_bank_ifsc": "BAD"}}).status_code == 400
    assert c.put(f"{A}/invoice-settings", json={"values": {"invoice_bank_account": "12ab"}}).status_code == 400
    assert c.put(f"{A}/invoice-settings", json={"values": {"invoice_gstin": "NOTAGSTIN"}}).status_code == 400
    assert c.put(f"{A}/invoice-settings", json={"values": {"invoice_signature": "data:text/html;base64,AAAA"}}).status_code == 400
    assert c.put(f"{A}/invoice-settings", json={"values": {"something_else": "x"}}).status_code == 400
    # never exposed on the public website's settings endpoint
    public = TestClient(app).get("/api/settings").text
    assert "50200104537837" not in public and "invoice_bank" not in public
    assert TestClient(app).get(f"{A}/invoice-settings").status_code in (401, 403)
    _set({})
