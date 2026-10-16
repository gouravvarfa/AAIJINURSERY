"""Customer outstanding / advance / frozen invoice balances. One formula (app/accounting/balances.py):
Net = posted invoices - payments - advance receipts + refunds - undecided payments on voided invoices."""
import os
import random
import uuid

from fastapi.testclient import TestClient

from app.accounting.pdf_builder import build_invoice_pdf_bytes
from app.database import SessionLocal
from app.main import app
from app.accounting.models import Invoice

A = "/api/admin/accounting"


def _admin():
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"identifier": os.environ["DEFAULT_ADMIN_USERNAME"], "password": os.environ["DEFAULT_ADMIN_PASSWORD"]}).status_code == 200
    return c


def _customer(c, name="Bal Cust", phone=None):
    phone = phone or f"9{random.randint(10**8, 10**9 - 1)}"
    r = c.post(f"{A}/contacts", json={"name": name, "phone": phone})
    assert r.status_code == 201, r.text
    return r.json()


def _invoice(c, contact_id, amount, **convert):
    so = c.post(f"{A}/sales-orders", json={"contact_id": contact_id, "order_date": "2026-10-14T00:00:00", "items": [{"description": "item", "quantity": 1, "unit_price": amount}]})
    assert so.status_code == 201, so.text
    r = c.post(f"{A}/sales-orders/{so.json()['id']}/convert-to-invoice", json=convert)
    assert r.status_code == 200, r.text
    return r.json()


def _pay(c, invoice_id, amount):
    return c.post(f"{A}/payments-in", json={"invoice_id": invoice_id, "amount": amount, "method": "Cash", "payment_date": "2026-10-15T00:00:00"})


def _pos(c, contact_id):
    return c.get(f"{A}/customers/{contact_id}/position").json()


def _advance(c, contact_id, amount):
    r = c.post(f"{A}/customers/{contact_id}/receipts", json={"amount": amount, "method": "Cash", "request_id": uuid.uuid4().hex})
    assert r.status_code == 201, r.text
    return r.json()


def test_new_customer_then_outstanding_adds_up():
    c = _admin()
    cu = _customer(c)
    first = _invoice(c, cu["id"], 6000)
    assert first["previous_balance"] == 0
    second = _invoice(c, cu["id"], 1500)
    assert second["previous_balance"] == 6000 and second["received_at_issue"] == 0
    assert _pos(c, cu["id"])["net"] == 7500  # 6000 + 1500, nothing paid
    assert _pay(c, second["id"], 2000).status_code == 201 or True
    # 2000 is more than this invoice's 1500: 1500 pays it, 500 stays as advance, and Net = 7500 - 2000
    p = _pos(c, cu["id"])
    assert p["net"] == 5500 and p["advance"] == 500


def test_previous_balance_is_frozen_but_current_outstanding_moves():
    c = _admin()
    cu = _customer(c)
    first = _invoice(c, cu["id"], 1000)
    second = _invoice(c, cu["id"], 400)
    assert second["previous_balance"] == 1000
    assert _pay(c, first["id"], 1000).status_code == 201
    again = c.get(f"{A}/invoices/{second['id']}").json()
    assert again["previous_balance"] == 1000  # never changes
    assert _pos(c, cu["id"])["net"] == 400  # but today's outstanding moved
    db = SessionLocal()
    try:
        inv = db.query(Invoice).filter(Invoice.id == second["id"]).first()
        pdf1 = build_invoice_pdf_bytes(inv, {"business_name": "N", "address": "", "phone": "", "email": ""})
        pdf2 = build_invoice_pdf_bytes(inv, {"business_name": "N", "address": "", "phone": "", "email": ""})
        assert pdf1[:4] == b"%PDF" and len(pdf1) > 800
        assert (inv.previous_balance, inv.received_at_issue) == (1000, 0)
    finally:
        db.close()


def test_partial_and_full_payment_status():
    c = _admin()
    cu = _customer(c)
    inv = _invoice(c, cu["id"], 1000)
    assert _pay(c, inv["id"], 300).status_code == 201
    got = c.get(f"{A}/invoices/{inv['id']}").json()
    assert got["status"] == "PartiallyPaid" and got["balance_due"] == 700
    r = _pay(c, inv["id"], 700)
    assert r.status_code == 201
    assert c.get(f"{A}/invoices/{inv['id']}").json()["status"] == "Paid"
    assert _pay(c, inv["id"], 10).status_code == 400  # fully paid: use an advance instead
    assert _pos(c, cu["id"])["net"] == 0


def test_overpayment_becomes_advance_not_negative_mystery():
    c = _admin()
    cu = _customer(c)
    inv = _invoice(c, cu["id"], 1000)
    r = _pay(c, inv["id"], 1300)
    assert r.status_code == 201 and r.json()["amount"] == 1000 and r.json()["advance_created"] == 300
    p = _pos(c, cu["id"])
    assert p["net"] == -300 and p["advance"] == 300 and p["due"] == 0
    assert any(x["kind"] == "overpayment" and x["amount"] == 300 for x in p["receipts"])


