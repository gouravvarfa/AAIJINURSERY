"""Walk-in seed entries: save at once, update later, never double-add stock."""
import random
import uuid

from tests.test_production import A, S, _admin, _plant, _ready

E = f"{S}/seed-entries"


def _rid():
    return uuid.uuid4().hex


def _create(admin, plant, seeds, **extra):
    body = {"new_customer": {"name": f"Walkin {random.randint(100, 999)}", "phone": f"98{random.randint(10**7, 10**8 - 1)}"}, "plant_id": plant["id"], "seeds_given": seeds, "request_id": _rid()} | extra
    return admin.post(E, json=body)


def test_create_is_pending_and_not_ready_stock():
    admin = _admin()
    plant = _plant(admin, stock=0)
    seeds = random.randint(200, 900)
    r = _create(admin, plant, seeds, reference="SO-9", notes="walk-in")
    assert r.status_code == 201, r.text
    e = r.json()
    assert e["status"] == "Pending" and e["status_label"] == "Seeds Given / Production Pending"
    assert e["seeds_given"] == seeds and e["remaining"] == seeds and e["customer_name"]
    assert _ready(plant["id"]) == 0  # seeds are not plants
    listed = admin.get(E).json()
    assert any(i["id"] == e["id"] for i in listed["items"]) and listed["totals"]["seeds_given"] >= seeds


def test_double_click_creates_one_entry_and_same_phone_one_customer():
    admin = _admin()
    plant = _plant(admin)
    rid = _rid()
    body = {"new_customer": {"name": "Ramesh", "phone": "9811122233"}, "plant_id": plant["id"], "seeds_given": 50, "request_id": rid}
    a, b = admin.post(E, json=body), admin.post(E, json=body)
    assert a.json()["id"] == b.json()["id"] and b.json()["already_saved"] is True
    c = admin.post(E, json={**body, "new_customer": {"name": "Ramesh K", "phone": "+91 98111 22233"}, "request_id": _rid()})
    assert c.json()["contact_id"] == a.json()["contact_id"]


def test_validation():
    admin = _admin()
    plant = _plant(admin)
    assert _create(admin, plant, 0).status_code == 422
    assert _create(admin, plant, -5).status_code == 422
    assert admin.post(E, json={"plant_id": plant["id"], "seeds_given": 5, "request_id": _rid()}).status_code == 400  # no customer
    assert _create(admin, {"id": 99999999}, 5).status_code == 400
    tray = _plant(admin, tray=100)
    assert _create(admin, tray, 5).status_code == 400  # tray size missing


def test_update_flow_extra_plants_to_stock_once():
    admin = _admin()
    plant = _plant(admin, stock=0)
    seeds = 1000
    e = _create(admin, plant, seeds).json()
    prep, extra, bad = random.randint(300, 500), random.randint(50, 150), random.randint(10, 40)
    rid = _rid()
    body = {"prepared_plants": prep, "extra_plants": extra, "rejected_plants": bad, "request_id": rid}
    r = admin.post(f"{E}/{e['id']}/update", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "In Progress" and r.json()["remaining"] == seeds - prep - extra - bad
    assert _ready(plant["id"]) == extra
    again = admin.post(f"{E}/{e['id']}/update", json=body)  # retry: nothing added twice
    assert again.json()["already_saved"] is True and _ready(plant["id"]) == extra
    assert admin.get(f"{E}/{e['id']}").json()["extra_plants"] == extra
    # more than the seeds left is refused
    assert admin.post(f"{E}/{e['id']}/update", json={"prepared_plants": seeds, "request_id": _rid()}).status_code == 400
    assert _ready(plant["id"]) == extra
    # finish: the rest did not grow
    f = admin.post(f"{E}/{e['id']}/update", json={"finish": True, "request_id": _rid()}).json()
    assert f["status"] == "Completed" and f["remaining"] == 0
    assert admin.post(f"{E}/{e['id']}/update", json={"prepared_plants": 1, "request_id": _rid()}).status_code == 400
    assert not any(i["id"] == e["id"] for i in admin.get(E).json()["items"])
    assert any(i["id"] == e["id"] for i in admin.get(f"{E}?status=all").json()["items"])


def test_tray_plant_extra_in_whole_trays():
    admin = _admin()
    tray = _plant(admin, tray=125)
    vid = tray["variants"][0]["id"]
    e = _create(admin, tray, 2000, variant_id=vid).json()
    assert e["tray_size"] == 125
    admin.post(f"{E}/{e['id']}/update", json={"extra_plants": 300, "request_id": _rid()})  # 2 trays + 50 loose
    assert _ready(tray["id"], vid) == 2
    admin.post(f"{E}/{e['id']}/update", json={"extra_plants": 80, "request_id": _rid()})  # 380 -> 3 trays total
    assert _ready(tray["id"], vid) == 3


def test_requires_login():
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).get(E).status_code in (401, 403)
