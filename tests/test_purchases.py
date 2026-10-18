"""Admin Purchases: supplier account, no double stock, merged/separate lines, inactive new plants."""
import os
import uuid
from datetime import datetime

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import InventoryTransaction, Plant, Purchase

A = "/api/admin"
ACC = "/api/admin/accounting"
_n = {"i": 0}


def _admin():
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"identifier": os.environ["DEFAULT_ADMIN_USERNAME"], "password": os.environ["DEFAULT_ADMIN_PASSWORD"]}).status_code == 200
    return c


def _plant(c, stock=0, active=True, **kw):
    _n["i"] += 1
    cat = c.get(f"{A}/categories").json()[0]
    r = c.post(f"{A}/plants", json={"name": f"Buy Plant {_n['i']}-{uuid.uuid4().hex[:4]}", "category_id": cat["id"], "price": 10, "stock_quantity": stock, "is_active": active} | kw)
    assert r.status_code == 201, r.text
    return r.json()


def _stock(plant_id):
    db = SessionLocal()
    try:
        return db.query(Plant.stock_quantity).filter(Plant.id == plant_id).scalar()
    finally:
        db.close()


def _supplier(c, name=None):
    r = c.post(f"{ACC}/contacts", json={"name": name or f"Supplier {uuid.uuid4().hex[:5]}", "contact_type": "supplier", "phone": "9000011111"})
    assert r.status_code == 201, r.text
    return r.json()


def _body(items, **kw):
    return {"purchase_date": datetime.utcnow().isoformat(), "items": items, "request_id": uuid.uuid4().hex} | kw


def test_existing_plant_purchase_adds_stock_once():
    c = _admin()
    p = _plant(c, stock=10)
    r = c.post(f"{A}/purchases", json=_body([{"plant_id": p["id"], "quantity": 25, "unit_cost": 4}]))
    assert r.status_code == 201 and r.json()["total_cost"] == 100
    assert _stock(p["id"]) == 35
    assert r.json()["contact_id"] is None  # no supplier chosen: works exactly as before


def test_double_submit_gives_the_same_purchase_and_one_stock_increase():
    c = _admin()
    p = _plant(c)
    body = _body([{"plant_id": p["id"], "quantity": 40, "unit_cost": 2.5}])
    a, b = c.post(f"{A}/purchases", json=body), c.post(f"{A}/purchases", json=body)
    assert a.status_code == 201 and a.json()["id"] == b.json()["id"]
    assert _stock(p["id"]) == 40
    db = SessionLocal()
    try:
        assert db.query(Purchase).filter(Purchase.request_id == body["request_id"]).count() == 1
        assert db.query(InventoryTransaction).filter(InventoryTransaction.plant_id == p["id"], InventoryTransaction.transaction_type == "PURCHASE_RECEIVED").count() == 1
    finally:
        db.close()


def test_supplier_gets_the_purchase_unpaid_and_payable_is_right():
    c = _admin()
    sup = _supplier(c)
    p = _plant(c)
    r = c.post(f"{A}/purchases", json=_body([{"plant_id": p["id"], "quantity": 10, "unit_cost": 30}], supplier_contact_id=sup["id"], invoice_number="SUP-INV-1"))
    assert r.status_code == 201
    pur = r.json()
    assert pur["contact_id"] == sup["id"] and pur["status"] == "Unpaid" and pur["supplier"] == sup["name"]
    got = c.get(f"{ACC}/contacts/{sup['id']}").json()
    assert got["total_purchases"] == 300 and got["payable"] == 300 and got["total_paid_out"] == 0  # nothing is assumed paid
    # it is in the supplier's bills / timeline / statement, once
    bills = c.get(f"{ACC}/bills?contact_id={sup['id']}").json()
    assert [b["id"] for b in bills] == [pur["id"]] and bills[0]["balance_due"] == 300
    timeline = c.get(f"{ACC}/parties/{sup['id']}/timeline").json()
    assert sum(1 for row in timeline["rows"] if row["type"] == "bill") == 1
    stmt = c.get(f"{ACC}/parties/{sup['id']}/statement").json()
    assert stmt["closing_balance"] == 300 and len(stmt["rows"]) == 1
    # a payment recorded in Accounting reduces the payable; a second purchase adds to it
    assert c.post(f"{ACC}/payments-out", json={"purchase_id": pur["id"], "amount": 100, "method": "Cash", "payment_date": "2026-10-16T00:00:00"}).status_code == 201
    c.post(f"{A}/purchases", json=_body([{"plant_id": p["id"], "quantity": 5, "unit_cost": 20}], supplier_contact_id=sup["id"]))
    assert c.get(f"{ACC}/contacts/{sup['id']}").json()["payable"] == 300 - 100 + 100