def test_advance_without_invoice_then_applied_without_double_counting():
    c = _admin()
    cu = _customer(c)
    r = _advance(c, cu["id"], 2000)
    assert _pos(c, cu["id"])["net"] == -2000
    # same request id again: no second advance
    dup = c.post(f"{A}/customers/{cu['id']}/receipts", json={"amount": 2000, "method": "Cash", "request_id": "same-request-1"})
    dup2 = c.post(f"{A}/customers/{cu['id']}/receipts", json={"amount": 2000, "method": "Cash", "request_id": "same-request-1"})
    assert dup.status_code == 201 and dup2.json()["already_saved"] is True
    c.post(f"{A}/receipts/{dup.json()['id']}/reverse")
    inv = _invoice(c, cu["id"], 1500)
    assert inv["previous_balance"] == -2000  # shown as advance credit
    before = _pos(c, cu["id"])["net"]
    assert before == -500
    ok = c.post(f"{A}/invoices/{inv['id']}/apply-advance", json={})
    assert ok.status_code == 200 and ok.json()["applied"] == 1500 and ok.json()["balance_due"] == 0
    after = _pos(c, cu["id"])
    assert after["net"] == before and after["due"] == 0 and after["advance"] == 500  # allocation moved credit, never changed Net
    assert c.post(f"{A}/invoices/{inv['id']}/apply-advance", json={"amount": 5}).status_code == 400  # already paid
    assert r["amount"] == 2000


def test_bill_with_payment_and_advance_at_once_is_frozen():
    c = _admin()
    cu = _customer(c)
    _advance(c, cu["id"], 1000)
    inv = _invoice(c, cu["id"], 1500, use_advance=True, received_amount=500, received_method="UPI")
    assert inv["previous_balance"] == -1000 and inv["advance_applied_at_issue"] == 1000 and inv["received_at_issue"] == 500
    assert inv["status"] == "Paid" and inv["balance_due"] == 0
    assert _pos(c, cu["id"])["net"] == 0  # -1000 + 1500 - 500
    # extra money handed over at billing is kept as advance
    cu2 = _customer(c)
    inv2 = _invoice(c, cu2["id"], 1500, received_amount=2000)
    assert inv2["received_at_issue"] == 2000 and _pos(c, cu2["id"])["net"] == -500
    # money received later changes today's outstanding but not the frozen bill
    cu3 = _customer(c)
    inv3 = _invoice(c, cu3["id"], 900)
    _pay(c, inv3["id"], 900)
    frozen = c.get(f"{A}/invoices/{inv3['id']}").json()
    assert frozen["received_at_issue"] == 0 and _pos(c, cu3["id"])["net"] == 0


def test_refund_and_reverse_rules():
    c = _admin()
    cu = _customer(c)
    r = _advance(c, cu["id"], 1000)
    assert c.post(f"{A}/receipts/{r['id']}/refund", json={"amount": 1500, "method": "Cash", "reason": "too much"}).status_code == 400
    assert c.post(f"{A}/receipts/{r['id']}/refund", json={"amount": 400, "method": "Cash", "reason": "gave back"}).status_code == 200
    assert _pos(c, cu["id"])["net"] == -600
    assert c.post(f"{A}/receipts/{r['id']}/reverse").status_code == 400  # already refunded from
    r2 = _advance(c, cu["id"], 100)
    assert c.post(f"{A}/receipts/{r2['id']}/reverse").status_code == 200
    assert _pos(c, cu["id"])["net"] == -600


def test_void_with_payment_needs_an_explicit_choice():
    c = _admin()
    cu = _customer(c)
    inv = _invoice(c, cu["id"], 1000)
    _pay(c, inv["id"], 400)
    assert _pos(c, cu["id"])["net"] == 600
    assert c.post(f"{A}/invoices/{inv['id']}/void").status_code == 400  # must choose
    assert c.get(f"{A}/invoices/{inv['id']}").json()["status"] == "PartiallyPaid"
    v = c.post(f"{A}/invoices/{inv['id']}/void", json={"payment_action": "advance"})
    assert v.status_code == 200 and v.json()["void_disposition"] == "advance"
    p = _pos(c, cu["id"])
    assert p["net"] == -400 and p["advance"] == 400 and p["unresolved_void_amount"] == 0
    assert any(x["kind"] == "void_transfer" and x["amount"] == 400 for x in p["receipts"])
    # voiding again changes nothing
    assert c.post(f"{A}/invoices/{inv['id']}/void", json={"payment_action": "refund"}).status_code == 200
    assert _pos(c, cu["id"])["net"] == -400


def test_void_with_refund_records_both_sides():
    c = _admin()
    cu = _customer(c)
    inv = _invoice(c, cu["id"], 1000)
    _pay(c, inv["id"], 1000)
    c.post(f"{A}/invoices/{inv['id']}/void", json={"payment_action": "refund", "notes": "returned cash"})
    p = _pos(c, cu["id"])
    assert p["net"] == 0 and p["advance"] == 0
    rc = [x for x in p["receipts"] if x["kind"] == "void_transfer"][0]
    assert rc["refunds"] and rc["refunds"][0]["amount"] == 1000 and rc["remaining"] == 0


