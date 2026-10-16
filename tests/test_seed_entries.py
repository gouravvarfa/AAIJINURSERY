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


def test_history_groups_by_customer_with_log():
    admin = _admin()
    plant = _plant(admin)
    c = admin.post(E, json={"new_customer": {"name": "Hist Cust", "phone": "9877700011"}, "plant_id": plant["id"], "seeds_given": 300, "request_id": _rid()}).json()
    admin.post(E, json={"contact_id": c["contact_id"], "plant_id": plant["id"], "seeds_given": 100, "request_id": _rid()})
    admin.post(f"{E}/{c['id']}/update", json={"prepared_plants": 200, "extra_plants": 30, "rejected_plants": 20, "request_id": _rid()})
    g = [x for x in admin.get(f"{E}/history").json()["customers"] if x["contact_id"] == c["contact_id"]][0]
    assert len(g["entries"]) == 2 and g["seeds"] == 400 and g["good"] == 200 and g["extra"] == 30 and g["rejected"] == 20 and g["remaining"] == 150
    assert any(len(e["log"]) == 1 for e in g["entries"])


def test_edit_entry_and_update_keep_stock_in_step():
    admin = _admin()
    plant = _plant(admin, stock=0)
    e = _create(admin, plant, 500).json()
    admin.post(f"{E}/{e['id']}/update", json={"prepared_plants": 100, "extra_plants": 50, "rejected_plants": 10, "request_id": _rid()})
    assert _ready(plant["id"]) == 50
    log = admin.get(f"{E}/{e['id']}").json()["updates"][0]
    # correct the line: extra 50 -> 80
    r = admin.put(f"{E}/{e['id']}/updates/{log['id']}", json={"prepared_plants": 100, "extra_plants": 80, "rejected_plants": 10})
    assert r.status_code == 200 and r.json()["extra_plants"] == 80 and _ready(plant["id"]) == 80
    # too many plants for the seeds is refused and nothing changes
    assert admin.put(f"{E}/{e['id']}/updates/{log['id']}", json={"prepared_plants": 900, "extra_plants": 80, "rejected_plants": 10}).status_code == 400
    assert _ready(plant["id"]) == 80
    # seeds cannot go below what is recorded; edit date/notes/seeds
    assert admin.put(f"{E}/{e['id']}", json={"seeds_given": 150}).status_code == 400
    ok = admin.put(f"{E}/{e['id']}", json={"seeds_given": 400, "reference": "R1", "notes": "n", "entry_date": "2026-01-05"})
    assert ok.status_code == 200 and ok.json()["seeds_given"] == 400 and ok.json()["entry_date"] == "2026-01-05"
    # plant cannot change once plants were recorded
    other = _plant(admin)
    assert admin.put(f"{E}/{e['id']}", json={"plant_id": other["id"]}).status_code == 400
    # entry cannot be deleted with updates; removing the update takes the extra plants back
    assert admin.delete(f"{E}/{e['id']}").status_code == 400
    d = admin.delete(f"{E}/{e['id']}/updates/{log['id']}")
    assert d.status_code == 200 and d.json()["status"] == "Pending" and _ready(plant["id"]) == 0
    assert admin.delete(f"{E}/{e['id']}").status_code == 200
    assert admin.get(f"{E}/{e['id']}").status_code == 404


def test_cannot_take_back_extra_plants_already_used():
    admin = _admin()
    plant = _plant(admin, stock=0)
    e = _create(admin, plant, 100).json()
    admin.post(f"{E}/{e['id']}/update", json={"extra_plants": 40, "request_id": _rid()})
    admin.post(f"{S}/ready/adjust", json={"plant_id": plant["id"], "new_quantity": 5, "reason": "sold some"})
    log = admin.get(f"{E}/{e['id']}").json()["updates"][0]
    assert admin.delete(f"{E}/{e['id']}/updates/{log['id']}").status_code == 400
    assert _ready(plant["id"]) == 5