def test_only_real_suppliers_can_be_chosen():
    c = _admin()
    p = _plant(c)
    customer = c.post(f"{ACC}/contacts", json={"name": "Just a customer", "contact_type": "customer"}).json()
    items = [{"plant_id": p["id"], "quantity": 1, "unit_cost": 1}]
    assert c.post(f"{A}/purchases", json=_body(items, supplier_contact_id=customer["id"])).status_code == 400
    assert c.post(f"{A}/purchases", json=_body(items, supplier_contact_id=99999999)).status_code == 400
    assert _stock(p["id"]) == 0  # nothing happened


def test_free_text_supplier_still_works_without_a_contact():
    c = _admin()
    p = _plant(c)
    r = c.post(f"{A}/purchases", json=_body([{"plant_id": p["id"], "quantity": 3, "unit_cost": 5}], supplier="Local mandi"))
    assert r.status_code == 201 and r.json()["supplier"] == "Local mandi" and r.json()["contact_id"] is None


def test_failed_purchase_leaves_no_stock_or_records():
    c = _admin()
    p1, p2 = _plant(c, stock=7), _plant(c, stock=3)
    bad = _body([{"plant_id": p1["id"], "quantity": 10, "unit_cost": 1}, {"plant_id": p2["id"], "quantity": 0, "unit_cost": 1}])
    assert c.post(f"{A}/purchases", json=bad).status_code == 400
    assert c.post(f"{A}/purchases", json=_body([{"plant_id": p1["id"], "quantity": 2, "unit_cost": -1}])).status_code == 400
    assert c.post(f"{A}/purchases", json=_body([{"plant_id": p1["id"], "quantity": 2, "unit_cost": 1}, {"plant_id": 99999999, "quantity": 1, "unit_cost": 1}])).status_code == 400
    assert (_stock(p1["id"]), _stock(p2["id"])) == (7, 3)
    db = SessionLocal()
    try:
        assert db.query(Purchase).filter(Purchase.request_id == bad["request_id"]).count() == 0
    finally:
        db.close()


def test_same_plant_same_cost_is_merged_exactly():
    c = _admin()
    p = _plant(c)
    r = c.post(f"{A}/purchases", json=_body([{"plant_id": p["id"], "quantity": 10, "unit_cost": 3.5}, {"plant_id": p["id"], "quantity": 15, "unit_cost": 3.5}]))
    assert r.status_code == 201
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["quantity"] == 25 and items[0]["total_cost"] == 87.5 and r.json()["total_cost"] == 87.5
    assert _stock(p["id"]) == 25


