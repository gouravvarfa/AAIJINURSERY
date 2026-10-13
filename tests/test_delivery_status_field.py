"""Sales orders and invoices report the status of their latest delivery
(read-only, computed from the deliveries table) so the admin lists can hide
the delivery-date alert once an order has been delivered."""

import os

A = "/api/admin/accounting"
D = "/api/admin/delivery"


def _login(client):
    r = client.post("/api/auth/login", json={"identifier": os.environ["DEFAULT_ADMIN_USERNAME"], "password": os.environ["DEFAULT_ADMIN_PASSWORD"]})
    assert r.status_code == 200


def _sales_order(client, contact_id, delivery_date=None):
    r = client.post(f"{A}/sales-orders", json={
        "contact_id": contact_id, "order_date": "2026-10-13T00:00:00", "delivery_date": delivery_date,
        "items": [{"description": "plant", "quantity": 2, "unit_price": 50}],
    })
    assert r.status_code == 201, r.text
    return r.json()


def test_delivery_date_and_status_on_orders_and_invoices(client):
    _login(client)
    contact = client.post(f"{A}/contacts", json={"name": "Delivery Status Party", "phone": "9000000042"}).json()
    plain = _sales_order(client, contact["id"], delivery_date=None)
    dated = _sales_order(client, contact["id"], delivery_date="2026-10-20T00:00:00")

    listing = {o["id"]: o for o in client.get(f"{A}/sales-orders").json()}
    assert listing[plain["id"]]["delivery_date"] is None
    assert listing[dated["id"]]["delivery_date"].startswith("2026-10-20")
    assert listing[dated["id"]]["delivery_status"] is None

    delivery = client.post(f"{D}/deliveries", json={"delivery_date": "2026-10-20T00:00:00", "contact_id": contact["id"], "sales_order_id": dated["id"]}).json()
    assert {o["id"]: o for o in client.get(f"{A}/sales-orders").json()}[dated["id"]]["delivery_status"] == "Ready"

    invoice = client.post(f"{A}/sales-orders/{dated['id']}/convert-to-invoice", json={"due_date": "2026-10-27T00:00:00"}).json()
    row = {i["id"]: i for i in client.get(f"{A}/invoices").json()}[invoice["id"]]
    assert row["sales_order"]["delivery_date"].startswith("2026-10-20")
    assert row["sales_order"]["delivery_status"] == "Ready"

    item = client.get(f"{D}/deliveries/{delivery['id']}").json()["items"][0]
    done = client.post(f"{D}/deliveries/{delivery['id']}/complete", json={"items": [{"item_id": item["id"], "delivered_quantity": item["ordered_quantity"]}]})
    assert done.status_code == 200
    assert {o["id"]: o for o in client.get(f"{A}/sales-orders").json()}[dated["id"]]["delivery_status"] == "Delivered"
    assert client.get(f"{A}/invoices/{invoice['id']}").json()["sales_order"]["delivery_status"] == "Delivered"
    # totals untouched
    assert client.get(f"{A}/sales-orders/{dated['id']}").json()["total_amount"] == 100