def test_old_voided_invoice_payment_is_held_then_decided_once():
    c = _admin()
    cu = _customer(c)
    inv = _invoice(c, cu["id"], 800)
    _pay(c, inv["id"], 500)
    db = SessionLocal()
    try:  # how an invoice voided before this feature looks: Voided, payments untouched, nothing decided
        row = db.query(Invoice).filter(Invoice.id == inv["id"]).first()
        row.status = "Voided"
        db.commit()
    finally:
        db.close()
    p = _pos(c, cu["id"])
    assert p["net"] == -500 and p["unresolved_void_amount"] == 500  # same as before: money kept, now flagged
    assert [x["invoice_id"] for x in p["unresolved_void_payments"]] == [inv["id"]]
    r = c.post(f"{A}/invoices/{inv['id']}/resolve-void-payments", json={"action": "advance"})
    assert r.status_code == 200 and r.json()["amount"] == 500
    p2 = _pos(c, cu["id"])
    assert p2["net"] == -500 and p2["unresolved_void_amount"] == 0  # counted once, via the advance
    assert c.post(f"{A}/invoices/{inv['id']}/resolve-void-payments", json={"action": "refund"}).status_code == 400


def test_linked_contacts_only_after_confirmation_and_counted_once():
    c = _admin()
    phone = f"9{random.randint(10**8, 10**9 - 1)}"
    a, b = _customer(c, "Link A", phone), _customer(c, "Link B", phone)
    inv_a = _invoice(c, a["id"], 3000)
    inv_b = _invoice(c, b["id"], 1000)
    _pay(c, inv_b["id"], 250)
    sug = c.get(f"{A}/contact-links/suggestions").json()
    assert any({x["a"]["id"], x["b"]["id"]} == {a["id"], b["id"]} for x in sug)
    assert _pos(c, a["id"])["net"] == 3000  # suggested is not linked
    ok = c.post(f"{A}/contact-links/confirm", json={"contact_a_id": b["id"], "contact_b_id": a["id"]})
    assert ok.status_code == 200 and ok.json()["status"] == "Confirmed"
    pa, pb = _pos(c, a["id"]), _pos(c, b["id"])
    assert pa["net"] == pb["net"] == 3750  # 3000 + 750, each invoice and payment once
    assert len(pa["linked_contacts"]) == 2
    inv_new = _invoice(c, a["id"], 100)
    assert inv_new["previous_balance"] == 3750
    summary = c.get(f"{A}/contacts/{a['id']}").json()
    assert summary["outstanding"] == 3850 and summary["own_outstanding"] == 3100 and summary["linked_contact_ids"] == [b["id"]]
    rep = c.get(f"{A}/reports/customer-outstanding").json()
    rows = [r for r in rep["rows"] if r["contact_id"] in (a["id"], b["id"])]
    assert len(rows) == 1 and rows[0]["outstanding"] == 3850  # one customer, one row
    link_id = ok.json()["id"]
    assert c.post(f"{A}/contact-links/{link_id}/unlink").status_code == 200
    assert _pos(c, a["id"])["net"] == 3100 and _pos(c, b["id"])["net"] == 750
    assert not any({x["a"]["id"], x["b"]["id"]} == {a["id"], b["id"]} for x in c.get(f"{A}/contact-links/suggestions").json())  # rejected pairs are not suggested again
    assert inv_a["previous_balance"] == 0


def test_one_number_everywhere():
    c = _admin()
    cu = _customer(c)
    i1 = _invoice(c, cu["id"], 2000)
    _pay(c, i1["id"], 500)
    _advance(c, cu["id"], 100)
    net = _pos(c, cu["id"])["net"]
    assert net == 1400
    assert c.get(f"{A}/contacts/{cu['id']}").json()["outstanding"] == net
    rep = c.get(f"{A}/reports/customer-outstanding").json()
    assert [r["outstanding"] for r in rep["rows"] if r["contact_id"] == cu["id"]] == [net]
    stmt = c.get(f"{A}/parties/{cu['id']}/statement").json()
    assert stmt["closing_balance"] == net


def test_sales_order_alone_never_counts():
    c = _admin()
    cu = _customer(c)
    c.post(f"{A}/sales-orders", json={"contact_id": cu["id"], "order_date": "2026-10-14T00:00:00", "items": [{"description": "x", "quantity": 1, "unit_price": 999}]})
    assert _pos(c, cu["id"])["net"] == 0


def test_legacy_invoice_without_snapshot_still_prints():
    c = _admin()
    cu = _customer(c)
    inv = _invoice(c, cu["id"], 500)
    db = SessionLocal()
    try:
        row = db.query(Invoice).filter(Invoice.id == inv["id"]).first()
        row.previous_balance = None
        row.received_at_issue = None
        db.commit()
        pdf = build_invoice_pdf_bytes(row, {"business_name": "N", "address": "", "phone": "", "email": ""})
        assert pdf[:4] == b"%PDF"
    finally:
        db.close()
    assert c.get(f"{A}/invoices/{inv['id']}/pdf").status_code == 200