def test_same_plant_different_costs_stay_separate_and_every_line_adds_stock():
    c = _admin()
    p = _plant(c)
    r = c.post(f"{A}/purchases", json=_body([{"plant_id": p["id"], "quantity": 10, "unit_cost": 4}, {"plant_id": p["id"], "quantity": 20, "unit_cost": 5}, {"plant_id": p["id"], "quantity": 5, "unit_cost": 4}]))
    assert r.status_code == 201
    items = sorted((i["quantity"], i["unit_cost"], i["total_cost"]) for i in r.json()["items"])
    assert items == [(15, 4, 60), (20, 5, 100)]  # the two costs are both kept
    assert r.json()["total_cost"] == 160
    assert _stock(p["id"]) == 35  # 10 + 20 + 5, none skipped
    again = c.post(f"{A}/purchases", json=_body([{"plant_id": p["id"], "quantity": 1, "unit_cost": 9}]))
    assert again.status_code == 201 and _stock(p["id"]) == 36


def test_new_plant_made_inactive_gets_no_stock_until_the_purchase_is_saved():
    c = _admin()
    p = _plant(c, active=False)  # what the Add Purchase popup creates
    assert p["is_active"] is False and _stock(p["id"]) == 0
    assert c.post(f"{A}/purchases", json=_body([{"plant_id": p["id"], "quantity": 12, "unit_cost": 6}])).status_code == 201
    assert _stock(p["id"]) == 12


def test_inactive_plants_are_not_public_anywhere():
    c = _admin()
    cat_id = c.get(f"{A}/categories").json()[0]["id"]
    hidden = _plant(c, active=False, category_id=cat_id)
    visible = _plant(c, active=True, category_id=cat_id)
    pub = TestClient(app)
    assert hidden["slug"] not in [p["slug"] for p in pub.get("/api/plants?limit=100").json()]
    assert pub.get(f"/api/plants/{hidden['slug']}").status_code == 404
    assert pub.get(f"/api/plants/{hidden['slug']}/related").status_code == 404
    assert pub.get(f"/api/plants/{hidden['slug']}/reviews").status_code == 404
    assert pub.get(f"/api/plants/{visible['slug']}").status_code == 200
    related = [p["slug"] for p in pub.get(f"/api/plants/{visible['slug']}/related").json()]
    assert hidden["slug"] not in related
    assert hidden["slug"] not in pub.get("/sitemap.xml").text and visible["slug"] in pub.get("/sitemap.xml").text
    # once the admin makes it active it appears
    put = dict(hidden)
    put.update({"is_active": True})
    keys = ("name", "category_id", "description", "price", "discount_price", "sku", "image_url", "care_level", "features", "is_featured", "availability_status")
    body = {k: put.get(k) for k in keys} | {"is_active": True, "care_level": put.get("care_level") or "Easy", "description": put.get("description") or "", "sku": put.get("sku") or "", "image_url": put.get("image_url") or "", "features": put.get("features") or "", "availability_status": put.get("availability_status") or "AVAILABLE", "is_featured": bool(put.get("is_featured"))}
    assert c.put(f"{A}/plants/{hidden['id']}", json=body).status_code == 200
    assert pub.get(f"/api/plants/{hidden['slug']}").status_code == 200


def test_old_purchases_are_untouched():
    c = _admin()
    p = _plant(c)
    old = c.post(f"{A}/purchases", json={"purchase_date": datetime.utcnow().isoformat(), "supplier": "Old text supplier", "items": [{"plant_id": p["id"], "quantity": 4, "unit_cost": 2}]})  # no request_id: the old way
    assert old.status_code == 201
    row = [x for x in c.get(f"{A}/purchases").json() if x["id"] == old.json()["id"]][0]
    assert row["contact_id"] is None and row["supplier"] == "Old text supplier" and row["status"] == "Paid"


def test_blank_supplier_field_from_the_form_means_no_supplier():
    c = _admin()
    p = _plant(c)
    r = c.post(f"{A}/purchases", json={"purchase_date": datetime.utcnow().isoformat(), "supplier": "Local mandi", "supplier_contact_id": "", "items": [{"plant_id": p["id"], "quantity": 5, "unit_cost": 2}]})
    assert r.status_code == 201 and r.json()["contact_id"] is None and r.json()["supplier"] == "Local mandi"
