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


def _row(admin, plant, variant_id=None):
    return [r for r in admin.get("/api/admin/inventory/stock-demand").json()["items"] if r["plant_id"] == plant["id"] and (r["variant_id"] or None) == variant_id][0]


def test_good_plants_for_a_customer_show_in_stock_as_allocated_not_for_sale():
    admin = _admin()
    plant = _plant(admin, stock=50)
    e = _create(admin, plant, 1000).json()
    assert _row(admin, plant)["customer_held"] == 0
    admin.post(f"{E}/{e['id']}/update", json={"prepared_plants": 600, "extra_plants": 40, "rejected_plants": 10, "request_id": _rid()})
    r = _row(admin, plant)
    assert r["customer_held"] == 600 and r["available_stock"] == 50 + 40  # extra is for sale, the customer's plants are not
    assert r["physical_stock"] == 50 + 40 + 600  # but they are in the nursery, so the stock picture counts them
    # a correction to the update moves the held number with it
    log = admin.get(f"{E}/{e['id']}").json()["updates"][0]
    admin.put(f"{E}/{e['id']}/updates/{log['id']}", json={"prepared_plants": 650, "extra_plants": 40, "rejected_plants": 10})
    assert _row(admin, plant)["customer_held"] == 650
    # handed over (closed): they leave the stock picture, nothing is added to Ready now
    admin.post(f"{E}/{e['id']}/update", json={"finish": True, "request_id": _rid()})
    r = _row(admin, plant)
    assert r["customer_held"] == 0 and r["available_stock"] == 90 and r["physical_stock"] == 90


def test_tray_plants_held_in_whole_trays_and_two_customers_add_up():
    admin = _admin()
    tray = _plant(admin, tray=125)
    vid = tray["variants"][0]["id"]
    a = _create(admin, tray, 2000, variant_id=vid).json()
    b = _create(admin, tray, 1000, variant_id=vid).json()
    admin.post(f"{E}/{a['id']}/update", json={"prepared_plants": 1000, "request_id": _rid()})  # 8 trays
    admin.post(f"{E}/{b['id']}/update", json={"prepared_plants": 300, "request_id": _rid()})  # 2 trays (+50 loose)
    r = _row(admin, tray, vid)
    assert r["customer_held"] == 10 and r["unit"] == "trays" and r["available_stock"] == 0


def test_customer_wants_500_gave_600_seeds_650_good_come_out():
    """The shop's real case: only 'how many good' is written; 500 stay for the customer, 150 go to Ready now."""
    admin = _admin()
    plant = _plant(admin, stock=20)
    e = _create(admin, plant, 600, wanted_plants=500).json()
    assert e["wanted_plants"] == 500 and e["customer_pending"] == 500
    # more plants than seeds is refused unless the seeds are raised on purpose
    r = admin.post(f"{E}/{e['id']}/update", json={"good_plants": 650, "request_id": _rid()})
    assert r.status_code == 400 and "more plants than seeds" in r.text
    ok = admin.post(f"{E}/{e['id']}/update", json={"good_plants": 650, "raise_seeds": True, "request_id": _rid()})
    assert ok.status_code == 200, ok.text
    j = ok.json()
    assert (j["prepared_plants"], j["extra_plants"], j["seeds_given"], j["remaining"], j["customer_pending"]) == (500, 150, 650, 0, 0)
    row = _row(admin, plant)
    assert row["available_stock"] == 20 + 150 and row["customer_held"] == 500 and row["physical_stock"] == 20 + 150 + 500
    # all seeds are accounted for (entry shows Completed) but the plants are still in the nursery until they are handed over
    assert j["status"] == "Completed" and j["handed_over"] is False
    assert any("raised from 600 to 650" in (u["notes"] or "") for u in admin.get(f"{E}/{e['id']}").json()["updates"])
    h = admin.post(f"{E}/{e['id']}/handover", json={"request_id": _rid()})
    assert h.status_code == 200 and h.json()["handed_over"] is True
    again = admin.post(f"{E}/{e['id']}/handover", json={"request_id": _rid()})
    assert again.json()["already_saved"] is True
    row = _row(admin, plant)
    assert row["customer_held"] == 0 and row["available_stock"] == 170 and row["physical_stock"] == 170


def test_good_plants_fill_the_customers_share_first_over_several_updates():
    admin = _admin()
    plant = _plant(admin, stock=0)
    e = _create(admin, plant, 900, wanted_plants=500).json()
    a = admin.post(f"{E}/{e['id']}/update", json={"good_plants": 400, "rejected_plants": 20, "request_id": _rid()}).json()
    assert (a["prepared_plants"], a["extra_plants"], a["customer_pending"]) == (400, 0, 100)
    b = admin.post(f"{E}/{e['id']}/update", json={"good_plants": 150, "request_id": _rid()}).json()
    assert (b["prepared_plants"], b["extra_plants"], b["customer_pending"], b["status"]) == (500, 50, 0, "In Progress")
    r = _row(admin, plant)
    assert r["available_stock"] == 50 and r["customer_held"] == 500
    # the same click twice adds once
    rid = _rid()
    admin.post(f"{E}/{e['id']}/update", json={"good_plants": 10, "request_id": rid})
    admin.post(f"{E}/{e['id']}/update", json={"good_plants": 10, "request_id": rid})
    assert _row(admin, plant)["available_stock"] == 60


def test_wanted_can_be_set_with_the_first_update_and_is_needed_for_good_plants():
    admin = _admin()
    plant = _plant(admin)
    e = _create(admin, plant, 300).json()
    assert admin.post(f"{E}/{e['id']}/update", json={"good_plants": 100, "request_id": _rid()}).status_code == 400  # nobody said how many the customer wants
    ok = admin.post(f"{E}/{e['id']}/update", json={"good_plants": 100, "wanted_plants": 80, "request_id": _rid()})
    assert ok.status_code == 200 and (ok.json()["prepared_plants"], ok.json()["extra_plants"]) == (80, 20)
    assert admin.post(f"{E}/{e['id']}/update", json={"good_plants": 5, "prepared_plants": 5, "request_id": _rid()}).status_code == 400  # not both ways at once


def test_old_completed_entries_stay_handed_over_not_suddenly_held():
    admin = _admin()
    plant = _plant(admin, stock=5)
    e = _create(admin, plant, 100).json()
    admin.post(f"{E}/{e['id']}/update", json={"prepared_plants": 60, "finish": True, "request_id": _rid()})  # the older way of closing
    j = admin.get(f"{E}/{e['id']}").json()
    assert j["handed_over"] is True and _row(admin, plant)["customer_held"] == 0
