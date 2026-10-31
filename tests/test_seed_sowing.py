"""Sowing Entry: stock comes in when the goods are received (not when the PO is made) and goes out when seed is sown."""
import uuid
from datetime import date

from tests.test_seed_packets import P, _admin
from tests.test_supply_bills import _batches, _bill, _line, _po, _supplier

SOW = "/api/admin/stock/seed-sowings"


def _received_lot(c, qty=10, lot=None):
    lot = lot or f"SW-{uuid.uuid4().hex[:6]}"
    sup = _supplier(c)
    po = _po(c, sup, [_line("seed_packet", description="Hybrid Tomato 1057", company="Seminis", lot_number=lot, quantity=qty, unit_price=50)]).json()
    return po, lot, sup


def _sow(c, batch_id, used, trays=2, **kw):
    body = {"batch_id": batch_id, "sowing_date": date.today().isoformat(), "packets_used": used, "trays_sown": trays, "nursery_batch_number": "NB-1", "request_id": uuid.uuid4().hex} | kw
    return c.post(SOW, json=body)


def test_stock_only_after_receipt_then_sowing_reduces_it_with_partial_packets():
    c = _admin()
    po, lot, _ = _received_lot(c, 10)
    assert _batches(c, batch=lot) == []  # a Purchase Order alone adds no stock
    assert _bill(c, po["id"]).status_code == 200  # receipt confirmed
    b = _batches(c, batch=lot)[0]
    assert b["remaining"] == 10
    r = _sow(c, b["id"], 3, trays=6, nursery_batch_number="NB-77")
    assert r.status_code == 201, r.text
    assert r.json()["remaining_after"] == 7 and r.json()["trays_sown"] == 6
    assert _batches(c, batch=lot)[0]["remaining"] == 7
    r = _sow(c, b["id"], 0.5)
    assert r.status_code == 201 and r.json()["remaining_after"] == 6.5
    assert _batches(c, batch=lot)[0]["remaining"] == 6.5
    hist = [h for h in c.get(f"{P}/history?batch_id={b['id']}").json()]
    assert [h["type"] for h in reversed(hist)] == ["RECEIPT", "USAGE", "USAGE"]
    assert [h["balance_after"] for h in reversed(hist)] == [10, 7, 6.5]


def test_cannot_sow_more_than_in_stock_and_retry_is_not_double():
    c = _admin()
    po, lot, _ = _received_lot(c, 4)
    _bill(c, po["id"])
    b = _batches(c, batch=lot)[0]
    assert _sow(c, b["id"], 5).status_code == 400
    rid = uuid.uuid4().hex
    assert _sow(c, b["id"], 1, request_id=rid).status_code == 201
    assert _sow(c, b["id"], 1, request_id=rid).json()["already_saved"] is True
    assert _batches(c, batch=lot)[0]["remaining"] == 3
    assert _sow(c, b["id"], 1, trays=0).status_code == 422
    assert _sow(c, b["id"], 1, sowing_date="2999-01-01").status_code == 400
    rows = c.get(f"{SOW}?q={lot}").json()
    assert len(rows) == 1 and rows[0]["lot_number"] == lot and rows[0]["remaining_after"] == 3


def test_only_seed_lots_can_be_sown():
    c = _admin()
    sup = _supplier(c)
    po = _po(c, sup, [_line("fertilizer", description="Urea", unit="kg", quantity=5, unit_price=10)]).json()
    _bill(c, po["id"])
    fert = [x for x in c.get(f"{P}?kind=fertilizer&show_empty=true").json()["items"] if x["item_name"] == "Urea"][0]
    assert _sow(c, fert["id"], 1).status_code == 404


def test_plant_selling_price_on_po_sets_plant_price_but_packet_cost_never_does():
    from tests.test_seed_packets import _plant

    c = _admin()
    plant = _plant(c, stock=0)
    before = c.get("/api/admin/plants").json()
    price0 = [x for x in before if x["id"] == plant["id"]][0]["price"]
    sup = _supplier(c)
    lot = f"PR-{uuid.uuid4().hex[:6]}"
    line = _line("seed_packet", plant_id=plant["id"], description="Chilli seed", company="Co", lot_number=lot, quantity=5, unit_price=16400)
    po = _po(c, sup, [line]).json()
    assert _bill(c, po["id"]).status_code == 200
    now = [x for x in c.get("/api/admin/plants").json() if x["id"] == plant["id"]][0]["price"]
    assert now == price0  # a 16,400 packet cost never becomes the plant price
    line2 = _line("seed_packet", plant_id=plant["id"], description="Chilli seed", company="Co", lot_number=lot + "B", quantity=5, unit_price=16400, plant_sell_price=2.5)
    po2 = _po(c, sup, [line2]).json()
    assert po2["items"][0]["plant_sell_price"] == 2.5
    assert _bill(c, po2["id"]).status_code == 200
    now = [x for x in c.get("/api/admin/plants").json() if x["id"] == plant["id"]][0]["price"]
    assert now == 2.5
    bad = _line("medicine", description="Neem", lot_number="N1", quantity=1, unit_price=5, plant_sell_price=3)
    assert _po(c, sup, [bad]).status_code == 400
