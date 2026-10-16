"""Seed packet batches: movement-log quantities, expiry alerts from today's date, auto expense."""
import os
import random
import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Plant

P = "/api/admin/stock/seed-packets"
A = "/api/admin/accounting"
_n = {"i": 0}


def _admin():
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"identifier": os.environ["DEFAULT_ADMIN_USERNAME"], "password": os.environ["DEFAULT_ADMIN_PASSWORD"]}).status_code == 200
    return c


def _plant(c, stock=40):
    _n["i"] += 1
    cat = c.get("/api/admin/categories").json()[0]
    r = c.post("/api/admin/plants", json={"name": f"Packet Plant {_n['i']}", "category_id": cat["id"], "price": 5, "stock_quantity": stock})
    assert r.status_code == 201, r.text
    return r.json()


def _body(plant, days=400, **kw):
    today = date.today()
    base = {"plant_id": plant["id"], "variety": "Hybrid", "company": f"Co{random.randint(1, 999)}", "supplier": f"Sup{random.randint(1, 999)}", "batch_number": f"B-{uuid.uuid4().hex[:6]}",
            "packets": 25, "packet_size": 10, "packet_unit": "g", "purchase_date": today.isoformat(), "expiry_date": (today + timedelta(days=days)).isoformat(),
            "unit_price": 100, "invoice_number": "BILL-1", "request_id": uuid.uuid4().hex}
    return base | kw


def _make(c, plant, **kw):
    r = c.post(P, json=_body(plant, **kw))
    assert r.status_code == 201, r.text
    return r.json()


def test_entry_saves_batch_and_books_expense_automatically():
    c = _admin()
    plant = _plant(c)
    stock_before = c.get(f"/api/admin/plants/{plant['id']}").json()["stock_quantity"] if False else 40
    b = _make(c, plant, packets=20, unit_price=150, supplier="Ravi Seeds Agency", invoice_number="INV-77")
    assert b["received"] == 20 and b["remaining"] == 20 and b["used"] == 0 and b["status"] == "OK" and b["record_no"].startswith("SP-")
    db = SessionLocal()
    try:
        assert db.query(Plant.stock_quantity).filter(Plant.id == plant["id"]).scalar() == stock_before  # plant stock untouched
    finally:
        db.close()
    exp = [e for e in c.get(f"{A}/expenses?q=Seed Packets").json() if f"batch {b['batch_number']}" in e["description"]]
    assert len(exp) == 1
    e = exp[0]
    assert e["category"] == "Seed Packets" and e["total_amount"] == 3000 and e["status"] == "Unpaid" and e["reference"] == "INV-77" and e["contact"]["name"] == "Ravi Seeds Agency"


def test_paid_now_marks_expense_paid_and_double_click_books_once():
    c = _admin()
    plant = _plant(c)
    body = _body(plant, packets=10, total_amount=900, paid_now=True, paid_method="UPI")
    a, b = c.post(P, json=body), c.post(P, json=body)
    assert a.status_code == 201 and b.json()["already_saved"] is True and a.json()["id"] == b.json()["id"]
    found = [e for e in c.get(f"{A}/expenses?q=Seed Packets").json() if f"batch {body['batch_number']}" in e["description"]]
    assert len(found) == 1 and found[0]["status"] == "Paid" and found[0]["balance_due"] == 0 and found[0]["amount_paid"] == 900
    assert a.json()["remaining"] == 10


def test_no_price_means_no_expense():
    c = _admin()
    plant = _plant(c)
    body = _body(plant, unit_price=None)
    body.pop("unit_price")
    b = c.post(P, json=body).json()
    assert not [e for e in c.get(f"{A}/expenses?q=Seed Packets").json() if f"batch {body['batch_number']}" in e["description"]]
    assert b["remaining"] == 25


def test_validation():
    c = _admin()
    plant = _plant(c)
    today = date.today()
    bad = lambda **kw: c.post(P, json=_body(plant, **kw)).status_code
    assert bad(packets=0) == 422 and bad(packets=-3) == 422
    assert c.post(P, json={k: v for k, v in _body(plant).items() if k != "expiry_date"}).status_code == 422  # expiry required
    assert bad(expiry_date="2026-13-45") == 422
    assert bad(expiry_date=(today - timedelta(days=5)).isoformat()) == 400  # expiry before purchase
    assert bad(manufacturing_date=(today + timedelta(days=500)).isoformat()) == 400
    assert bad(plant_id=99999999) == 400
    assert bad(packet_unit="bucket") == 400
    assert bad(company="") == 422 and bad(batch_number="") == 422


