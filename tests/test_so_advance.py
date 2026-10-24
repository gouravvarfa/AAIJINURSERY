"""Advance payment on a Sales Order: lowers what the customer owes at once, is used on the invoice, never counted twice."""
import uuid

from tests.test_customer_balance import A, _admin, _customer, _pos


def _so(c, contact_id, amount):
    r = c.post(f"{A}/sales-orders", json={"contact_id": contact_id, "order_date": "2026-10-14T00:00:00", "items": [{"description": "item", "quantity": 1, "unit_price": amount}]})
    assert r.status_code == 201, r.text
    return r.json()


def _adv(c, so_id, amount, rid=None, **kw):
    return c.post(f"{A}/sales-orders/{so_id}/advance", json={"amount": amount, "method": "UPI", "request_id": rid or uuid.uuid4().hex} | kw)


def test_advance_lowers_outstanding_and_is_used_on_the_invoice():
    c = _admin()
    cust = _customer(c)
    so = _so(c, cust["id"], 1000)
    r = _adv(c, so["id"], 300)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["advance_received"] == 300 and d["balance_after_advance"] == 700 and len(d["advances"]) == 1
    assert _pos(c, cust["id"])["net"] == -300  # the customer has 300 with us, nothing is owed yet
    inv = c.post(f"{A}/sales-orders/{so['id']}/convert-to-invoice", json={})
    assert inv.status_code == 200, inv.text
    inv = inv.json()
    assert inv["amount_paid"] == 300 and inv["balance_due"] == 700
    assert _pos(c, cust["id"])["net"] == 700  # owes the rest, advance not counted twice
    assert c.get(f"{A}/sales-orders/{so['id']}").json()["advance_remaining"] == 0


def test_advance_covering_the_whole_order_marks_invoice_paid():
    c = _admin()
    cust = _customer(c)
    so = _so(c, cust["id"], 500)
    assert _adv(c, so["id"], 200).status_code == 201
    assert _adv(c, so["id"], 300).status_code == 201
    inv = c.post(f"{A}/sales-orders/{so['id']}/convert-to-invoice", json={}).json()
    assert inv["status"] == "Paid" and inv["balance_due"] == 0
    assert _pos(c, cust["id"])["net"] == 0


def test_retry_never_double_records_and_cannot_exceed_order_total():
    c = _admin()
    cust = _customer(c)
    so = _so(c, cust["id"], 400)
    rid = uuid.uuid4().hex
    assert _adv(c, so["id"], 150, rid).status_code == 201
    assert _adv(c, so["id"], 150, rid).status_code == 201
    assert c.get(f"{A}/sales-orders/{so['id']}").json()["advance_received"] == 150
    assert _adv(c, so["id"], 300).status_code == 400  # 150 + 300 > 400
    assert _adv(c, so["id"], 0).status_code == 422
    assert _pos(c, cust["id"])["net"] == -150


def test_no_advance_on_invoiced_order_and_reversal_restores_balance():
    c = _admin()
    cust = _customer(c)
    so = _so(c, cust["id"], 600)
    rid = _adv(c, so["id"], 100).json()["advances"][0]["id"]
    assert c.post(f"{A}/receipts/{rid}/reverse").status_code == 200
    assert c.get(f"{A}/sales-orders/{so['id']}").json()["advance_received"] == 0
    assert _pos(c, cust["id"])["net"] == 0
    c.post(f"{A}/sales-orders/{so['id']}/convert-to-invoice", json={})
    assert _adv(c, so["id"], 50).status_code == 400
