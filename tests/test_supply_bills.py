"""Supplier bills for seed packets / medicines / fertilizers / supplies: Purchase Order lines, lots, expiry, decimals,
duplicate bill numbers, supplier payable, plant history. Plant stock must never move."""
import uuid
from datetime import date, datetime, timedelta

from app.accounting.models import Expense
from app.database import SessionLocal
from app.models import InventoryTransaction, Plant
from tests.test_seed_packets import A, P, _admin, _plant

ADMIN = "/api/admin"
PO = "/api/admin/accounting/purchase-orders"
ACC = "/api/admin/accounting"


def _stock(plant_id):
    db = SessionLocal()
    try:
        return db.query(Plant.stock_quantity).filter(Plant.id == plant_id).scalar()
    finally:
        db.close()


def _supplier(c, name=None):
    r = c.post(f"{ACC}/contacts", json={"name": name or f"Sup {uuid.uuid4().hex[:6]}", "contact_type": "supplier", "phone": "9000011111"})
    assert r.status_code == 201, r.text
    return r.json()


def _line(kind="seed_packet", **kw):
    base = {"item_kind": kind, "description": f"Item {uuid.uuid4().hex[:4]}", "company": "BrandCo", "lot_number": f"LOT-{uuid.uuid4().hex[:5]}", "quantity": 10, "unit": "", "unit_price": 20,
            "expiry_date": (date.today() + timedelta(days=300)).isoformat()}
    return base | kw


def _po(c, sup, lines, **kw):
    r = c.post(PO, json={"contact_id": sup["id"], "order_date": datetime.utcnow().isoformat(), "items": lines} | kw)
    return r


def _bill(c, po_id, **kw):
    return c.post(f"{PO}/{po_id}/convert-to-bill", json=kw)