def test_same_batch_number_is_never_silently_mixed():
    c = _admin()
    plant = _plant(c)
    first = _make(c, plant, packets=10, company="Same Co", variety="Cherry", batch_number="LOT-1")
    again = _body(plant, packets=5, company="same co", variety="cherry", batch_number="lot-1", expiry_date=first["expiry_date"])
    r = c.post(P, json=again)
    assert r.status_code == 409 and r.text.count("BATCH_EXISTS") == 1  # asks first
    assert c.get(f"{P}/{first['id']}").json()["remaining"] == 10
    other_exp = again | {"expiry_date": (date.today() + timedelta(days=700)).isoformat(), "merge_into_existing": True, "request_id": uuid.uuid4().hex}
    assert c.post(P, json=other_exp).status_code == 409  # a batch has one expiry: never overwritten
    assert c.get(f"{P}/{first['id']}").json()["expiry_date"] == first["expiry_date"]
    merged = c.post(P, json=again | {"merge_into_existing": True, "request_id": uuid.uuid4().hex})
    assert merged.status_code == 201 and merged.json()["merged"] is True and merged.json()["id"] == first["id"]
    assert merged.json()["received"] == 15 and merged.json()["remaining"] == 15
    # a different company with the same batch number is a different batch
    third = _make(c, plant, packets=3, company="Other Co", variety="Cherry", batch_number="LOT-1")
    assert third["id"] != first["id"]


def test_use_adjust_correct_writeoff_all_leave_history():
    c = _admin()
    plant = _plant(c)
    b = _make(c, plant, packets=30)
    use = c.post(f"{P}/{b['id']}/use", json={"quantity": 12, "request_id": uuid.uuid4().hex})
    assert use.status_code == 200 and use.json()["used"] == 12 and use.json()["remaining"] == 18
    assert c.post(f"{P}/{b['id']}/use", json={"quantity": 19, "request_id": uuid.uuid4().hex}).status_code == 400  # more than left
    rid = uuid.uuid4().hex
    c.post(f"{P}/{b['id']}/use", json={"quantity": 1, "request_id": rid})
    again = c.post(f"{P}/{b['id']}/use", json={"quantity": 1, "request_id": rid})
    assert again.json()["already_saved"] is True and again.json()["remaining"] == 17  # double click: once
    adj = c.post(f"{P}/{b['id']}/adjust", json={"new_remaining": 15, "reason": "counted shelf", "request_id": uuid.uuid4().hex})
    assert adj.json()["remaining"] == 15 and adj.json()["adjusted"] == -2
    assert c.post(f"{P}/{b['id']}/adjust", json={"new_remaining": 15, "reason": "same", "request_id": uuid.uuid4().hex}).status_code == 400
    new_exp = (date.today() + timedelta(days=200)).isoformat()
    cor = c.post(f"{P}/{b['id']}/correct", json={"expiry_date": new_exp, "reason": "typed wrong date", "request_id": uuid.uuid4().hex})
    assert cor.status_code == 200 and cor.json()["expiry_date"] == new_exp
    hist = c.get(f"{P}/history?batch_id={b['id']}").json()
    types = [h["type"] for h in hist]
    assert types.count("RECEIPT") == 1 and "USAGE" in types and "ADJUSTMENT" in types and "CORRECTION" in types
    corr = [h for h in hist if h["type"] == "CORRECTION"][0]
    assert b["expiry_date"] in corr["detail"] and new_exp in corr["detail"] and corr["reason"] == "typed wrong date" and corr["by"]
    wo = c.post(f"{P}/{b['id']}/write-off", json={"reason": "discard rest", "request_id": uuid.uuid4().hex})
    assert wo.json()["remaining"] == 0 and wo.json()["status"] == "Empty" and wo.json()["written_off"] == 15
    assert c.post(f"{P}/{b['id']}/write-off", json={"reason": "again", "request_id": uuid.uuid4().hex}).status_code == 400
    assert len(c.get(f"{P}/history?batch_id={b['id']}").json()) == len(hist) + 1  # nothing deleted, only added


