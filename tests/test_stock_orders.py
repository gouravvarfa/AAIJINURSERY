"""Stock team's Sales Order view: prepare target with a buffer, and recording how
many came out good (customer's share + leftover into general stock)."""

import os

from app.database import SessionLocal
from app.models import Plant

A = "/api/admin/accounting"
S = "/api/admin/stock-orders"
ADMIN = "/api/admin"
_n = {"i": 0}


def _login(client):
    r = client.post("/api/auth/login", json={"identifier": os.environ["DEFAULT_ADMIN_USERNAME"], "password": os.environ["DEFAULT_ADMIN_PASSWORD"]})
    assert r.status_code == 200


def _plant(client, stock):
    _n["i"] += 1
    cat = client.get(f"{ADMIN}/categories").json()[0]
    r = client.post(f"{ADMIN}/plants", json={"name": f"Tomato {_n['i']}", "category_id": cat["id"], "price": 10, "stock_quantity": stock})
    assert r.status_code == 201, r.text
    return r.json()


def _stock(plant_id):
    db = SessionLocal()
    try:
        return db.query(Plant.stock_quantity).filter(Plant.id == plant_id).scalar()
    finally:
        db.close()


def _order(client, plant_id, qty):
    contact = client.post(f"{A}/contacts", json={"name": "Ramesh Stock Test", "phone": "9000000077"}).json()
    r = client.post(f"{A}/sales-orders", json={
        "contact_id": contact["id"], "order_date": "2026-10-14T00:00:00",
        "items": [{"plant_id": plant_id, "description": "tomato", "quantity": qty, "unit_price": 5}],
    })
    assert r.status_code == 201, r.text
    return r.json()


def _line(client, order_id):
    rows = [r for r in client.get(S).json()["items"] if r["sales_order_id"] == order_id]
    assert len(rows) == 1
    return rows[0]


def test_buffer_on_new_plants_then_leftover_goes_to_stock(client):
    _login(client)
    plant = _plant(client, 40)
    order = _order(client, plant["id"], 100)

    # Shows up for the stock team straight away, with customer name and no prices.
    row = _line(client, order["id"])
    assert row["customer_name"] == "Ramesh Stock Test"
    assert (row["quantity"], row["allocated"], row["pending"], row["available_stock"]) == (100, 0, 100, 40)
    assert not any("price" in k or "amount" in k for k in row)

    # 40 already good in stock -> give them first, 60 still to be grown.
    assert client.post(f"/api/admin/inventory/fulfil", json={"kind": "sales_order", "item_id": row["line_id"], "action": "stock", "quantity": 40}).status_code == 200
    row = _line(client, order["id"])
    assert (row["allocated"], row["pending"]) == (40, 60)

    # Stock team decides to grow 80 (60 + 20 buffer).
    r = client.put(f"{S}/lines/{row['line_id']}/prepare", json={"prepare_quantity": 80})
    assert r.status_code == 200 and r.json()["to_prepare"] is True

    # All 80 come out good: 60 to the customer, 20 into general stock.
    r = client.post(f"{S}/lines/{row['line_id']}/ready", json={"good": 80, "to_customer": 60})
    assert r.status_code == 200, r.text
    assert r.json()["to_general_stock"] == 20
    assert _stock(plant["id"]) == 20

    # Order is now fully covered and drops off the "needs plants" list; customer's order is untouched.
    assert not [x for x in client.get(f"{S}?only_pending=true").json()["items"] if x["sales_order_id"] == order["id"]]
    so = client.get(f"{A}/sales-orders/{order['id']}").json()
    assert so["items"][0]["quantity"] == 100 and so["total_amount"] == 500


def test_some_plants_lost_and_validation(client):
    _login(client)
    plant = _plant(client, 0)
    order = _order(client, plant["id"], 10)
    row = _line(client, order["id"])

    assert client.post(f"{S}/lines/{row['line_id']}/ready", json={"good": 5, "to_customer": 6}).status_code == 400
    assert client.post(f"{S}/lines/{row['line_id']}/ready", json={"good": 20, "to_customer": 11}).status_code == 400

    # Only 7 of the grown plants survive: all 7 go to the customer, 3 still pending.
    r = client.post(f"{S}/lines/{row['line_id']}/ready", json={"good": 7, "to_customer": 7})
    assert r.status_code == 200 and r.json()["pending"] == 3
    assert _stock(plant["id"]) == 0

    # Clearing the target.
    assert client.put(f"{S}/lines/{row['line_id']}/prepare", json={"prepare_quantity": 0}).json()["to_prepare"] is False


def test_alert_numbers_and_new_order_alert_never_blocks_saving(client):
    _login(client)
    assert client.post(f"{S}/alert-recipients", json={"name": "Stock", "mobile": "123"}).status_code == 400
    r = client.post(f"{S}/alert-recipients", json={"name": "Stock Boy", "mobile": "98765 43210"})
    assert r.status_code == 201 and r.json()["mobile"] == "+919876543210"
    assert any(x["mobile"] == "+919876543210" for x in client.get(f"{S}/alert-recipients").json())

    # Saving an order with an alert number set up works even though the WhatsApp template isn't approved yet.
    plant = _plant(client, 5)
    _order(client, plant["id"], 2)

    assert client.delete(f"{S}/alert-recipients/{r.json()['id']}").status_code == 200
    assert not any(x["id"] == r.json()["id"] for x in client.get(f"{S}/alert-recipients").json())


def test_free_text_line_and_invoiced_order_still_show_for_stock_team(client):
    _login(client)
    plant = _plant(client, 50)
    contact = client.post(f"{A}/contacts", json={"name": "Free Text Party", "phone": "9000000088"}).json()
    r = client.post(f"{A}/sales-orders", json={
        "contact_id": contact["id"], "order_date": "2026-10-14T00:00:00",
        "items": [
            {"description": "10 tray tomato (typed, no plant picked)", "quantity": 10, "unit_price": 5},
            {"plant_id": plant["id"], "description": "linked", "quantity": 5, "unit_price": 5},
        ],
    })
    assert r.status_code == 201, r.text
    order_id = r.json()["id"]

    rows = [x for x in client.get(S).json()["items"] if x["sales_order_id"] == order_id]
    assert sorted(x["has_plant"] for x in rows) == [False, True]
    free = next(x for x in rows if not x["has_plant"])
    assert free["customer_name"] == "Free Text Party" and free["quantity"] == 10 and free["available_stock"] is None
    # No stock actions are possible on a line with no plant.
    assert client.put(f"{S}/lines/{free['line_id']}/prepare", json={"prepare_quantity": 5}).status_code == 404

    # Invoicing gives the in-stock line from stock (nothing pending) -- it must still be listed.
    assert client.post(f"{A}/sales-orders/{order_id}/convert-to-invoice", json={"due_date": "2026-10-30T00:00:00"}).status_code == 200
    rows = [x for x in client.get(S).json()["items"] if x["sales_order_id"] == order_id]
    assert len(rows) == 2
    linked = next(x for x in rows if x["has_plant"])
    assert linked["pending"] == 0
    # The optional "hide fully given" filter drops it again.
    hidden = [x for x in client.get(f"{S}?only_pending=true").json()["items"] if x["line_id"] == linked["line_id"]]
    assert hidden == []
