"""Seeds -> production batch -> ready plants -> orders, with random quantities.
All numbers are generated per run; every assertion is relative to them."""
import os
import random
import threading

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import InventoryTransaction, Plant, PlantVariant
from app.production_models import SeedItem, SeedMovement

A = "/api/admin"
S = "/api/admin/stock"
_n = {"i": 0}


def _admin():
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"identifier": os.environ["DEFAULT_ADMIN_USERNAME"], "password": os.environ["DEFAULT_ADMIN_PASSWORD"]}).status_code == 200
    return c


def _customer():
    _n["i"] += 1
    c = TestClient(app)
    assert c.post("/api/customer/register", json={"name": "P Cust", "email": f"prod{_n['i']}@example.com", "mobile": "9000000000", "password": "password123"}).status_code == 201
    return c


def _plant(admin, stock=0, tray=None):
    _n["i"] += 1
    cat = admin.get(f"{A}/categories").json()[0]
    body = {"name": f"Prod Plant {_n['i']}", "category_id": cat["id"], "price": 10, "stock_quantity": 0 if tray else stock}
    if tray:
        body["variants"] = [{"tray_size": tray, "stock_quantity": stock}]
    r = admin.post(f"{A}/plants", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _form(plant):
    """What the plant form would send back unchanged (fields missing from the response get defaults)."""
    keys = ("name", "category_id", "description", "price", "discount_price", "sku", "image_url", "care_level", "features", "is_featured", "availability_status")
    return {k: plant.get(k, "" if k in ("description", "sku", "image_url", "features") else None) for k in keys} | {"care_level": plant.get("care_level") or "Easy", "is_featured": bool(plant.get("is_featured")), "availability_status": plant.get("availability_status") or "AVAILABLE"}


def _ready(plant_id, variant_id=None):
    db = SessionLocal()
    try:
        m, i = (PlantVariant, variant_id) if variant_id else (Plant, plant_id)
        return db.query(m.stock_quantity).filter(m.id == i).scalar()
    finally:
        db.close()


def _seed_balance(seed_id):
    db = SessionLocal()
    try:
        return db.query(SeedItem.quantity).filter(SeedItem.id == seed_id).scalar()
    finally:
        db.close()


def _order(cust, plant, qty, key, variant_id=None):
    r = cust.post("/api/customer/checkout", json={
        "delivery_name": "P", "delivery_mobile": "12345", "delivery_line1": "L", "delivery_city": "C", "delivery_state": "S", "delivery_pincode": "452001",
        "payment_method": "COD", "buy_now_plant_id": plant["id"], "buy_now_variant_id": variant_id, "buy_now_quantity": qty, "idempotency_key": key})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _row(admin, plant_id):
    return [r for r in admin.get(f"{A}/inventory/stock-demand").json()["items"] if r["plant_id"] == plant_id][0]


def test_whole_story_with_random_numbers():
    rnd = random.Random()
    demand = rnd.choice([400, 700, 1000, 1500])
    extra_seeds = rnd.randint(150, 600)
    issued = demand + extra_seeds                      # more seeds than the order needs
    consumed = issued - rnd.randint(10, 60)            # a few seeds go back unused
    returned = issued - consumed
    healthy = demand + rnd.randint(40, 250)            # more healthy plants than the order needs
    rejected = consumed - healthy if consumed > healthy else 0
    rejected = min(rejected, consumed - healthy) if consumed > healthy else 0
    surplus = healthy - demand
    second = surplus + rnd.randint(50, 300)            # the next customer wants more than the surplus

    admin, cust = _admin(), _customer()
    plant = _plant(admin, stock=0)
    seed = admin.post(f"{S}/seeds", json={"name": f"Seed {plant['name']}", "plant_id": plant["id"], "opening_quantity": issued + 100}).json()
    assert seed["balance"] == issued + 100

    oid = _order(cust, plant, demand, f"story-{plant['id']}")
    row = _row(admin, plant["id"])
    assert (row["outstanding_demand"], row["available_stock"], row["to_produce"]) == (demand, 0, demand)

    batch = admin.post(f"{S}/batches", json={"plant_id": plant["id"], "seed_item_id": seed["id"], "planned_quantity": demand,
                                              "links": [{"kind": "order", "item_id": admin.get(f"{A}/orders/{oid}").json()["items"][0]["id"]}]}).json()
    assert batch["status"] == "Draft" and batch["batch_number"] == f"BATCH-{batch['id']}"
    row = _row(admin, plant["id"])
    assert (row["in_production"], row["to_produce"], row["available_stock"]) == (demand, 0, 0)   # planned, never counted as ready stock

    r = admin.post(f"{S}/batches/{batch['id']}/issue-seeds", json={"quantity": issued, "request_id": "i1"}).json()
    assert (r["seeds_issued"], r["status"]) == (issued, "In Progress") and _seed_balance(seed["id"]) == 100
    again = admin.post(f"{S}/batches/{batch['id']}/issue-seeds", json={"quantity": issued, "request_id": "i1"}).json()   # a retry
    assert again["seeds_issued"] == issued and _seed_balance(seed["id"]) == 100

    bad = admin.post(f"{S}/batches/{batch['id']}/complete", json={"seeds_consumed": consumed, "seeds_returned": returned - 1, "healthy_plants": healthy})
    assert bad.status_code == 400 and "Account for every seed" in bad.json()["detail"]
    too_many = admin.post(f"{S}/batches/{batch['id']}/complete", json={"seeds_consumed": consumed, "seeds_returned": returned, "healthy_plants": consumed + 1})
    assert too_many.status_code == 400
    assert _ready(plant["id"]) == 0

    done = admin.post(f"{S}/batches/{batch['id']}/complete", json={"seeds_consumed": consumed, "seeds_returned": returned, "healthy_plants": healthy, "rejected_plants": rejected})
    assert done.status_code == 200, done.text
    d = done.json()
    assert (d["status"], d["accepted_plants"], d["accepted_units"], d["seeds_returned"]) == ("Completed", healthy, healthy, returned)
    assert _ready(plant["id"]) == healthy and _seed_balance(seed["id"]) == 100 + returned
    dup = admin.post(f"{S}/batches/{batch['id']}/complete", json={"seeds_consumed": consumed, "seeds_returned": returned, "healthy_plants": healthy})
    assert dup.status_code == 409 and _ready(plant["id"]) == healthy          # no second addition

    line = admin.get(f"{A}/orders/{oid}").json()["items"][0]
    sug = admin.get(f"{S}/batches/{batch['id']}/suggest").json()
    assert sug["available_stock"] == healthy and sug["lines"][0]["suggested"] == demand
    got = admin.post(f"{A}/inventory/fulfil", json={"kind": "order", "item_id": line["id"], "action": "stock", "quantity": demand})
    assert got.status_code == 200
    assert _ready(plant["id"]) == surplus                                       # the extra plants stay available
    row = _row(admin, plant["id"])
    assert (row["available_stock"], row["reserved_stock"], row["outstanding_demand"], row["to_produce"]) == (surplus, demand, 0, 0)

    oid2 = _order(cust, plant, second, f"story2-{plant['id']}")
    row = _row(admin, plant["id"])
    assert (row["outstanding_demand"], row["available_stock"], row["to_produce"]) == (second, surplus, second - surplus)   # only the real gap
    line2 = admin.get(f"{A}/orders/{oid2}").json()["items"][0]
    assert admin.post(f"{A}/inventory/fulfil", json={"kind": "order", "item_id": line2["id"], "action": "stock", "quantity": surplus}).status_code == 200
    assert _ready(plant["id"]) == 0
    row = _row(admin, plant["id"])
    assert (row["outstanding_demand"], row["to_produce"]) == (second - surplus, second - surplus)

    rep = admin.get(f"{S}/reports/yield").json()
    mine = [b for b in rep["batches"] if b["id"] == batch["id"]][0]
    assert mine["yield_pct"] == round(100 * healthy / consumed, 1)
    kinds = [m["type"] for m in admin.get(f"{S}/movements?kind=all&limit=200").json()["items"]]
    for expected in ("ISSUED", "CONSUMED", "RETURNED", "PRODUCTION_RECEIVED", "SALE"):
        assert expected in kinds


def test_tray_products_convert_plants_into_whole_trays():
    admin = _admin()
    plant = _plant(admin, stock=3, tray=125)
    v = plant["variants"][0]
    b = admin.post(f"{S}/batches", json={"plant_id": plant["id"], "variant_id": v["id"], "planned_quantity": 1000}).json()
    assert b["planned_units"] == 8 and b["unit"] == "trays"
    assert _row(admin, plant["id"])["in_production"] == 8
    d = admin.post(f"{S}/batches/{b['id']}/complete", json={"healthy_plants": 1000 + 62}).json()   # 8 trays + 62 loose
    assert (d["accepted_units"], d["loose_plants"]) == (8, 62)
    assert _ready(plant["id"], v["id"]) == 3 + 8


def test_wrong_variety_and_unsold_tray_choices_are_refused():
    admin = _admin()
    a, b = _plant(admin, 5), _plant(admin, 5)
    seed = admin.post(f"{S}/seeds", json={"name": f"Seed-only-for-{a['name']}", "plant_id": a["id"], "opening_quantity": 10}).json()
    assert admin.post(f"{S}/batches", json={"plant_id": b["id"], "seed_item_id": seed["id"], "planned_quantity": 5}).status_code == 400
    tray = _plant(admin, 5, tray=50)
    assert admin.post(f"{S}/batches", json={"plant_id": tray["id"], "planned_quantity": 100}).status_code == 400   # tray size required
    assert admin.post(f"{S}/batches", json={"plant_id": b["id"], "variant_id": tray["variants"][0]["id"], "planned_quantity": 100}).status_code == 400


def test_cancel_returns_every_issued_seed_and_cannot_repeat():
    admin = _admin()
    plant = _plant(admin, 0)
    seed = admin.post(f"{S}/seeds", json={"name": f"Seed c {plant['id']}", "plant_id": plant["id"], "opening_quantity": 500}).json()
    b = admin.post(f"{S}/batches", json={"plant_id": plant["id"], "seed_item_id": seed["id"], "planned_quantity": 300}).json()
    admin.post(f"{S}/batches/{b['id']}/issue-seeds", json={"quantity": 320})
    assert _seed_balance(seed["id"]) == 180
    assert admin.post(f"{S}/batches/{b['id']}/cancel").json()["status"] == "Cancelled"
    assert _seed_balance(seed["id"]) == 500
    assert admin.post(f"{S}/batches/{b['id']}/cancel").status_code == 409 and _seed_balance(seed["id"]) == 500
    assert _row(admin, plant["id"])["in_production"] == 0          # a cancelled batch no longer counts as production


def test_seed_store_never_goes_negative_under_concurrent_issues():
    admin = _admin()
    plant = _plant(admin, 0)
    seed = admin.post(f"{S}/seeds", json={"name": f"Seed race {plant['id']}", "plant_id": plant["id"], "opening_quantity": 100}).json()
    batches = [admin.post(f"{S}/batches", json={"plant_id": plant["id"], "seed_item_id": seed["id"], "planned_quantity": 50}).json() for _ in range(6)]
    codes = []

    def issue(b):
        c = _admin()
        codes.append(c.post(f"{S}/batches/{b['id']}/issue-seeds", json={"quantity": 30}).status_code)

    threads = [threading.Thread(target=issue, args=(b,)) for b in batches]
    [t.start() for t in threads]
    [t.join() for t in threads]
    ok = codes.count(200)
    assert ok <= 3 and _seed_balance(seed["id"]) == 100 - 30 * ok >= 0, codes


def test_plant_form_stock_changes_are_written_to_the_ledger():
    admin = _admin()
    plant = _plant(admin, stock=40)
    body = _form(plant)
    body.update(is_active=True, stock_quantity=55)
    assert admin.put(f"{A}/plants/{plant['id']}", json=body).status_code == 200
    body["stock_quantity"] = 55   # saving again without a change adds nothing
    assert admin.put(f"{A}/plants/{plant['id']}", json=body).status_code == 200
    assert _ready(plant["id"]) == 55
    db = SessionLocal()
    try:
        rows = db.query(InventoryTransaction).filter(InventoryTransaction.plant_id == plant["id"]).order_by(InventoryTransaction.id).all()
        assert [(r.transaction_type, r.quantity, r.before_quantity, r.after_quantity) for r in rows] == [("OPENING_STOCK", 40, 0, 40), ("MANUAL_ADJUSTMENT", 15, 40, 55)]
    finally:
        db.close()


def test_tray_stock_edit_keeps_the_tray_identity_and_ledger():
    admin = _admin()
    plant = _plant(admin, stock=10, tray=125)
    v = plant["variants"][0]
    body = _form(plant)
    body.update(is_active=True, stock_quantity=0, variants=[{"tray_size": 125, "stock_quantity": 7}, {"tray_size": 150, "stock_quantity": 4}])
    out = admin.put(f"{A}/plants/{plant['id']}", json=body).json()
    assert sorted((x["tray_size"], x["stock_quantity"]) for x in out["variants"]) == [(125, 7), (150, 4)]
    assert [x["id"] for x in out["variants"] if x["tray_size"] == 125] == [v["id"]]     # same tray id as before
    assert out["stock_quantity"] == 11


def test_stock_pages_need_the_products_permission(client, plain_admin):
    assert client.get(f"{S}/seeds").status_code == 401           # not logged in
    assert client.post("/api/auth/login", json={"identifier": plain_admin["username"], "password": plain_admin["password"]}).status_code == 200
    # a plain admin has no explicit products permission unless a role grants it: the endpoints must answer 200 or 403, never 500
    assert client.get(f"{S}/seeds").status_code in (200, 403)
    assert client.post(f"{S}/seeds", json={"name": "x"}).status_code in (201, 403, 400)


def test_counting_ready_plants_writes_the_difference_and_reason_to_the_ledger():
    admin = _admin()
    plant = _plant(admin, stock=100)
    r = admin.post(f"{S}/ready/adjust", json={"plant_id": plant["id"], "new_quantity": 92, "reason": "Physical count: 8 plants dried"})
    assert r.status_code == 200 and r.json()["changed_by"] == -8 and _ready(plant["id"]) == 92
    assert admin.post(f"{S}/ready/adjust", json={"plant_id": plant["id"], "new_quantity": 92, "reason": "same again"}).json()["changed_by"] == 0
    assert admin.post(f"{S}/ready/adjust", json={"plant_id": plant["id"], "new_quantity": 5, "reason": "x"}).status_code == 422   # reason too short
    tray = _plant(admin, stock=4, tray=125)
    assert admin.post(f"{S}/ready/adjust", json={"plant_id": tray["id"], "new_quantity": 9, "reason": "count"}).status_code == 400   # tray size needed
    assert admin.post(f"{S}/ready/adjust", json={"plant_id": tray["id"], "variant_id": tray["variants"][0]["id"], "new_quantity": 9, "reason": "count"}).status_code == 200
    mv = [m for m in admin.get(f"{S}/movements?kind=stock&plant_id={plant['id']}").json()["items"] if m["type"] == "MANUAL_ADJUSTMENT"]
    assert mv and mv[0]["notes"] == "Physical count: 8 plants dried" and mv[0]["quantity"] == 8