def test_expired_packets_are_not_normal_stock():
    c = _admin()
    plant = _plant(c)
    b = _make(c, plant, packets=10)
    # make it expired the way time would: fix the date through the audited correction
    past = (date.today() - timedelta(days=3)).isoformat()
    db = SessionLocal()
    try:
        from app.seed_packet_models import SeedPacketBatch
        row = db.query(SeedPacketBatch).filter(SeedPacketBatch.id == b["id"]).first()
        row.purchase_date = date.today() - timedelta(days=400)
        row.expiry_date = date.fromisoformat(past)
        db.commit()
    finally:
        db.close()
    assert c.get(f"{P}/{b['id']}").json()["status"] == "Expired"
    assert c.post(f"{P}/{b['id']}/use", json={"quantity": 2, "request_id": uuid.uuid4().hex}).status_code == 400
    assert c.post(f"{P}/{b['id']}/use", json={"quantity": 2, "allow_expired": True, "reason": "x", "request_id": uuid.uuid4().hex}).status_code == 400  # needs a real reason
    ok = c.post(f"{P}/{b['id']}/use", json={"quantity": 2, "allow_expired": True, "reason": "Owner approved for test sowing", "request_id": uuid.uuid4().hex})
    assert ok.status_code == 200 and ok.json()["remaining"] == 8
    exc = [h for h in c.get(f"{P}/history?batch_id={b['id']}").json() if h["type"] == "USAGE"][0]
    assert exc["is_exception"] is True and "expired" in exc["detail"]


def test_alerts_use_todays_date_and_are_announced_once():
    c = _admin()
    plant = _plant(c)
    soon = _make(c, plant, days=20, packets=7, batch_number="SOON-1")
    week = _make(c, plant, days=5, packets=3, batch_number="WEEK-1")
    far = _make(c, plant, days=400, packets=9, batch_number="FAR-1")
    empty = _make(c, plant, days=10, packets=2, batch_number="EMPTY-1")
    c.post(f"{P}/{empty['id']}/write-off", json={"reason": "gone", "request_id": uuid.uuid4().hex})
    first = {a["id"]: a for a in c.get(f"{P}/alerts").json()["items"]}
    assert soon["id"] in first and week["id"] in first and far["id"] not in first and empty["id"] not in first
    s, w = first[soon["id"]], first[week["id"]]
    assert s["days_left"] == 20 and s["warning_period"] == 30 and s["alert_key"] == "d30" and s["is_new"] is True and s["remaining"] == 7
    assert w["days_left"] == 5 and w["warning_period"] == 7 and w["level"] == "critical"
    second = {a["id"]: a for a in c.get(f"{P}/alerts").json()["items"]}
    assert second[soon["id"]]["is_new"] is False  # same batch + period is not announced again


def test_warning_periods_are_configurable():
    c = _admin()
    plant = _plant(c)
    b = _make(c, plant, days=100, packets=4, batch_number="CFG-1")
    assert b["status"] == "OK"
    assert c.put(f"{P}/settings", json={"warning_days": [120, 60]}).json()["warning_days"] == [120, 60]
    try:
        got = c.get(f"{P}/{b['id']}").json()
        assert got["status"] == "Expiring soon" and got["warning_period"] == 120
    finally:
        c.put(f"{P}/settings", json={"warning_days": [90, 30, 15, 7]})
    assert c.put(f"{P}/settings", json={"warning_days": [0, -5]}).status_code == 400


def test_inventory_filters_and_totals():
    c = _admin()
    plant = _plant(c)
    a = _make(c, plant, company="FilterCo Alpha", supplier="SupAlpha", batch_number="FA-1", packets=5)
    b = _make(c, plant, company="FilterCo Beta", supplier="SupBeta", batch_number="FB-1", packets=8, days=10)
    inv = c.get(f"{P}?plant_id={plant['id']}").json()
    assert {r["id"] for r in inv["items"]} == {a["id"], b["id"]} and inv["totals"]["remaining"] == 13
    assert [r["id"] for r in c.get(f"{P}?plant_id={plant['id']}&company=Beta").json()["items"]] == [b["id"]]
    assert [r["id"] for r in c.get(f"{P}?plant_id={plant['id']}&supplier=SupAlpha").json()["items"]] == [a["id"]]
    assert [r["id"] for r in c.get(f"{P}?plant_id={plant['id']}&batch=FA-").json()["items"]] == [a["id"]]
    assert [r["id"] for r in c.get(f"{P}?plant_id={plant['id']}&expiry=soon").json()["items"]] == [b["id"]]
    assert [r["id"] for r in c.get(f"{P}?plant_id={plant['id']}&expiry=ok").json()["items"]] == [a["id"]]


def test_requires_login():
    assert TestClient(app).get(P).status_code in (401, 403)
