"""Orders are never limited by stock. Stock only moves when the admin gives a
line from stock; the rest stays pending / "to prepare"."""
import os
import threading

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.inventory import MAX_ORDER_QUANTITY, allocate_stock
from app.main import app
from app.models import InventoryTransaction, OrderItem, Plant, PlantVariant

A = "/api/admin"
_n = {"i": 0}


def _admin():
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"identifier": os.environ["DEFAULT_ADMIN_USERNAME"], "password": os.environ["DEFAULT_ADMIN_PASSWORD"]})
    assert r.status_code == 200
    return c


def _customer():
    _n["i"] += 1
    c = TestClient(app)
    r = c.post("/api/customer/register", json={"name": "Stock Cust", "email": f"stock{_n['i']}@example.com", "mobile": "9000000000", "password": "password123"})
    assert r.status_code == 201, r.text
    return c


def _plant(admin, stock, tray=False):
    _n["i"] += 1
    cat = admin.get(f"{A}/categories").json()[0]
    body = {"name": f"Stock Plant {_n['i']}", "category_id": cat["id"], "price": 10, "stock_quantity": 0 if tray else stock}
    if tray:
        body["variants"] = [{"tray_size": 50, "stock_quantity": stock}]
    r = admin.post(f"{A}/plants", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _stock(plant_id, variant_id=None):
    db = SessionLocal()
    try:
        model, ident = (PlantVariant, variant_id) if variant_id else (Plant, plant_id)
        return db.query(model.stock_quantity).filter(model.id == ident).scalar()
    finally:
        db.close()


def _buy(cust, plant, qty, key, variant_id=None):
    return cust.post("/api/customer/checkout", json={
        "delivery_name": "S", "delivery_mobile": "9000000000", "delivery_line1": "L", "delivery_city": "C", "delivery_state": "S",
        "delivery_pincode": "452001", "payment_method": "COD", "buy_now_plant_id": plant["id"], "buy_now_variant_id": variant_id,
        "buy_now_quantity": qty, "idempotency_key": key})


@pytest.mark.parametrize("stock,qty", [(1000, 400), (1000, 1000), (1000, 5000), (0, 300)])
def test_order_keeps_full_quantity_and_stock_is_untouched(stock, qty):
    admin, cust = _admin(), _customer()
    plant = _plant(admin, stock)
    r = _buy(cust, plant, qty, f"k-{plant['id']}")
    assert r.status_code == 201, r.text
    item = r.json()["items"][0]
    assert (item["quantity"], item["allocated"], item["pending"]) == (qty, 0, qty)
    assert _stock(plant["id"]) == stock  # nothing is taken automatically


def test_invalid_quantities_refused_but_large_bulk_allowed():
    admin, cust = _admin(), _customer()
    plant = _plant(admin, 5)
    assert _buy(cust, plant, 0, "z0").status_code == 400
    assert _buy(cust, plant, -3, "zn").status_code == 400
    assert _buy(cust, plant, MAX_ORDER_QUANTITY + 1, "zbig").status_code == 400
    assert _buy(cust, plant, MAX_ORDER_QUANTITY, "zmax").status_code == 201
    assert cust.post("/api/customer/cart", json={"plant_id": plant["id"], "quantity": 100000}).status_code == 201


def test_admin_gives_from_stock_prepares_and_cancel_restores_only_what_was_given():
    admin, cust = _admin(), _customer()
    plant = _plant(admin, 1000)
    oid = _buy(cust, plant, 5000, "ak1").json()["id"]
    line = admin.get(f"{A}/orders/{oid}").json()["items"][0]

    too_much = admin.post(f"{A}/inventory/fulfil", json={"kind": "order", "item_id": line["id"], "action": "stock", "quantity": 1500})
    assert too_much.status_code == 400 and "in stock" in too_much.json()["detail"]
    assert _stock(plant["id"]) == 1000

    ok = admin.post(f"{A}/inventory/fulfil", json={"kind": "order", "item_id": line["id"], "action": "stock", "quantity": 700}).json()
    assert (ok["allocated"], ok["pending"]) == (700, 4300) and _stock(plant["id"]) == 300
    assert admin.post(f"{A}/inventory/fulfil", json={"kind": "order", "item_id": line["id"], "action": "prepare"}).json()["to_prepare"] is True
    assert admin.post(f"{A}/inventory/fulfil", json={"kind": "order", "item_id": line["id"], "action": "clear"}).json()["to_prepare"] is False

    row = [r for r in admin.get(f"{A}/inventory/stock-demand").json()["items"] if r["plant_id"] == plant["id"]][0]
    assert (row["available_stock"], row["reserved_stock"], row["physical_stock"], row["outstanding_demand"], row["shortage"]) == (300, 700, 1000, 4300, 4000)

    assert admin.post(f"{A}/orders/{oid}/cancel", json={"remarks": "t"}).status_code == 200
    assert _stock(plant["id"]) == 1000  # only the 700 that was given comes back
    db = SessionLocal()
    try:
        rows = db.query(InventoryTransaction).filter(InventoryTransaction.plant_id == plant["id"]).all()
        assert sorted(r.transaction_type for r in rows) == ["OPENING_STOCK", "SALE", "SALE_REVERSAL"]  # opening + give + restore
    finally:
        db.close()
    closed = admin.post(f"{A}/inventory/fulfil", json={"kind": "order", "item_id": line["id"], "action": "stock"})
    assert closed.status_code == 400


def test_cancel_with_nothing_given_does_not_touch_stock():
    admin, cust = _admin(), _customer()
    plant = _plant(admin, 100)
    oid = _buy(cust, plant, 900, "ak2").json()["id"]
    assert cust.post(f"/api/customer/orders/{oid}/cancel", json={"remarks": "t"}).status_code == 200
    assert _stock(plant["id"]) == 100


def test_tray_product_uses_tray_stock_and_tray_quantity():
    admin, cust = _admin(), _customer()
    plant = _plant(admin, 20, tray=True)
    v = plant["variants"][0]
    r = _buy(cust, plant, 50, "tray1", variant_id=v["id"])
    assert r.status_code == 201
    item = r.json()["items"][0]
    assert (item["quantity"], item["tray_size"], item["unit_price"], item["line_total"]) == (50, 50, v["price"], 50 * v["price"])
    line = admin.get(f"{A}/orders/{r.json()['id']}").json()["items"][0]
    admin.post(f"{A}/inventory/fulfil", json={"kind": "order", "item_id": line["id"], "action": "stock", "quantity": 20})
    assert _stock(plant["id"], v["id"]) == 0


def test_sales_order_above_stock_invoice_takes_available_only_and_void_restores():
    admin = _admin()
    plant = _plant(admin, 10)
    contact = admin.post(f"{A}/accounting/contacts", json={"name": "Stock Party", "phone": ""}).json()

    def make(to_prepare):
        return admin.post(f"{A}/accounting/sales-orders", json={
            "contact_id": contact["id"], "order_date": "2026-10-13T00:00:00",
            "items": [{"plant_id": plant["id"], "description": "x", "quantity": 25, "unit_price": 10, "to_prepare": to_prepare}]})

    so = make(False)
    assert so.status_code == 201
    sid = so.json()["id"]
    detail = admin.get(f"{A}/accounting/sales-orders/{sid}").json()["items"][0]
    assert (detail["quantity"], detail["allocated"], detail["pending"], detail["available_stock"]) == (25, 0, 25, 10)
    inv = admin.post(f"{A}/accounting/sales-orders/{sid}/convert-to-invoice", json={})
    assert inv.status_code == 200, inv.text
    line = admin.get(f"{A}/accounting/sales-orders/{sid}").json()["items"][0]
    assert (line["allocated"], line["pending"]) == (10, 15) and _stock(plant["id"]) == 0
    assert admin.post(f"{A}/accounting/invoices/{inv.json()['id']}/void", json={}).status_code == 200
    assert _stock(plant["id"]) == 10

    so2 = make(True)  # admin chose "prepare": invoicing takes nothing from stock
    admin.post(f"{A}/accounting/sales-orders/{so2.json()['id']}/convert-to-invoice", json={})
    assert _stock(plant["id"]) == 10


def test_online_order_demand_is_not_double_counted_with_its_sales_order():
    admin, cust = _admin(), _customer()
    plant = _plant(admin, 50)
    _buy(cust, plant, 80, "dc1")
    row = [r for r in admin.get(f"{A}/inventory/stock-demand").json()["items"] if r["plant_id"] == plant["id"]][0]
    assert row["outstanding_demand"] == 80  # once, not twice


def test_concurrent_gives_never_take_more_than_stock():
    admin = _admin()
    plant = _plant(admin, 100)
    taken, errors = [], []

    def worker(i):
        db = SessionLocal()
        try:
            taken.append(allocate_stock(db, plant_id=plant["id"], quantity=30, source_type="TEST", source_id=i, reference=f"CONC:{plant['id']}:{i}", created_by="t"))
            db.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
            db.rollback()
        finally:
            db.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(taken) <= 100, (taken, errors)
    assert _stock(plant["id"]) == 100 - sum(taken) and _stock(plant["id"]) >= 0


def test_allocate_is_idempotent_for_a_retry():
    admin = _admin()
    plant = _plant(admin, 40)
    db = SessionLocal()
    try:
        a = allocate_stock(db, plant_id=plant["id"], quantity=15, source_type="TEST", source_id=1, reference=f"RETRY:{plant['id']}", created_by="t")
        db.commit()
        b = allocate_stock(db, plant_id=plant["id"], quantity=15, source_type="TEST", source_id=1, reference=f"RETRY:{plant['id']}", created_by="t")
        db.commit()
    finally:
        db.close()
    assert (a, b) == (15, 15) and _stock(plant["id"]) == 25


def test_legacy_rows_without_allocation_count_as_fully_allocated():
    item = OrderItem(quantity=12, allocated_quantity=None)
    assert (item.allocated, item.pending) == (12, 0)