def _batches(c, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return c.get(f"{P}?{qs}&show_empty=true").json()["items"]


# ------------------------------------------------------------------ purchase order lines
def test_plants_cannot_be_added_to_a_purchase_order_any_more():
    c = _admin()
    plant = _plant(c)
    r = _po(c, _supplier(c), [{"item_kind": "plant", "plant_id": plant["id"], "quantity": 5, "unit_price": 3}])
    assert r.status_code == 400 and "plants are not bought" in r.text


def test_line_rules_lot_expiry_units_and_decimals():
    c = _admin()
    sup = _supplier(c)
    bad = lambda **kw: _po(c, sup, [_line(**kw)]).status_code
    assert bad(item_kind="seed_packet", lot_number="") == 400  # lot required for seed packets
    assert bad(item_kind="medicine", lot_number="") == 400 and bad(item_kind="medicine", expiry_date=None) == 400  # and for medicines
    assert bad(item_kind="seed_packet", expiry_date=None) == 400
    assert bad(item_kind="fertilizer", lot_number="", expiry_date=None, unit="bags") == 201  # optional for fertilizers
    assert bad(item_kind="supply", lot_number="", expiry_date=None, unit="pcs") == 201  # and other supplies
    assert bad(item_kind="medicine", unit="bottles", quantity=2.5) == 400  # whole units are whole numbers
    assert bad(item_kind="medicine", unit="litre", quantity=2.5) == 201  # litres can be decimal
    assert bad(item_kind="fertilizer", unit="kg", quantity=0.25, lot_number="", expiry_date=None) == 201
    assert bad(quantity=0) == 400 and bad(quantity=-1) == 400
    assert bad(item_kind="medicine", plant_id=None, description="") == 400  # an item needs a name
    plant = _plant(c)
    assert bad(item_kind="medicine", plant_id=plant["id"], unit="litre") == 400  # only seed packets link to a plant
    assert bad(item_kind="seed_packet", plant_id=99999999) == 400
    assert bad(item_kind="seed_packet", expiry_date=(date.today() - timedelta(days=2)).isoformat()) == 400  # already expired before it was bought


def test_purchase_order_with_mixed_lines_totals_decimals_exactly():
    c = _admin()
    sup = _supplier(c)
    r = _po(c, sup, [_line("seed_packet", quantity=12, unit_price=8.5), _line("medicine", unit="litre", quantity=2.5, unit_price=410), _line("fertilizer", unit="kg", quantity=12.75, unit_price=18.4, lot_number="", expiry_date=None)])
    assert r.status_code == 201, r.text
    po = r.json()
    assert [i["line_total"] for i in po["items"]] == [102.0, 1025.0, 234.6] and po["total_amount"] == 1361.6
    assert [i["quantity"] for i in po["items"]] == [12, 2.5, 12.75]


# ------------------------------------------------------------------ converting to a bill = receiving into lot batches
def test_convert_creates_one_unpaid_bill_with_lines_and_lots_and_no_plant_stock():
    c = _admin()
    sup = _supplier(c)
    plant = _plant(c, stock=25)
    seed = _line("seed_packet", plant_id=plant["id"], description="Tomato Hybrid", lot_number="TH-1", quantity=30, unit_price=10)
    med = _line("medicine", description="Neem oil", lot_number="NM-7", unit="litre", quantity=2.5, unit_price=400)
    po = _po(c, sup, [seed, med]).json()
    r = _bill(c, po["id"], supplier_bill_number="SUP-501")
    assert r.status_code == 200, r.text
    bill = r.json()
    assert bill["status"] == "Unpaid" and bill["invoice_number"] == "SUP-501" and bill["total_cost"] == 1300 and bill["balance_due"] == 1300 and bill["contact_id"] == sup["id"]
    assert [(l["item_name"], l["lot_number"], l["quantity"], l["unit"]) for l in bill["supply_lines"]] == [("Tomato Hybrid", "TH-1", 30, "packets"), ("Neem oil", "NM-7", 2.5, "litre")]
    assert all(l["batch_id"] for l in bill["supply_lines"])
    # stock went into the lot batches, with the bill number on the receipt...
    seed_batch = _batches(c, batch="TH-1")[0]
    assert seed_batch["remaining"] == 30 and seed_batch["plant_id"] == plant["id"] and seed_batch["item_kind"] == "seed_packet"
    med_batch = _batches(c, batch="NM-7")[0]
    assert med_batch["remaining"] == 2.5 and med_batch["quantity_unit"] == "litre" and med_batch["plant_id"] is None and med_batch["item_kind"] == "medicine"
    hist = c.get(f"{P}/history?batch_id={seed_batch['id']}").json()
    assert hist[0]["type"] == "RECEIPT" and hist[0]["invoice_number"] == "SUP-501" and hist[0]["purchase_id"] == bill["id"] and hist[0]["supplier"] == sup["name"]
    # ...and never into ready-to-sell plant stock
    assert _stock(plant["id"]) == 25
    db = SessionLocal()
    try:
        assert db.query(InventoryTransaction).filter(InventoryTransaction.plant_id == plant["id"], InventoryTransaction.transaction_type == "PURCHASE_RECEIVED").count() == 0
        assert db.query(Expense).filter(Expense.contact_id == sup["id"]).count() == 0  # a bill, not an expense
    finally:
        db.close()
    # the supplier owes the bill total, once
    assert c.get(f"{ACC}/contacts/{sup['id']}").json()["payable"] == 1300
    # a bill can only be made once from an order
    assert _bill(c, po["id"]).status_code == 400
    assert c.get(f"{ACC}/contacts/{sup['id']}").json()["payable"] == 1300 and len(_batches(c, batch="TH-1")) == 1
    assert c.get(f"{P}/{seed_batch['id']}").json()["remaining"] == 30


def test_same_lot_on_a_second_bill_joins_the_same_batch_with_its_own_bill_number():
    c = _admin()
    sup = _supplier(c)
    line = _line("medicine", description="Fungicide X", lot_number="FX-9", unit="bottles", quantity=10, unit_price=100)
    b1 = _bill(c, _po(c, sup, [line]).json()["id"], supplier_bill_number="B-1").json()
    b2 = _bill(c, _po(c, sup, [line | {"quantity": 5}]).json()["id"], supplier_bill_number="B-2").json()
    batches = _batches(c, batch="FX-9")
    assert len(batches) == 1 and batches[0]["received"] == 15 and batches[0]["remaining"] == 15
    receipts = [h for h in c.get(f"{P}/history?batch_id={batches[0]['id']}").json() if h["type"] == "RECEIPT"]
    assert sorted(r["invoice_number"] for r in receipts) == ["B-1", "B-2"] and {r["purchase_id"] for r in receipts} == {b1["id"], b2["id"]}
    assert c.get(f"{ACC}/contacts/{sup['id']}").json()["payable"] == 1500


def test_same_lot_with_a_different_expiry_is_refused_and_nothing_is_saved():
    c = _admin()
    sup = _supplier(c)
    tag = uuid.uuid4().hex[:6]
    line = _line("seed_packet", description="Okra", lot_number=f"OK-{tag}", quantity=10, unit_price=5)
    _bill(c, _po(c, sup, [line]).json()["id"])
    clash = line | {"expiry_date": (date.today() + timedelta(days=700)).isoformat()}
    po2 = _po(c, sup, [_line("seed_packet", description="Other", lot_number=f"ZQ-{tag}", quantity=3, unit_price=5), clash]).json()
    r = _bill(c, po2["id"])
    assert r.status_code == 409 and "one expiry date" in r.text
    assert c.get(f"{ACC}/purchase-orders/{po2['id']}").json()["bill"] is None  # still not billed
    assert _batches(c, batch=f"ZQ-{tag}") == []  # the good line was not half-received
    assert c.get(f"{ACC}/contacts/{sup['id']}").json()["payable"] == 50
    # a retry after fixing the order works
    assert c.get(f"{ACC}/purchase-orders/{po2['id']}").json()["status"] == "Draft"


def test_duplicate_supplier_bill_number_is_stopped_unless_overridden_with_a_reason():
    c = _admin()
    sup, other = _supplier(c), _supplier(c)
    one = lambda s, n, **kw: _bill(c, _po(c, s, [_line("fertilizer", unit="bags", lot_number="", expiry_date=None)]).json()["id"], supplier_bill_number=n, **kw)
    assert one(sup, "DUP-1").status_code == 200
    r = one(sup, "dup-1 ")  # same number: capitals and spaces do not matter
    assert r.status_code == 409 and "DUPLICATE_BILL" in r.text and "DUP-1" in r.text
    assert one(other, "DUP-1").status_code == 200  # another supplier may use the same number
    assert one(sup, "DUP-1", allow_duplicate_bill=True).status_code == 409  # an override needs a reason
    ok = one(sup, "DUP-1", allow_duplicate_bill=True, duplicate_reason="Second bill, same number, supplier confirmed")
    assert ok.status_code == 200 and ok.json()["duplicate_override_reason"].startswith("Second bill") and ok.json()["duplicate_override_by"]
    # no bill number at all is never a duplicate
    assert one(sup, "").status_code == 200 and one(sup, "").status_code == 200
    # the stopped attempt left nothing behind: 1 + 1 override + 2 blank = 4 bills for this supplier
    assert len(c.get(f"{ACC}/bills?contact_id={sup['id']}").json()) == 4


# ------------------------------------------------------------------ standalone Packet Entry
def _entry(c, **kw):
    body = {"item_kind": "seed_packet", "item_name": f"Seed {uuid.uuid4().hex[:4]}", "company": "Co", "lot_number": f"L-{uuid.uuid4().hex[:5]}", "quantity": 10, "purchase_date": date.today().isoformat(),
            "expiry_date": (date.today() + timedelta(days=300)).isoformat(), "request_id": uuid.uuid4().hex} | kw
    return c.post(P, json=body)


def test_unassigned_packet_and_plant_link_and_no_plant_stock_change():
    c = _admin()
    plant = _plant(c, stock=12)
    free = _entry(c, item_name="Mystery seed").json()
    assert free["plant_id"] is None and free["plant_name"] == "Unassigned / General stock"
    linked = _entry(c, plant_id=plant["id"], item_name="Chilli F1", unit_price=3, supplier="Link Agro", invoice_number="LK-1").json()
    assert linked["plant_id"] == plant["id"] and linked["billed"] is True
    assert _stock(plant["id"]) == 12
    hist = c.get(f"/api/admin/plants/{plant['id']}/history").json()
    assert [p["id"] for p in hist["packets"]] == [linked["id"]] and hist["packets"][0]["receipts"][0]["bill_number"] == "LK-1" and hist["packets"][0]["receipts"][0]["supplier"] == "Link Agro"
    assert free["id"] not in [p["id"] for p in hist["packets"]]


def test_standalone_entry_supports_every_kind_and_decimals():
    c = _admin()
    sup = _supplier(c)
    r = _entry(c, item_kind="fertilizer", item_name="Urea", company="", lot_number="", expiry_date=None, quantity=12.5, quantity_unit="kg", unit_price=6.4, supplier_contact_id=sup["id"], invoice_number="U-1")
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["remaining"] == 12.5 and j["quantity_unit"] == "kg" and j["expiry_date"] is None and j["status"] == "OK" and j["billed"] is True
    bill = c.get(f"{ACC}/bills/{j['purchase_id']}").json()
    assert bill["total_cost"] == 80.0 and bill["status"] == "Unpaid"
    use = c.post(f"{P}/{j['id']}/use", json={"quantity": 2.25, "request_id": uuid.uuid4().hex})
    assert use.status_code == 200 and use.json()["remaining"] == 10.25 and use.json()["used"] == 2.25
    assert _entry(c, item_kind="medicine", item_name="Spray", quantity=2.5, quantity_unit="bottles").status_code == 400
    bottles = _entry(c, item_kind="medicine", item_name="Spray 2", quantity=4, quantity_unit="bottles").json()
    assert c.post(f"{P}/{bottles['id']}/use", json={"quantity": 1.5, "request_id": uuid.uuid4().hex}).status_code == 400  # whole units cannot be used in fractions
    assert c.post(f"{P}/{bottles['id']}/adjust", json={"new_remaining": 2.5, "reason": "count", "request_id": uuid.uuid4().hex}).status_code == 400
    # a lot without an expiry never raises an expiry alert
    assert j["id"] not in [a["id"] for a in c.get(f"{P}/alerts").json()["items"]]


def test_standalone_duplicate_bill_number_and_retry_safety():
    c = _admin()
    sup = _supplier(c)
    first = _entry(c, supplier_contact_id=sup["id"], unit_price=5, invoice_number="SA-1")
    assert first.status_code == 201
    dup = _entry(c, supplier_contact_id=sup["id"], unit_price=5, invoice_number="sa-1")
    assert dup.status_code == 409 and "DUPLICATE_BILL" in dup.text
    ok = _entry(c, supplier_contact_id=sup["id"], unit_price=5, invoice_number="SA-1", allow_duplicate_bill=True, duplicate_reason="Genuinely a second bill")
    assert ok.status_code == 201
    same = {"request_id": uuid.uuid4().hex}
    a, b = _entry(c, supplier_contact_id=sup["id"], unit_price=5, invoice_number="SA-2", **same), _entry(c, supplier_contact_id=sup["id"], unit_price=5, invoice_number="SA-2", **same)
    assert a.status_code == 201 and b.json()["already_saved"] is True
    assert len(c.get(f"{ACC}/bills?contact_id={sup['id']}").json()) == 3
    assert c.get(f"{ACC}/contacts/{sup['id']}").json()["payable"] == 150  # 3 bills x (10 x 5)
    assert _entry(c, supplier_contact_id=99999999, unit_price=5).status_code == 400
    assert _entry(c, paid_now=True, supplier_contact_id=sup["id"], unit_price=5).status_code == 400


# ------------------------------------------------------------------ supplier payable and payments
def test_payable_counts_bills_and_expenses_and_never_goes_negative_from_a_payment():
    c = _admin()
    sup = _supplier(c)
    po = _po(c, sup, [_line("supply", unit="pcs", lot_number="", expiry_date=None, quantity=4, unit_price=250)]).json()
    bill = _bill(c, po["id"], supplier_bill_number="PAY-1").json()
    assert c.get(f"{ACC}/contacts/{sup['id']}").json()["payable"] == 1000
    assert c.post(f"{ACC}/payments-out", json={"purchase_id": bill["id"], "amount": 400, "method": "Bank", "payment_date": "2026-10-16T00:00:00"}).status_code == 201
    got = c.get(f"{ACC}/contacts/{sup['id']}").json()
    assert got["payable"] == 600 and got["total_paid_out"] == 400
    # an expense booked against the supplier is owed too; paying it brings the payable back, never below what is really owed
    exp = c.post(f"{ACC}/expenses", json={"category": "Transport", "contact_id": sup["id"], "amount": 300, "expense_date": "2026-10-16T00:00:00", "description": "freight"}).json()
    assert c.get(f"{ACC}/contacts/{sup['id']}").json()["payable"] == 900
    assert c.post(f"{ACC}/payments-out", json={"expense_id": exp["id"], "amount": 300, "method": "Cash", "payment_date": "2026-10-16T00:00:00"}).status_code == 201
    assert c.get(f"{ACC}/contacts/{sup['id']}").json()["payable"] == 600
    rep = c.get(f"{ACC}/reports/supplier-outstanding").json()
    assert [r["outstanding"] for r in rep["rows"] if r["contact_id"] == sup["id"]] == [600]
    stmt = c.get(f"{ACC}/parties/{sup['id']}/statement").json()
    assert stmt["closing_balance"] == 600 and len(stmt["rows"]) == 4  # bill, expense, two payments
    assert c.post(f"{ACC}/payments-out", json={"purchase_id": bill["id"], "amount": 600, "method": "Bank", "payment_date": "2026-10-16T00:00:00"}).status_code == 201
    assert c.get(f"{ACC}/contacts/{sup['id']}").json()["payable"] == 0
    assert c.get(f"{ACC}/bills/{bill['id']}").json()["balance_due"] == 0


def test_older_plant_lines_on_a_purchase_order_still_receive_plant_stock():
    c = _admin()
    sup = _supplier(c)
    plant = _plant(c, stock=5)
    po = _po(c, sup, [_line("seed_packet", lot_number="LEG-1", quantity=3, unit_price=10)]).json()
    # an order made before this change: a plant line sits on it (added directly, as the old screen did)
    from app.accounting.models import PurchaseOrder, PurchaseOrderItem

    db = SessionLocal()
    try:
        order = db.query(PurchaseOrder).filter(PurchaseOrder.id == po["id"]).first()
        db.add(PurchaseOrderItem(purchase_order_id=order.id, plant_id=plant["id"], description=plant["name"], quantity=7, unit_price=4, line_total=28, item_kind="plant"))
        order.total_amount = order.subtotal = 58
        db.commit()
    finally:
        db.close()
    bill = _bill(c, po["id"], supplier_bill_number="LEG-B1").json()
    assert bill["total_cost"] == 58 and len(bill["items"]) == 1 and len(bill["supply_lines"]) == 1
    assert _stock(plant["id"]) == 12  # the old plant line still receives plant stock, as before
    assert _batches(c, batch="LEG-1")[0]["remaining"] == 3  # and the packet goes to its lot, not to the plant


def test_bill_retry_cannot_double_stock_or_payable():
    c = _admin()
    sup = _supplier(c)
    po = _po(c, sup, [_line("medicine", lot_number="RT-1", unit="bottles", quantity=6, unit_price=50)]).json()
    assert _bill(c, po["id"], supplier_bill_number="RT-B").status_code == 200
    for _ in range(3):
        assert _bill(c, po["id"], supplier_bill_number="RT-B").status_code == 400
    assert _batches(c, batch="RT-1")[0]["remaining"] == 6 and c.get(f"{ACC}/contacts/{sup['id']}").json()["payable"] == 300


# ------------------------------------------------------------------ plant history
def test_plant_history_shows_stock_purchases_packets_and_customer_seeds():
    c = _admin()
    plant = _plant(c, stock=30)
    sup = _supplier(c)
    r1 = _entry(c, plant_id=plant["id"], item_name="Hy A", lot_number="PH-1", quantity=10, unit_price=4, supplier_contact_id=sup["id"], invoice_number="PH-B1").json()
    _entry(c, plant_id=plant["id"], item_name="Hy A", lot_number="PH-2", quantity=5, supplier="Cash Dealer")  # another lot of the same plant, no bill
    c.post(f"{ADMIN}/purchases", json={"purchase_date": datetime.utcnow().isoformat(), "supplier": "Plants Dealer", "invoice_number": "PD-1", "items": [{"plant_id": plant["id"], "quantity": 20, "unit_cost": 2}]})
    c.post(f"{ADMIN}/stock/seed-entries", json={"new_customer": {"name": "Hist Kisan", "phone": "9333300001"}, "plant_id": plant["id"], "seeds_given": 50, "wanted_plants": 40, "request_id": uuid.uuid4().hex})
    h = c.get(f"/api/admin/plants/{plant['id']}/history")
    assert h.status_code == 200
    j = h.json()
    assert j["plant"]["name"] == plant["name"] and j["plant"]["ready_stock"] == 50
    lots = {p["batch_number"]: p for p in j["packets"]}
    assert set(lots) == {"PH-1", "PH-2"} and j["packet_totals"]["lots"] == 2
    a = lots["PH-1"]
    assert a["receipts"][0]["bill_number"] == "PH-B1" and a["receipts"][0]["supplier"] == sup["name"] and a["receipts"][0]["quantity"] == 10 and a["receipts"][0]["purchase_date"] == date.today().isoformat()
    assert a["expiry_date"] and a["remaining"] == 10 and a["item_name"] == "Hy A"
    assert [m["type"] for m in j["packet_movements"]].count("RECEIPT") == 2
    assert any(s["type"] == "PURCHASE_RECEIVED" and s["quantity"] == 20 for s in j["stock_movements"]) and any(s["type"] == "OPENING_STOCK" for s in j["stock_movements"])
    assert [(p["bill_number"], p["quantity"]) for p in j["plant_purchases"]] == [("PD-1", 20)]
    assert [s["customer"] for s in j["customer_seeds"]] == ["Hist Kisan"]
    assert c.get("/api/admin/plants/99999999/history").status_code == 404
    assert r1["purchase_id"]


def test_new_plant_created_inactive_has_no_stock_and_a_packet_does_not_activate_it():
    c = _admin()
    cat = c.get(f"{ADMIN}/categories").json()[0]
    plant = c.post(f"{ADMIN}/plants", json={"name": f"Packet Plant {uuid.uuid4().hex[:5]}", "category_id": cat["id"], "price": 9, "stock_quantity": 0, "is_active": False}).json()
    assert plant["is_active"] is False and _stock(plant["id"]) == 0
    _entry(c, plant_id=plant["id"], item_name="Seed for it", quantity=40)
    assert _stock(plant["id"]) == 0  # 40 packets are packet stock, not 40 ready plants
    assert c.get(f"/api/admin/plants/{plant['id']}/history").json()["plant"]["is_active"] is False


def test_po_keeps_supplier_bill_number_and_uses_it_on_convert():
    c = _admin()
    sup = _supplier(c)
    line = _line("seed_packet", description="Okra", lot_number="OK-1", quantity=5, unit_price=10)
    po = _po(c, sup, [line], supplier_bill_number="  SB-77 ").json()
    assert po["supplier_bill_number"] == "SB-77"
    assert c.get(f"{PO}/{po['id']}").json()["supplier_bill_number"] == "SB-77"
    po2 = c.put(f"{PO}/{po['id']}", json={"contact_id": sup["id"], "order_date": datetime.utcnow().isoformat(), "items": [line], "supplier_bill_number": "SB-78"}).json()
    assert po2["supplier_bill_number"] == "SB-78"
    bill = _bill(c, po["id"]).json()
    assert bill["invoice_number"] == "SB-78"
