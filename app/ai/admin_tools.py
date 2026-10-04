"""Controlled, read-only tools for the Admin "Ask AAIJI" assistant.

Same architecture discipline as app/ai/tools.py (the customer assistant):
the LLM never gets a database session, never executes SQL, and every tool
here is a plain function that returns a JSON-serializable dict.

The one thing added on top of the customer tools: every single tool here
calls check_permission(db, admin, module, action) itself, using the SAME
RBAC engine (app/permissions.py) every other admin page already respects --
BEFORE running any query. The LLM is never the thing deciding whether an
admin can see a module's data; it only ever sees the tool's result, which
is either real data or a permission-denied dict. A Delivery Manager asking
about company expenses gets denied by this check the same way clicking
into the Expenses page directly would deny them.

Nothing here performs a write. There is no .add()/.commit()/.delete() in
this file, by design -- Ask AAIJI is read-only in this phase.
"""
import re
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.accounting.models import (
    AuditLog, Contact, Employee, Expense, Invoice, PaymentIn, PaymentOut, SalesOrder,
)
from app.analytics_utils import money, now_ist, resolve_date_range, to_utc
from app.delivery.models import Delivery, DeliveryStatusHistory, DeliveryTrip, Driver, Vehicle
from app.models import (
    AdminActivityLog, AdminUser, Category, Customer, CustomerActivityLog, Inquiry,
    InventoryTransaction, LoginAttempt, Order, OrderItem, OrderStatusHistory, Plant, Purchase,
)
from app.permissions import check_permission

MAX_RESULTS = 10
LOW_STOCK_THRESHOLD = 20

# Mirrors app/delivery/router_deliveries.py's own TERMINAL_STATUSES -- a
# delivery is "pending" if it hasn't reached one of these yet. Duplicated
# as a plain constant here (not imported from a router module) to avoid
# coupling a tools module to route-layer code for one list of strings.
DELIVERY_TERMINAL_STATUSES = {"Delivered", "Partially Delivered", "Failed", "Cancelled"}


def _denied(module: str) -> dict:
    return {"error": f"You don't have permission to view {module} data."}


IST_OFFSET = timedelta(hours=5, minutes=30)
NOT_RECORDED = "not recorded"
RANGE_KEYS = {
    "today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days",
    "week", "month", "last_month", "year", "last_year",
}


def _fmt(dt) -> str | None:
    """Stored timestamps are UTC-naive; admins think in IST."""
    if not dt:
        return None
    return (dt + IST_OFFSET).strftime("%Y-%m-%d %H:%M IST")


def _parse_day(value: str):
    return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d")


def _range(range_key: str = "today", from_date: str = None, to_date: str = None):
    """Returns (start_utc, end_utc, error). A from_date (YYYY-MM-DD) wins
    over range_key; from_date alone means that single day."""
    try:
        if from_date:
            f = _parse_day(from_date)
            t = _parse_day(to_date) if to_date else f
            if t < f:
                return None, None, "to_date is before from_date."
            start, end = resolve_date_range("custom", f, t)
            return start, end, None
        key = range_key or "today"
        if key not in RANGE_KEYS:
            return None, None, f"Unknown range '{key}'. Use one of {sorted(RANGE_KEYS)} or from_date/to_date (YYYY-MM-DD)."
        today = now_ist().replace(hour=0, minute=0, second=0, microsecond=0)
        if key == "yesterday":
            return to_utc(today - timedelta(days=1)), to_utc(today), None
        if key == "day_before_yesterday":
            return to_utc(today - timedelta(days=2)), to_utc(today - timedelta(days=1)), None
        if key == "last_7_days":
            return to_utc(today - timedelta(days=6)), to_utc(today + timedelta(days=1)), None
        if key == "last_30_days":
            return to_utc(today - timedelta(days=29)), to_utc(today + timedelta(days=1)), None
        start, end = resolve_date_range(key)
        return start, end, None
    except ValueError:
        return None, None, "Dates must be in YYYY-MM-DD format."


def _first_actor(db: Session, table_name: str, record_id: int) -> str | None:
    row = (
        db.query(AuditLog.changed_by)
        .filter(AuditLog.table_name == table_name, AuditLog.record_id == record_id)
        .order_by(AuditLog.changed_at.asc(), AuditLog.id.asc())
        .first()
    )
    return row[0] if row and row[0] else None


def _first_actor_void(db: Session, invoice_id: int) -> str | None:
    row = (
        db.query(AuditLog.changed_by)
        .filter(AuditLog.table_name == "accounting_invoices", AuditLog.record_id == invoice_id, AuditLog.action == "void")
        .order_by(AuditLog.changed_at.desc())
        .first()
    )
    return row[0] if row and row[0] else None


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-zA-Z0-9]+", name or "") if t]


def _ambiguous_matches(db: Session, name: str) -> list[dict]:
    """More than one genuinely different person matching the query (case-
    insensitive duplicates of the same name don't count). An exact full-name
    match is never ambiguous."""
    tokens = _tokens(name)
    if not tokens:
        return []
    found: dict[str, dict] = {}
    cq = db.query(Customer.name, Customer.mobile)
    for t in tokens:
        cq = cq.filter(Customer.name.ilike(f"%{t}%"))
    for n, m in cq.limit(20).all():
        found.setdefault(n.strip().lower(), {"name": n, "mobile": m, "channel": "online"})
    kq = db.query(Contact.name, Contact.phone)
    for t in tokens:
        kq = kq.filter(Contact.name.ilike(f"%{t}%"))
    for n, m in kq.limit(20).all():
        found.setdefault(n.strip().lower(), {"name": n, "mobile": m, "channel": "offline"})
    if name.strip().lower() in found or len(found) < 2:
        return []
    return list(found.values())[:8]


def _ambiguity_reply(matches: list[dict]) -> dict:
    return {
        "ambiguous": True,
        "message": "Multiple matching customers found. Ask the admin which one they mean (name + mobile).",
        "matches": matches,
    }


def _find_customer(db: Session, name: str) -> Customer | None:
    """Duplicate/near-duplicate customer records (e.g. "Gourav Varfa" and
    "gourav varfa" as two separate accounts) are a real, observed data
    pattern here -- a plain .first() can silently pick the empty one and
    truthfully-but-unhelpfully report "no purchases" for someone who
    clearly has orders. When more than one candidate matches the name,
    prefer whichever actually has order history, most recent first."""
    tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", name) if t]
    if not tokens:
        return None
    q = db.query(Customer)
    for t in tokens:
        q = q.filter(Customer.name.ilike(f"%{t}%"))
    candidates = q.all() or db.query(Customer).filter(Customer.name.ilike(f"%{name.strip()}%")).all()
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    order_counts = dict(
        db.query(Order.customer_id, func.count(Order.id))
        .filter(Order.customer_id.in_([c.id for c in candidates]))
        .group_by(Order.customer_id)
        .all()
    )
    return max(candidates, key=lambda c: order_counts.get(c.id, 0))


def _find_contact(db: Session, name: str) -> Contact | None:
    """Covers offline-only parties (e.g. walk-in customers entered straight
    into accounting) that have no website Customer row at all -- Customer
    search alone would silently miss these ('couldn't find any record' even
    though the Parties page clearly shows them)."""
    tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", name) if t]
    if not tokens:
        return None
    q = db.query(Contact)
    for t in tokens:
        q = q.filter(Contact.name.ilike(f"%{t}%"))
    candidates = q.all() or db.query(Contact).filter(Contact.name.ilike(f"%{name.strip()}%")).all()
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    order_counts = dict(
        db.query(SalesOrder.contact_id, func.count(SalesOrder.id))
        .filter(SalesOrder.contact_id.in_([c.id for c in candidates]))
        .group_by(SalesOrder.contact_id)
        .all()
    )
    return max(candidates, key=lambda c: order_counts.get(c.id, 0))


def _find_driver(db: Session, name: str) -> Driver | None:
    tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", name) if t]
    if not tokens:
        return None
    q = db.query(Driver)
    for t in tokens:
        q = q.filter(Driver.name.ilike(f"%{t}%"))
    return q.first() or db.query(Driver).filter(Driver.name.ilike(f"%{name.strip()}%")).first()


# ---------- Sales ----------

def get_sales_summary(db: Session, admin: AdminUser, range: str = "today", channel: str = "all", from_date: str = None, to_date: str = None) -> dict:
    """channel: 'all' | 'online' | 'offline'. Covers 'today's sales', and
    conversational follow-ups like 'online?'/'offline?' after it -- the
    model re-calls this with channel set instead of needing a second tool."""
    if not check_permission(db, admin, "analytics", "VIEW"):
        return _denied("analytics")
    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}

    online_sales, online_orders = 0.0, 0
    if channel != "offline":
        row = (
            db.query(func.coalesce(func.sum(Order.total_amount), 0), func.count(Order.id))
            .filter(Order.created_at >= start, Order.created_at < end, Order.status != "Cancelled")
            .first()
        )
        online_sales, online_orders = money(row[0]), int(row[1] or 0)

    offline_sales, offline_invoices = 0.0, 0
    if channel != "online":
        row = (
            db.query(func.coalesce(func.sum(Invoice.total_amount), 0), func.count(Invoice.id))
            .filter(
                Invoice.invoice_date >= start,
                Invoice.invoice_date < end,
                Invoice.source == "offline",
                Invoice.status != "Voided",
            )
            .first()
        )
        offline_sales, offline_invoices = money(row[0]), int(row[1] or 0)

    return {
        "range": f"{from_date}..{to_date or from_date}" if from_date else range,
        "channel": channel,
        "online_sales": online_sales,
        "online_orders": online_orders,
        "offline_sales": offline_sales,
        "offline_invoices": offline_invoices,
        "total_sales": money(online_sales + offline_sales),
    }


def get_customers_who_purchased(db: Session, admin: AdminUser, range: str = "today", limit: int = 15, from_date: str = None, to_date: str = None) -> dict:
    """Who bought what in a period -- online Orders and offline Invoices,
    with the customer, products and amount. Totals/highest/lowest are
    computed over ALL matching purchases, not just the listed page."""
    if not check_permission(db, admin, "analytics", "VIEW"):
        return _denied("analytics")
    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    cap = max(1, min(limit or 15, 25))

    purchases = []
    for o in (
        db.query(Order)
        .filter(Order.created_at >= start, Order.created_at < end, Order.status != "Cancelled")
        .order_by(Order.created_at.desc())
        .limit(300)
        .all()
    ):
        purchases.append({
            "order_ref": f"Order #{o.id}",
            "customer_name": o.delivery_name or (o.customer.name if o.customer else "Unknown"),
            "channel": "online",
            "payment_method": o.payment_method,
            "amount": o.total_amount,
            "products": [f"{i.plant_name} x{i.quantity}" for i in o.items],
            "_t": o.created_at,
        })
    for inv in (
        db.query(Invoice)
        .filter(Invoice.invoice_date >= start, Invoice.invoice_date < end, Invoice.source == "offline", Invoice.status != "Voided")
        .order_by(Invoice.invoice_date.desc())
        .limit(300)
        .all()
    ):
        purchases.append({
            "order_ref": f"Invoice {inv.invoice_number}",
            "customer_name": inv.contact.name if inv.contact else "Unknown",
            "channel": "offline",
            "payment_status": inv.status,
            "amount": inv.total_amount,
            "products": [f"{i.description} x{i.quantity}" for i in inv.items],
            "_t": inv.invoice_date,
        })

    purchases.sort(key=lambda p: p["_t"], reverse=True)
    total = len(purchases)
    summary = {
        "total_purchases": total,
        "distinct_customers": len({p["customer_name"].strip().lower() for p in purchases}),
        "total_amount": money(sum(p["amount"] or 0 for p in purchases)),
    }
    if purchases:
        hi = max(purchases, key=lambda p: p["amount"] or 0)
        lo = min(purchases, key=lambda p: p["amount"] or 0)
        summary["highest_order"] = {k: hi[k] for k in ("order_ref", "customer_name", "amount")}
        summary["lowest_order"] = {k: lo[k] for k in ("order_ref", "customer_name", "amount")}
    page = purchases[:cap]
    for p in page:
        p["when"] = _fmt(p.pop("_t"))
    return {
        "range": f"{from_date}..{to_date or from_date}" if from_date else range,
        **summary,
        "listed": len(page),
        "purchases": page,
    }


def get_top_selling_plants(db: Session, admin: AdminUser, range: str = "month", limit: int = 5, from_date: str = None, to_date: str = None) -> dict:
    if not check_permission(db, admin, "analytics", "VIEW"):
        return _denied("analytics")
    from app.analytics_utils import combined_sale_lines

    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    lines = combined_sale_lines(db, start, end, "")
    totals: dict[int, int] = {}
    for line in lines:
        if line.plant_id is None:
            continue
        totals[line.plant_id] = totals.get(line.plant_id, 0) + int(line.quantity or 0)
    top = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[: min(limit, MAX_RESULTS)]
    names = dict(db.query(Plant.id, Plant.name).filter(Plant.id.in_([pid for pid, _ in top])).all())
    return {"range": range, "top_plants": [{"name": names.get(pid, "Unknown"), "units_sold": qty} for pid, qty in top]}


# ---------- Orders ----------

def get_pending_orders(db: Session, admin: AdminUser, limit: int = 10) -> dict:
    if not check_permission(db, admin, "orders", "VIEW"):
        return _denied("orders")
    orders = (
        db.query(Order)
        .filter(Order.status.notin_(["Delivered", "Cancelled"]))
        .order_by(Order.created_at.desc())
        .limit(min(limit, MAX_RESULTS))
        .all()
    )
    return {
        "count": len(orders),
        "orders": [
            {"order_id": o.id, "status": o.status, "total_amount": o.total_amount, "created_at": o.created_at.isoformat()}
            for o in orders
        ],
    }


def get_order_details(db: Session, admin: AdminUser, order_id: int) -> dict:
    """order_id is the plain numeric Order ID shown in the admin Orders
    list (this system doesn't use formatted order codes like 'AA1024')."""
    if not check_permission(db, admin, "orders", "VIEW"):
        return _denied("orders")
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return {"error": f"No order #{order_id} found."}
    return {
        "order_id": order.id,
        "status": order.status,
        "payment_status": order.payment_status,
        "payment_method": order.payment_method,
        "total_amount": order.total_amount,
        "customer_name": order.delivery_name,
        "tracking_number": order.tracking_number,
        "delivery_partner": order.delivery_partner,
        "created_at": order.created_at.isoformat(),
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        "items": [
            {"plant_name": i.plant_name, "quantity": i.quantity, "unit_price": i.unit_price, "line_total": i.line_total}
            for i in order.items
        ],
    }


# ---------- Customers ----------

def search_customer(db: Session, admin: AdminUser, name: str) -> dict:
    if not check_permission(db, admin, "customers", "VIEW"):
        return _denied("customers")
    tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", name) if t]
    q = db.query(Customer)
    for t in tokens:
        q = q.filter(Customer.name.ilike(f"%{t}%"))
    customers = q.limit(5).all()
    results = [{"id": c.id, "name": c.name, "mobile": c.mobile, "email": c.email, "channel": "online"} for c in customers]

    # Offline-only parties (accounting Contact with no linked website
    # Customer row) -- otherwise invisible to this search, same gap that
    # caused "couldn't find any record" for walk-in customers.
    cq = db.query(Contact).filter(Contact.customer_id.is_(None))
    for t in tokens:
        cq = cq.filter(Contact.name.ilike(f"%{t}%"))
    contacts = cq.limit(5).all()
    results += [{"id": c.id, "name": c.name, "mobile": c.phone, "email": c.email, "channel": "offline"} for c in contacts]

    return {"count": len(results), "customers": results[:10]}


def get_customer_purchase_history(db: Session, admin: AdminUser, name: str, months: int = None) -> dict:
    if not check_permission(db, admin, "customers", "VIEW"):
        return _denied("customers")
    amb = _ambiguous_matches(db, name)
    if amb:
        return _ambiguity_reply(amb)
    customer = _find_customer(db, name)
    if customer:
        q = db.query(Order).filter(Order.customer_id == customer.id, Order.status != "Cancelled")
        if months:
            cutoff = to_utc(now_ist() - timedelta(days=30 * months))
            q = q.filter(Order.created_at >= cutoff)
        orders = q.order_by(Order.created_at.desc()).limit(MAX_RESULTS).all()
        total_spent = sum(o.total_amount for o in orders)
        return {
            "customer_name": customer.name,
            "mobile": customer.mobile,
            "channel": "online",
            "order_count": len(orders),
            "total_spent": money(total_spent),
            "last_purchase_date": orders[0].created_at.isoformat() if orders else None,
            "orders": [
                {
                    "order_id": o.id,
                    "status": o.status,
                    "total_amount": o.total_amount,
                    "created_at": o.created_at.isoformat(),
                    "items": [i.plant_name for i in o.items],
                }
                for o in orders
            ],
        }

    # Fall back to an offline-only accounting Contact (e.g. a walk-in
    # customer who has never registered on the website).
    contact = _find_contact(db, name)
    if not contact:
        return {"error": f"No customer found matching '{name}'."}
    q = db.query(SalesOrder).filter(SalesOrder.contact_id == contact.id, SalesOrder.status != "Cancelled")
    if months:
        cutoff = to_utc(now_ist() - timedelta(days=30 * months))
        q = q.filter(SalesOrder.order_date >= cutoff)
    sorders = q.order_by(SalesOrder.order_date.desc()).limit(MAX_RESULTS).all()
    total_spent = sum(so.total_amount for so in sorders)
    return {
        "customer_name": contact.name,
        "mobile": contact.phone,
        "channel": "offline",
        "order_count": len(sorders),
        "total_spent": money(total_spent),
        "last_purchase_date": sorders[0].order_date.isoformat() if sorders else None,
        "orders": [
            {
                "order_id": so.id,
                "status": so.status,
                "total_amount": so.total_amount,
                "created_at": so.order_date.isoformat(),
                "items": [i.description for i in so.items],
            }
            for so in sorders
        ],
    }


def get_customer_outstanding(db: Session, admin: AdminUser, name: str) -> dict:
    if not check_permission(db, admin, "accounting", "VIEW"):
        return _denied("accounting")
    amb = _ambiguous_matches(db, name)
    if amb:
        return _ambiguity_reply(amb)
    customer = _find_customer(db, name)
    if customer:
        contact = db.query(Contact).filter(Contact.customer_id == customer.id).first()
        display_name = customer.name
    else:
        contact = _find_contact(db, name)
        display_name = contact.name if contact else None
    if not contact:
        if not display_name:
            return {"error": f"No customer found matching '{name}'."}
        return {"customer_name": display_name, "outstanding_amount": 0, "note": "No accounting record for this customer."}
    outstanding = (
        db.query(func.coalesce(func.sum(Invoice.balance_due), 0))
        .filter(Invoice.contact_id == contact.id, Invoice.status != "Voided")
        .scalar()
    )
    return {"customer_name": display_name, "outstanding_amount": money(outstanding)}


def get_customer_invoices(db: Session, admin: AdminUser, name: str, limit: int = 10) -> dict:
    """Full invoice/bill list for a customer by name -- works for both
    website customers and offline-only accounting contacts (same lookup
    used by get_customer_purchase_history)."""
    if not check_permission(db, admin, "accounting", "VIEW"):
        return _denied("accounting")
    amb = _ambiguous_matches(db, name)
    if amb:
        return _ambiguity_reply(amb)
    customer = _find_customer(db, name)
    if customer:
        contact = db.query(Contact).filter(Contact.customer_id == customer.id).first()
        display_name = customer.name
    else:
        contact = _find_contact(db, name)
        display_name = contact.name if contact else None
    if not contact:
        if not display_name:
            return {"error": f"No customer found matching '{name}'."}
        return {"customer_name": display_name, "count": 0, "invoices": []}

    invoices = (
        db.query(Invoice)
        .filter(Invoice.contact_id == contact.id)
        .order_by(Invoice.invoice_date.desc())
        .limit(min(limit, MAX_RESULTS))
        .all()
    )
    return {
        "customer_name": display_name,
        "count": len(invoices),
        "invoices": [
            {
                "invoice_id": inv.id,
                "invoice_number": inv.invoice_number,
                "status": inv.status,
                "voided_by": (inv.voided_by or _first_actor_void(db, inv.id) or NOT_RECORDED) if inv.status == "Voided" else None,
                "voided_at": _fmt(inv.voided_at) if inv.voided_at else None,
                "invoice_date": _fmt(inv.invoice_date),
                "total_amount": inv.total_amount,
                "amount_paid": inv.amount_paid,
                "balance_due": inv.balance_due,
                "items": [
                    {"description": i.description, "quantity": i.quantity, "unit_price": i.unit_price, "line_total": i.line_total}
                    for i in inv.items
                ],
            }
            for inv in invoices
        ],
    }


# ---------- Employees ----------

def get_employee_details(db: Session, admin: AdminUser, name: str) -> dict:
    """Full profile for one employee by name. Bank account details are
    deliberately excluded from the response -- an AI chat answer is the
    wrong place for that even if the admin has permission to see it."""
    if not check_permission(db, admin, "labour", "VIEW"):
        return _denied("employees")
    tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", name) if t]
    q = db.query(Employee)
    for t in tokens:
        q = q.filter(Employee.name.ilike(f"%{t}%"))
    employee = q.first() or db.query(Employee).filter(Employee.name.ilike(f"%{name.strip()}%")).first()
    if not employee:
        return {"error": f"No employee found matching '{name}'."}
    return {
        "name": employee.name,
        "role": employee.role,
        "department": employee.department,
        "email": employee.email,
        "phone": employee.phone,
        "status": employee.status,
        "is_active": employee.is_active,
        "salary": employee.salary,
        "overtime_rate": employee.overtime_rate,
        "payment_method": employee.payment_method,
        "joining_date": employee.joining_date.isoformat() if employee.joining_date else None,
    }


# ---------- Inventory ----------

def get_low_stock_plants(db: Session, admin: AdminUser, threshold: int = LOW_STOCK_THRESHOLD) -> dict:
    if not check_permission(db, admin, "products", "VIEW"):
        return _denied("products")
    plants = (
        db.query(Plant)
        .filter(Plant.is_active.is_(True), Plant.stock_quantity <= threshold)
        .order_by(Plant.stock_quantity.asc())
        .limit(MAX_RESULTS)
        .all()
    )
    return {
        "count": len(plants),
        "plants": [{"name": p.name, "stock_quantity": p.stock_quantity} for p in plants],
    }


# ---------- Delivery ----------

def get_pending_deliveries(db: Session, admin: AdminUser, limit: int = 10) -> dict:
    if not check_permission(db, admin, "delivery", "VIEW"):
        return _denied("delivery")
    deliveries = (
        db.query(Delivery)
        .filter(Delivery.status.notin_(DELIVERY_TERMINAL_STATUSES))
        .order_by(Delivery.delivery_date.asc())
        .limit(min(limit, MAX_RESULTS))
        .all()
    )
    return {
        "count": len(deliveries),
        "deliveries": [
            {
                "delivery_number": d.delivery_number,
                "status": d.status,
                "delivery_date": d.delivery_date.isoformat() if d.delivery_date else None,
                "driver_name": d.driver.name if d.driver else "Unassigned",
            }
            for d in deliveries
        ],
    }


def get_driver_details(db: Session, admin: AdminUser, name: str) -> dict:
    """Full profile for one delivery driver by name: contact/vehicle info
    plus delivery/trip performance stats."""
    if not check_permission(db, admin, "delivery", "VIEW"):
        return _denied("delivery")
    driver = _find_driver(db, name)
    if not driver:
        return {"error": f"No driver found matching '{name}'."}

    total_deliveries = db.query(func.count(Delivery.id)).filter(Delivery.driver_id == driver.id).scalar() or 0
    completed = (
        db.query(func.count(Delivery.id))
        .filter(Delivery.driver_id == driver.id, Delivery.status == "Delivered")
        .scalar()
        or 0
    )
    pending = (
        db.query(func.count(Delivery.id))
        .filter(Delivery.driver_id == driver.id, Delivery.status.notin_(DELIVERY_TERMINAL_STATUSES))
        .scalar()
        or 0
    )
    recent_deliveries = (
        db.query(Delivery)
        .filter(Delivery.driver_id == driver.id)
        .order_by(Delivery.delivery_date.desc())
        .limit(MAX_RESULTS)
        .all()
    )
    total_trips = db.query(func.count(DeliveryTrip.id)).filter(DeliveryTrip.driver_id == driver.id).scalar() or 0

    return {
        "name": driver.name,
        "phone": driver.phone,
        "status": driver.status,
        "address": driver.address,
        "emergency_contact": driver.emergency_contact,
        "joining_date": driver.joining_date.isoformat() if driver.joining_date else None,
        "assigned_vehicle": driver.assigned_vehicle.registration_number if driver.assigned_vehicle else None,
        "total_deliveries": total_deliveries,
        "completed_deliveries": completed,
        "pending_deliveries": pending,
        "total_trips": total_trips,
        "recent_deliveries": [
            {
                "delivery_number": d.delivery_number,
                "status": d.status,
                "delivery_date": d.delivery_date.isoformat() if d.delivery_date else None,
                "customer_name": d.contact.name if d.contact else None,
            }
            for d in recent_deliveries
        ],
    }


def get_inquiries(db: Session, admin: AdminUser, range: str = "week", from_date: str = None, to_date: str = None, status: str = None, limit: int = 15) -> dict:
    """Website contact/product enquiries (the Inquiries page) -- who asked,
    about what plant, when, and whether it's been replied to."""
    if not check_permission(db, admin, "customers", "VIEW"):
        return _denied("customers")
    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    q = db.query(Inquiry).filter(Inquiry.created_at >= start, Inquiry.created_at < end)
    if status:
        q = q.filter(Inquiry.status == status.strip().lower())
    rows = q.order_by(Inquiry.created_at.desc()).all()
    by_status: dict = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    return {
        "range": f"{from_date}..{to_date or from_date}" if from_date else range,
        "count": len(rows),
        "by_status": by_status,
        "listed": [
            {
                "enquiry_number": r.enquiry_number or f"INQ-{r.id}",
                "when": _fmt(r.created_at),
                "name": r.name,
                "mobile": r.mobile,
                "plant": r.plant_name_snapshot or (r.plant.name if r.plant else None),
                "requirement": r.requirement or None,
                "status": r.status,
            }
            for r in rows[: max(1, min(limit or 15, 25))]
        ],
    }


def get_customer_counts(db: Session, admin: AdminUser) -> dict:
    """How many customers exist, by channel: online (registered on the
    website) vs offline-only (accounting contacts with no website
    account). Use for 'kitne online customer hai', 'total customers'."""
    if not check_permission(db, admin, "customers", "VIEW"):
        return _denied("customers")
    online = db.query(func.count(Customer.id)).scalar() or 0
    offline_only = db.query(func.count(Contact.id)).filter(Contact.customer_id.is_(None), Contact.contact_type.in_(["customer", "both"])).scalar() or 0
    return {
        "online_customers": online,
        "offline_only_customers": offline_only,
        "total_customers": online + offline_only,
    }


# ---------- Business overview ----------

def get_business_summary(db: Session, admin: AdminUser, range: str = "today") -> dict:
    """The catch-all 'how's the business doing' tool -- combines sales,
    pending orders, pending deliveries and low stock, each still gated by
    its own module permission (a user missing one of those permissions
    simply gets that one section omitted, not a full denial)."""
    out: dict = {"range": range}
    sales = get_sales_summary(db, admin, range=range)
    if "error" not in sales:
        out["total_sales"] = sales["total_sales"]
        out["online_sales"] = sales["online_sales"]
        out["offline_sales"] = sales["offline_sales"]
    pending_orders = get_pending_orders(db, admin, limit=1)
    if "error" not in pending_orders:
        out["pending_orders_count"] = pending_orders["count"] if pending_orders["count"] < MAX_RESULTS else f"{MAX_RESULTS}+"
    pending_deliveries = get_pending_deliveries(db, admin, limit=1)
    if "error" not in pending_deliveries:
        out["pending_deliveries_count"] = pending_deliveries["count"]
    low_stock = get_low_stock_plants(db, admin)
    if "error" not in low_stock:
        out["low_stock_plants_count"] = low_stock["count"]
    if len(out) == 1:
        return {"error": "You don't have permission to view any business summary data."}
    return out


# ---------- Audit / timeline / history tools ----------

AUDIT_ENTITY_TABLES = {
    "invoice": "accounting_invoices",
    "sales_order": "accounting_sales_orders",
    "contact": "accounting_contacts",
    "expense": "accounting_expenses",
    "payment_in": "accounting_payments_in",
    "payment_out": "accounting_payments_out",
    "purchase_order": "accounting_purchase_orders",
    "bill": "purchases",
}

# Facts the system genuinely never stores -- returned with timeline tools so
# the model can say so plainly instead of inventing an answer.
KNOWN_GAPS = [
    "Payment verification/approval: no such workflow exists; only who recorded the payment (and only for payments recorded after audit tracking began).",
    "Delivery approval: offline deliveries have no approval step. For online orders the closest is the team confirmation (team_confirmed_by).",
    "Refunds: no structured refund record (amount/actor/method) exists; 'Refund' is only a status label.",
    "Delivery driver/status change history exists only for changes made after audit tracking began.",
]


def _event(events: list, when, event: str, by, details):
    events.append({"_t": when, "when": _fmt(when), "event": event, "by": by or NOT_RECORDED, "details": details})


def get_order_timeline(db: Session, admin: AdminUser, order_id: int) -> dict:
    """Who did what on an online order and when: placement, acknowledgement,
    team (delivery-feasibility) confirmation, every status change with the
    admin's username, rejection reason, and stock movements."""
    if not check_permission(db, admin, "orders", "VIEW"):
        return _denied("orders")
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return {"error": f"No order #{order_id} found."}
    events: list = []
    _event(events, order.created_at, "Order placed", "customer (website)",
           f"total {money(order.total_amount)}, {order.payment_method}, payment {order.payment_status}")
    if order.acknowledged_by and order.acknowledged_at:
        _event(events, order.acknowledged_at, "Order acknowledged", order.acknowledged_by, None)
    if order.team_confirmed_at:
        _event(events, order.team_confirmed_at, "Team confirmation (delivery feasibility)", order.team_confirmed_by,
               f"confirmation={order.team_confirmation_status}, feasibility={order.delivery_feasibility}")
    for h in db.query(OrderStatusHistory).filter(OrderStatusHistory.order_id == order.id).order_by(OrderStatusHistory.created_at.asc(), OrderStatusHistory.id.asc()):
        _event(events, h.created_at, f"Status {h.old_status or '-'} -> {h.new_status}", h.updated_by, h.remarks or None)
    if check_permission(db, admin, "products", "VIEW"):
        for t in db.query(InventoryTransaction).filter(
            InventoryTransaction.source_id == str(order.id),
            InventoryTransaction.source_type.in_(["ONLINE_ORDER", "ADMIN_CANCEL", "DELIVERY_REJECTED"]),
        ).order_by(InventoryTransaction.created_at.asc()):
            _event(events, t.created_at, f"Stock {t.transaction_type}", t.created_by,
                   f"{t.plant.name if t.plant else t.plant_id}: {t.before_quantity} -> {t.after_quantity}")
    events.sort(key=lambda e: e["_t"])
    for e in events:
        e.pop("_t")
    return {
        "order_id": order.id,
        "customer_name": order.delivery_name,
        "status": order.status,
        "payment_status": order.payment_status,
        "payment_method": order.payment_method,
        "total_amount": order.total_amount,
        "assigned_to": order.assigned_to or NOT_RECORDED,
        "rejection_reason": order.delivery_rejection_reason or None,
        "delivered_at": _fmt(order.delivered_at),
        "items": [f"{i.plant_name} x{i.quantity}" for i in order.items],
        "events": events,
        "not_stored_by_system": KNOWN_GAPS,
    }


def get_payment_history(db: Session, admin: AdminUser, name: str = None, direction: str = "in", range: str = "month", from_date: str = None, to_date: str = None, limit: int = 15) -> dict:
    """Payments received (in) and/or paid out (out) in a period, optionally
    for one customer/party. Includes totals by method (Cash/UPI/...) and who
    recorded each payment where that is known."""
    if not check_permission(db, admin, "accounting", "VIEW"):
        return _denied("accounting")
    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    cap = max(1, min(limit or 15, 25))
    contact_ids = None
    display = None
    if name:
        amb = _ambiguous_matches(db, name)
        if amb:
            return _ambiguity_reply(amb)
        customer = _find_customer(db, name)
        ids = set()
        if customer:
            display = customer.name
            ids |= {c.id for c in db.query(Contact.id).filter(Contact.customer_id == customer.id)}
        else:
            c = _find_contact(db, name)
            if c:
                display = c.name
                ids.add(c.id)
        if not ids:
            return {"error": f"No customer/party found matching '{name}'."}
        contact_ids = ids

    out: dict = {"range": f"{from_date}..{to_date or from_date}" if from_date else range, "party": display}

    def block(model, date_col, table, label_fn):
        q = db.query(model).filter(date_col >= start, date_col < end)
        if contact_ids is not None:
            q = q.filter(model.contact_id.in_(contact_ids))
        rows = q.order_by(date_col.desc()).all()
        by_method: dict = {}
        for r in rows:
            by_method[r.method] = money(by_method.get(r.method, 0) + (r.amount or 0))
        items = []
        for r in rows[:cap]:
            items.append({
                "payment_id": r.id,
                "when": _fmt(r.payment_date),
                "amount": r.amount,
                "method": r.method,
                "reference": r.reference or None,
                "for": label_fn(r),
                "recorded_by": r.recorded_by or _first_actor(db, table, r.id) or NOT_RECORDED,
            })
        return {"count": len(rows), "total": money(sum(r.amount or 0 for r in rows)), "by_method": by_method, "listed": items}

    if direction in ("in", "both"):
        out["payments_in"] = block(PaymentIn, PaymentIn.payment_date, "accounting_payments_in",
                                   lambda r: f"Invoice {r.invoice.invoice_number}" if r.invoice else None)
    if direction in ("out", "both"):
        out["payments_out"] = block(PaymentOut, PaymentOut.payment_date, "accounting_payments_out",
                                    lambda r: ("Expense: " + (r.expense.description or r.expense.category)) if r.expense else (f"Bill #{r.purchase_id}" if r.purchase_id else None))
    out["not_stored_by_system"] = [KNOWN_GAPS[0], KNOWN_GAPS[2]]
    return out


def get_audit_history(db: Session, admin: AdminUser, entity: str, record_id: int, limit: int = 30) -> dict:
    """Field-level change history (who changed what, old -> new, when) for
    one accounting record. entity: invoice | sales_order | contact | expense |
    payment_in | payment_out | purchase_order | bill."""
    if not check_permission(db, admin, "accounting", "VIEW"):
        return _denied("accounting")
    table = AUDIT_ENTITY_TABLES.get(entity)
    if not table:
        return {"error": f"Unknown entity '{entity}'. Use one of {sorted(AUDIT_ENTITY_TABLES)}."}
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.table_name == table, AuditLog.record_id == record_id)
        .order_by(AuditLog.changed_at.asc(), AuditLog.id.asc())
        .limit(max(1, min(limit or 30, 60)))
        .all()
    )
    if not rows:
        return {"entity": entity, "record_id": record_id, "count": 0, "note": "No audit history recorded for this record."}
    return {
        "entity": entity,
        "record_id": record_id,
        "count": len(rows),
        "history": [
            {"when": _fmt(r.changed_at), "action": r.action, "field": r.field_name, "old": r.old_value, "new": r.new_value, "by": r.changed_by or NOT_RECORDED}
            for r in rows
        ],
    }


def get_inventory_history(db: Session, admin: AdminUser, plant_name: str = None, range: str = "month", from_date: str = None, to_date: str = None, limit: int = 20) -> dict:
    """Stock movement ledger: sales, reversals (cancel/void), purchases
    received, manual adjustments -- with before/after quantity and who."""
    if not check_permission(db, admin, "products", "VIEW"):
        return _denied("products")
    from app.ai.tools import _find_plant_by_name

    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    q = db.query(InventoryTransaction).filter(InventoryTransaction.created_at >= start, InventoryTransaction.created_at < end)
    plant = None
    if plant_name:
        plant = _find_plant_by_name(db, plant_name)
        if not plant:
            return {"error": f"No plant found matching '{plant_name}'."}
        q = q.filter(InventoryTransaction.plant_id == plant.id)
    rows = q.order_by(InventoryTransaction.created_at.desc()).all()
    sold = sum(r.quantity for r in rows if r.transaction_type == "SALE")
    restored = sum(r.quantity for r in rows if r.transaction_type == "SALE_REVERSAL")
    received = sum(r.quantity for r in rows if r.transaction_type == "PURCHASE_RECEIVED")
    return {
        "plant": plant.name if plant else "all plants",
        "current_stock": plant.stock_quantity if plant else None,
        "movements": len(rows),
        "units_sold": sold,
        "units_restored": restored,
        "units_received": received,
        "recent": [
            {
                "when": _fmt(r.created_at),
                "plant": r.plant.name if r.plant else r.plant_id,
                "type": r.transaction_type,
                "qty": r.quantity,
                "before": r.before_quantity,
                "after": r.after_quantity,
                "source": f"{r.source_type}:{r.source_id}" if r.source_id else r.source_type,
                "by": r.created_by or NOT_RECORDED,
                "notes": r.notes or None,
            }
            for r in rows[: max(1, min(limit or 20, 40))]
        ],
    }


def get_expenses(db: Session, admin: AdminUser, range: str = "month", from_date: str = None, to_date: str = None, category: str = None, limit: int = 15) -> dict:
    if not check_permission(db, admin, "accounting", "VIEW"):
        return _denied("accounting")
    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    q = db.query(Expense).filter(Expense.expense_date >= start, Expense.expense_date < end, Expense.status.notin_(["Voided", "Cancelled"]))
    if category:
        q = q.filter(Expense.category.ilike(f"%{category.strip()}%"))
    rows = q.order_by(Expense.expense_date.desc()).all()
    by_cat: dict = {}
    for r in rows:
        key = r.category or "Uncategorised"
        by_cat[key] = money(by_cat.get(key, 0) + (r.total_amount or 0))
    return {
        "range": f"{from_date}..{to_date or from_date}" if from_date else range,
        "count": len(rows),
        "total": money(sum(r.total_amount or 0 for r in rows)),
        "paid": money(sum(r.amount_paid or 0 for r in rows)),
        "unpaid": money(sum(r.balance_due or 0 for r in rows)),
        "by_category": by_cat,
        "listed": [
            {"expense_id": r.id, "when": _fmt(r.expense_date), "category": r.category, "description": r.description,
             "amount": r.total_amount, "status": r.status, "entered_by": r.created_by or NOT_RECORDED}
            for r in rows[: max(1, min(limit or 15, 25))]
        ],
    }


def get_purchase_summary(db: Session, admin: AdminUser, range: str = "month", from_date: str = None, to_date: str = None, supplier: str = None, limit: int = 15) -> dict:
    """Stock purchases / supplier bills."""
    if not check_permission(db, admin, "products", "VIEW"):
        return _denied("products")
    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    q = db.query(Purchase).filter(Purchase.purchase_date >= start, Purchase.purchase_date < end)
    if supplier:
        q = q.filter(Purchase.supplier.ilike(f"%{supplier.strip()}%"))
    rows = q.order_by(Purchase.purchase_date.desc()).all()
    return {
        "range": f"{from_date}..{to_date or from_date}" if from_date else range,
        "count": len(rows),
        "total_cost": money(sum(r.total_cost or 0 for r in rows)),
        "listed": [
            {"purchase_id": r.id, "when": _fmt(r.purchase_date), "supplier": r.supplier, "invoice_number": r.invoice_number or None,
             "total_cost": r.total_cost, "status": r.status, "entered_by": r.created_by or NOT_RECORDED}
            for r in rows[: max(1, min(limit or 15, 25))]
        ],
    }


def get_deliveries(db: Session, admin: AdminUser, range: str = "today", from_date: str = None, to_date: str = None, status: str = None, driver_name: str = None, vehicle: str = None, customer_name: str = None, limit: int = 15) -> dict:
    """List deliveries by date, optionally filtered by status, driver,
    vehicle (registration or model) or customer. Includes counts per
    status and per driver."""
    if not check_permission(db, admin, "delivery", "VIEW"):
        return _denied("delivery")
    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    q = db.query(Delivery).filter(Delivery.delivery_date >= start, Delivery.delivery_date < end)
    if status:
        q = q.filter(Delivery.status.ilike(status.strip()))
    if driver_name:
        d = _find_driver(db, driver_name)
        if not d:
            return {"error": f"No driver found matching '{driver_name}'."}
        q = q.filter(Delivery.driver_id == d.id)
    if vehicle:
        like = f"%{vehicle.strip()}%"
        v = db.query(Vehicle).filter(Vehicle.registration_number.ilike(like) | Vehicle.name_model.ilike(like)).first()
        if not v:
            return {"error": f"No vehicle found matching '{vehicle}'."}
        q = q.filter(Delivery.vehicle_id == v.id)
    if customer_name:
        ids = [c.id for c in db.query(Contact.id).filter(Contact.name.ilike(f"%{customer_name.strip()}%"))]
        q = q.filter(Delivery.contact_id.in_(ids or [-1]))
    rows = q.order_by(Delivery.delivery_date.asc()).all()
    by_status: dict = {}
    by_driver: dict = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        dn = r.driver.name if r.driver else "Unassigned"
        by_driver[dn] = by_driver.get(dn, 0) + 1
    return {
        "range": f"{from_date}..{to_date or from_date}" if from_date else range,
        "count": len(rows),
        "by_status": by_status,
        "by_driver": by_driver,
        "listed": [
            {"delivery_number": r.delivery_number, "date": _fmt(r.delivery_date), "status": r.status,
             "customer": r.contact.name if r.contact else None, "driver": r.driver.name if r.driver else "Unassigned",
             "vehicle": r.vehicle.registration_number if r.vehicle else None, "created_by": r.created_by or NOT_RECORDED}
            for r in rows[: max(1, min(limit or 15, 25))]
        ],
    }


def get_delivery_timeline(db: Session, admin: AdminUser, delivery_number: str) -> dict:
    """Full history of one delivery (e.g. 'DEL-12' or just 12): creation,
    each driver/vehicle assignment, each status change and completion --
    with who did it."""
    if not check_permission(db, admin, "delivery", "VIEW"):
        return _denied("delivery")
    key = str(delivery_number).strip().upper()
    d = db.query(Delivery).filter(Delivery.delivery_number == key).first()
    if not d and key.isdigit():
        d = db.query(Delivery).filter(Delivery.id == int(key)).first()
    if not d:
        return {"error": f"No delivery found matching '{delivery_number}'."}
    hist = (
        db.query(DeliveryStatusHistory)
        .filter(DeliveryStatusHistory.delivery_id == d.id)
        .order_by(DeliveryStatusHistory.created_at.asc(), DeliveryStatusHistory.id.asc())
        .all()
    )
    names = {x.id: x.name for x in db.query(Driver)}
    vehicles = {x.id: x.registration_number for x in db.query(Vehicle)}

    def label(event, v):
        if v is None:
            return "-"
        if event == "DRIVER_ASSIGNED" and str(v).isdigit():
            return names.get(int(v), v)
        if event == "VEHICLE_ASSIGNED" and str(v).isdigit():
            return vehicles.get(int(v), v)
        return v

    events = [
        {"when": _fmt(h.created_at), "event": h.event, "change": f"{label(h.event, h.old_value)} -> {label(h.event, h.new_value)}",
         "by": h.changed_by or NOT_RECORDED, "remarks": h.remarks or None}
        for h in hist
    ]
    return {
        "delivery_number": d.delivery_number,
        "customer": d.contact.name if d.contact else None,
        "status": d.status,
        "delivery_date": _fmt(d.delivery_date),
        "current_driver": d.driver.name if d.driver else "Unassigned",
        "current_vehicle": d.vehicle.registration_number if d.vehicle else None,
        "created_by": d.created_by or NOT_RECORDED,
        "created_at": _fmt(d.created_at),
        "remarks": d.delivery_remarks or None,
        "items": [f"{i.description} ordered {i.ordered_quantity}, delivered {i.delivered_quantity if i.delivered_quantity is not None else '-'}" for i in d.items],
        "events": events,
        "note": None if events else "No change history recorded for this delivery (it predates audit tracking, or nothing changed after creation).",
        "not_stored_by_system": [KNOWN_GAPS[1], KNOWN_GAPS[3]],
    }


def get_customer_timeline(db: Session, admin: AdminUser, name: str) -> dict:
    """Complete business history of one customer, oldest first: account/
    contact creation, orders, status changes, sales orders, invoices (and
    voids), payments (method, who recorded), stock movements, deliveries
    (driver/vehicle/status history). Sections the admin lacks permission for
    are listed in `sections_hidden_due_to_permissions`; stages the system
    never stored are in `not_stored_by_system`."""
    if not check_permission(db, admin, "customers", "VIEW"):
        return _denied("customers")
    amb = _ambiguous_matches(db, name)
    if amb:
        return _ambiguity_reply(amb)
    customer = _find_customer(db, name)
    contacts: list = []
    if customer:
        contacts = db.query(Contact).filter(Contact.customer_id == customer.id).all()
    else:
        c = _find_contact(db, name)
        if c:
            contacts = [c]
    if not customer and not contacts:
        return {"error": f"No customer found matching '{name}'."}
    display = customer.name if customer else contacts[0].name
    contact_ids = [c.id for c in contacts]

    can_orders = check_permission(db, admin, "orders", "VIEW")
    can_acc = check_permission(db, admin, "accounting", "VIEW")
    can_del = check_permission(db, admin, "delivery", "VIEW")
    can_stock = check_permission(db, admin, "products", "VIEW")
    hidden = [m for m, ok in (("orders", can_orders), ("accounting", can_acc), ("delivery", can_del), ("stock", can_stock)) if not ok]
    events: list = []

    if customer:
        _event(events, customer.created_at, "Website account created", "customer (self-registered)", f"{customer.name}, {customer.mobile or 'no mobile'}")
    for c in contacts:
        if c.source == "offline":
            _event(events, c.created_at, "Offline customer/party created", c.created_by or _first_actor(db, "accounting_contacts", c.id),
                   f"{c.name}, {c.phone or 'no phone'}")

    if can_orders and customer:
        for o in db.query(Order).filter(Order.customer_id == customer.id).order_by(Order.created_at.asc()).limit(25):
            _event(events, o.created_at, f"Online order #{o.id} placed", "customer (website)",
                   f"total {money(o.total_amount)}, {o.payment_method}, items: " + ", ".join(f"{i.plant_name} x{i.quantity}" for i in o.items))
            if o.team_confirmed_at:
                _event(events, o.team_confirmed_at, f"Order #{o.id} team confirmation (delivery feasibility)", o.team_confirmed_by, o.delivery_feasibility)
            for h in o.history:
                _event(events, h.created_at, f"Order #{o.id} status {h.old_status or '-'} -> {h.new_status}", h.updated_by, h.remarks or None)
            if can_stock:
                for t in db.query(InventoryTransaction).filter(
                    InventoryTransaction.source_id == str(o.id),
                    InventoryTransaction.source_type.in_(["ONLINE_ORDER", "ADMIN_CANCEL", "DELIVERY_REJECTED"]),
                ):
                    _event(events, t.created_at, f"Order #{o.id} stock {t.transaction_type}", t.created_by,
                           f"{t.plant.name if t.plant else t.plant_id}: {t.before_quantity} -> {t.after_quantity}")

    if can_acc and contact_ids:
        for so in db.query(SalesOrder).filter(SalesOrder.contact_id.in_(contact_ids), SalesOrder.source == "offline").order_by(SalesOrder.created_at.asc()).limit(25):
            _event(events, so.created_at, f"Sales order {so.order_number} created", so.created_by or _first_actor(db, "accounting_sales_orders", so.id),
                   f"total {money(so.total_amount)}, items: " + ", ".join(f"{i.description} x{i.quantity}" for i in so.items))
            if can_stock:
                for t in db.query(InventoryTransaction).filter(
                    InventoryTransaction.source_id == str(so.id),
                    InventoryTransaction.source_type.in_(["SALES_ORDER", "SALES_ORDER_VOID"]),
                ):
                    _event(events, t.created_at, f"Sales order {so.order_number} stock {t.transaction_type}", t.created_by,
                           f"{t.plant.name if t.plant else t.plant_id}: {t.before_quantity} -> {t.after_quantity}")
        for inv in db.query(Invoice).filter(Invoice.contact_id.in_(contact_ids), Invoice.source == "offline").order_by(Invoice.created_at.asc()).limit(25):
            _event(events, inv.created_at, f"Invoice {inv.invoice_number} created", _first_actor(db, "accounting_invoices", inv.id),
                   f"total {money(inv.total_amount)}, paid {money(inv.amount_paid)}, balance {money(inv.balance_due)}, status {inv.status}")
            if inv.status == "Voided":
                vrow = (
                    db.query(AuditLog)
                    .filter(AuditLog.table_name == "accounting_invoices", AuditLog.record_id == inv.id, AuditLog.action == "void")
                    .order_by(AuditLog.changed_at.desc())
                    .first()
                )
                when = inv.voided_at or (vrow.changed_at if vrow else None)
                if when:
                    _event(events, when, f"Invoice {inv.invoice_number} voided", inv.voided_by or (vrow.changed_by if vrow else None), None)
        for p in db.query(PaymentIn).filter(PaymentIn.contact_id.in_(contact_ids)).order_by(PaymentIn.payment_date.asc()).limit(40):
            _event(events, p.payment_date, f"Payment {money(p.amount)} via {p.method}", p.recorded_by or _first_actor(db, "accounting_payments_in", p.id),
                   f"invoice {p.invoice.invoice_number if p.invoice else '-'}, ref {p.reference or '-'}")

    if can_del and contact_ids:
        names = {x.id: x.name for x in db.query(Driver)}
        vehicles = {x.id: x.registration_number for x in db.query(Vehicle)}

        def lab(ev, v):
            if v is not None and str(v).isdigit() and ev == "DRIVER_ASSIGNED":
                return names.get(int(v), v)
            if v is not None and str(v).isdigit() and ev == "VEHICLE_ASSIGNED":
                return vehicles.get(int(v), v)
            return v if v is not None else "-"

        for d in db.query(Delivery).filter(Delivery.contact_id.in_(contact_ids)).order_by(Delivery.created_at.asc()).limit(15):
            _event(events, d.created_at, f"Delivery {d.delivery_number} created", d.created_by,
                   f"now {d.status}, driver {d.driver.name if d.driver else 'unassigned'}, vehicle {d.vehicle.registration_number if d.vehicle else '-'}")
            for h in db.query(DeliveryStatusHistory).filter(DeliveryStatusHistory.delivery_id == d.id).order_by(DeliveryStatusHistory.created_at.asc()):
                if h.event == "CREATED":
                    continue
                _event(events, h.created_at, f"Delivery {d.delivery_number} {h.event}", h.changed_by,
                       f"{lab(h.event, h.old_value)} -> {lab(h.event, h.new_value)}" + (f" ({h.remarks})" if h.remarks else ""))

    events.sort(key=lambda e: e["_t"])
    truncated = len(events) > 80
    events = events[:80]
    for e in events:
        e.pop("_t")
    return {
        "customer_name": display,
        "channels": sorted(({"online"} if customer else set()) | {c.source for c in contacts}),
        "event_count": len(events),
        "truncated": truncated,
        "events": events,
        "sections_hidden_due_to_permissions": hidden,
        "not_stored_by_system": KNOWN_GAPS,
    }


def get_admin_activity(db: Session, admin: AdminUser, username: str = None, range: str = "today", from_date: str = None, to_date: str = None, limit: int = 20) -> dict:
    """What admins did (order actions, role/permission changes, ...) from the
    admin activity log. Restricted to users with the Users & Roles
    permission."""
    if not check_permission(db, admin, "users_roles", "VIEW"):
        return _denied("users & roles")
    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    q = db.query(AdminActivityLog).filter(AdminActivityLog.created_at >= start, AdminActivityLog.created_at < end)
    if username:
        q = q.filter(AdminActivityLog.admin_username.ilike(username.strip()))
    rows = q.order_by(AdminActivityLog.created_at.desc()).all()
    by_action: dict = {}
    for r in rows:
        by_action[r.action] = by_action.get(r.action, 0) + 1
    return {
        "count": len(rows),
        "by_action": by_action,
        "recent": [
            {"when": _fmt(r.created_at), "admin": r.admin_username, "action": r.action, "detail": (r.detail or "")[:160]}
            for r in rows[: max(1, min(limit or 20, 30))]
        ],
    }


# ---------- Fraud / anomaly ("is an employee doing something suspicious") ----------

def get_admin_risk_summary(db: Session, admin: AdminUser, username: str = None, range: str = "month", from_date: str = None, to_date: str = None) -> dict:
    """Per-admin activity that's worth a second look: invoices voided,
    orders cancelled, manual stock adjustments, price overrides below
    catalog price, failed login attempts. Not proof of wrongdoing by
    itself -- a high count is a prompt to go look at the actual records,
    not an accusation."""
    if not check_permission(db, admin, "users_roles", "VIEW"):
        return _denied("users & roles")
    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}

    def grouped(q, col):
        rows = q.all()
        out: dict = {}
        for name, *_ in rows:
            out[name or NOT_RECORDED] = out.get(name or NOT_RECORDED, 0) + 1
        return out

    voids = dict(
        db.query(AuditLog.changed_by, func.count(AuditLog.id))
        .filter(AuditLog.table_name == "accounting_invoices", AuditLog.action == "void",
                AuditLog.changed_at >= start, AuditLog.changed_at < end)
        .group_by(AuditLog.changed_by).all()
    )
    cancellations = dict(
        db.query(OrderStatusHistory.updated_by, func.count(OrderStatusHistory.id))
        .filter(OrderStatusHistory.new_status == "Cancelled", OrderStatusHistory.created_at >= start, OrderStatusHistory.created_at < end)
        .group_by(OrderStatusHistory.updated_by).all()
    )
    adjustments = dict(
        db.query(InventoryTransaction.created_by, func.count(InventoryTransaction.id))
        .filter(InventoryTransaction.transaction_type == "MANUAL_ADJUSTMENT", InventoryTransaction.created_at >= start, InventoryTransaction.created_at < end)
        .group_by(InventoryTransaction.created_by).all()
    )
    failed_logins = dict(
        db.query(LoginAttempt.identifier, func.count(LoginAttempt.id))
        .filter(LoginAttempt.success.is_(False), LoginAttempt.created_at >= start, LoginAttempt.created_at < end)
        .group_by(LoginAttempt.identifier).all()
    )
    overrides = _price_override_rows(db, start, end)
    override_by_admin: dict = {}
    for r in overrides:
        override_by_admin[r["created_by"]] = override_by_admin.get(r["created_by"], 0) + 1

    admins = set(voids) | set(cancellations) | set(adjustments) | set(override_by_admin)
    admins.discard(None)
    admins.discard("")
    if username:
        admins = {a for a in admins if a.lower() == username.strip().lower()}

    summary = []
    for a in sorted(admins):
        summary.append({
            "admin": a,
            "invoices_voided": voids.get(a, 0),
            "orders_cancelled": cancellations.get(a, 0),
            "manual_stock_adjustments": adjustments.get(a, 0),
            "price_overrides": override_by_admin.get(a, 0),
        })
    summary.sort(key=lambda r: sum(v for k, v in r.items() if k != "admin"), reverse=True)

    return {
        "range": f"{from_date}..{to_date or from_date}" if from_date else range,
        "by_admin": summary,
        "failed_logins_by_identifier": failed_logins,
        "note": "High numbers are a prompt to review the actual records (get_audit_history, get_price_overrides, get_order_timeline), not proof of a problem.",
    }


def _price_override_rows(db: Session, start, end, threshold_percent: float = 10.0) -> list:
    from app.accounting.models import SalesOrderItem

    rows = []
    for item, so in (
        db.query(SalesOrderItem, SalesOrder)
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.sales_order_id)
        .filter(SalesOrderItem.plant_id.isnot(None), SalesOrder.created_at >= start, SalesOrder.created_at < end)
        .all()
    ):
        plant = db.query(Plant).filter(Plant.id == item.plant_id).first()
        if not plant or not plant.price:
            continue
        diff_pct = (plant.price - item.unit_price) / plant.price * 100
        if diff_pct >= threshold_percent:
            rows.append({
                "sales_order": so.order_number,
                "when": _fmt(so.created_at),
                "plant": plant.name,
                "catalog_price": plant.price,
                "sold_at": item.unit_price,
                "discount_percent": round(diff_pct, 1),
                "created_by": so.created_by or _first_actor(db, "accounting_sales_orders", so.id) or NOT_RECORDED,
            })
    return rows


def get_price_overrides(db: Session, admin: AdminUser, range: str = "month", from_date: str = None, to_date: str = None, threshold_percent: float = 10.0, limit: int = 20) -> dict:
    """Offline sales order lines sold noticeably below the plant's catalog
    price -- a manually-typed unit_price, not validated against the
    catalog. Useful to check an employee isn't under-billing."""
    if not check_permission(db, admin, "accounting", "VIEW"):
        return _denied("accounting")
    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    rows = _price_override_rows(db, start, end, threshold_percent)
    rows.sort(key=lambda r: r["discount_percent"], reverse=True)
    return {
        "range": f"{from_date}..{to_date or from_date}" if from_date else range,
        "threshold_percent": threshold_percent,
        "count": len(rows),
        "listed": rows[: max(1, min(limit or 20, 30))],
    }


def get_failed_logins(db: Session, admin: AdminUser, username: str = None, range: str = "week", from_date: str = None, to_date: str = None, limit: int = 20) -> dict:
    """Failed login attempts (wrong password, unknown user, locked,
    inactive) -- across admin and customer logins alike."""
    if not check_permission(db, admin, "users_roles", "VIEW"):
        return _denied("users & roles")
    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    q = db.query(LoginAttempt).filter(LoginAttempt.created_at >= start, LoginAttempt.created_at < end, LoginAttempt.success.is_(False))
    if username:
        q = q.filter(LoginAttempt.identifier.ilike(f"%{username.strip()}%"))
    rows = q.order_by(LoginAttempt.created_at.desc()).all()
    by_identifier: dict = {}
    for r in rows:
        by_identifier[r.identifier] = by_identifier.get(r.identifier, 0) + 1
    return {
        "range": f"{from_date}..{to_date or from_date}" if from_date else range,
        "count": len(rows),
        "by_identifier": by_identifier,
        "listed": [
            {"when": _fmt(r.created_at), "identifier": r.identifier, "ip": r.ip_address, "reason": r.reason}
            for r in rows[: max(1, min(limit or 20, 30))]
        ],
    }


def get_voided_invoices(db: Session, admin: AdminUser, range: str = "month", from_date: str = None, to_date: str = None, limit: int = 20) -> dict:
    """All invoices voided in a period, with who voided each one and the
    amount -- use to review void activity across all admins at once."""
    if not check_permission(db, admin, "accounting", "VIEW"):
        return _denied("accounting")
    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    rows = (
        db.query(Invoice)
        .filter(Invoice.status == "Voided", Invoice.voided_at.isnot(None), Invoice.voided_at >= start, Invoice.voided_at < end)
        .order_by(Invoice.voided_at.desc())
        .all()
    )
    by_admin: dict = {}
    for r in rows:
        by_admin[r.voided_by or NOT_RECORDED] = by_admin.get(r.voided_by or NOT_RECORDED, 0) + 1
    return {
        "range": f"{from_date}..{to_date or from_date}" if from_date else range,
        "count": len(rows),
        "total_amount": money(sum(r.total_amount or 0 for r in rows)),
        "by_admin": by_admin,
        "listed": [
            {"invoice_number": r.invoice_number, "customer": r.contact.name if r.contact else None,
             "amount": r.total_amount, "voided_by": r.voided_by or NOT_RECORDED, "voided_at": _fmt(r.voided_at)}
            for r in rows[: max(1, min(limit or 20, 30))]
        ],
    }


def get_stock_adjustments(db: Session, admin: AdminUser, username: str = None, range: str = "month", from_date: str = None, to_date: str = None, limit: int = 20) -> dict:
    """Manual stock adjustments (not a sale/purchase/order) -- who
    adjusted what, by how much, and any note given."""
    if not check_permission(db, admin, "products", "VIEW"):
        return _denied("products")
    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    q = db.query(InventoryTransaction).filter(
        InventoryTransaction.transaction_type == "MANUAL_ADJUSTMENT",
        InventoryTransaction.created_at >= start, InventoryTransaction.created_at < end,
    )
    if username:
        q = q.filter(InventoryTransaction.created_by.ilike(f"%{username.strip()}%"))
    rows = q.order_by(InventoryTransaction.created_at.desc()).all()
    by_admin: dict = {}
    for r in rows:
        by_admin[r.created_by or NOT_RECORDED] = by_admin.get(r.created_by or NOT_RECORDED, 0) + 1
    return {
        "range": f"{from_date}..{to_date or from_date}" if from_date else range,
        "count": len(rows),
        "by_admin": by_admin,
        "listed": [
            {"when": _fmt(r.created_at), "plant": r.plant.name if r.plant else r.plant_id, "qty": r.quantity,
             "before": r.before_quantity, "after": r.after_quantity, "by": r.created_by or NOT_RECORDED, "notes": r.notes or None}
            for r in rows[: max(1, min(limit or 20, 30))]
        ],
    }


# ---------- Labour & Payroll ----------

def get_attendance_summary(db: Session, admin: AdminUser, worker_name: str = None, range: str = "week", from_date: str = None, to_date: str = None, limit: int = 20) -> dict:
    """Attendance for monthly-salary employees and daily-wage labour --
    present/absent/overtime counts, optionally for one worker by name."""
    if not check_permission(db, admin, "labour", "VIEW"):
        return _denied("labour")
    from app.labour.models import EmployeeAttendance, Labour, LabourAttendance

    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    rows = []
    eq = db.query(EmployeeAttendance).filter(EmployeeAttendance.attendance_date >= start, EmployeeAttendance.attendance_date < end)
    lq = db.query(LabourAttendance).filter(LabourAttendance.attendance_date >= start, LabourAttendance.attendance_date < end)
    if worker_name:
        emp_ids = [e.id for e in db.query(Employee.id).filter(Employee.name.ilike(f"%{worker_name.strip()}%"))]
        lab_ids = [l.id for l in db.query(Labour.id).filter(Labour.name.ilike(f"%{worker_name.strip()}%"))]
        eq = eq.filter(EmployeeAttendance.employee_id.in_(emp_ids or [-1]))
        lq = lq.filter(LabourAttendance.labour_id.in_(lab_ids or [-1]))
    emp_names = {e.id: e.name for e in db.query(Employee)}
    lab_names = {l.id: l.name for l in db.query(Labour)}
    for r in eq.all():
        rows.append({"who": emp_names.get(r.employee_id, "Unknown"), "type": "employee", "date": _fmt(r.attendance_date), "status": r.status, "overtime_hours": r.overtime_hours, "amount": None})
    for r in lq.all():
        rows.append({"who": lab_names.get(r.labour_id, "Unknown"), "type": "labour", "date": _fmt(r.attendance_date), "status": r.status, "overtime_hours": r.overtime_hours, "amount": r.earned_amount})
    by_status: dict = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return {
        "range": f"{from_date}..{to_date or from_date}" if from_date else range,
        "count": len(rows),
        "by_status": by_status,
        "listed": rows[: max(1, min(limit or 20, 30))],
    }


def get_payroll_summary(db: Session, admin: AdminUser, year: int = None, month: int = None, worker_name: str = None, limit: int = 20) -> dict:
    """Payroll rows (monthly salary/wage calculation) -- gross, advance
    recovery, deductions, net payable, status (Draft/Finalized), and who
    generated/finalized each one."""
    if not check_permission(db, admin, "labour", "VIEW"):
        return _denied("labour")
    from app.labour.models import Labour, Payroll

    now = now_ist()
    year = year or now.year
    month = month or now.month
    q = db.query(Payroll).filter(Payroll.period_year == year, Payroll.period_month == month)
    emp_names = {e.id: e.name for e in db.query(Employee)}
    lab_names = {l.id: l.name for l in db.query(Labour)}
    rows = q.all()
    if worker_name:
        key = worker_name.strip().lower()
        rows = [r for r in rows if key in (emp_names.get(r.employee_id, "") or lab_names.get(r.labour_id, "")).lower()]
    return {
        "period": f"{year}-{month:02d}",
        "count": len(rows),
        "total_net_payable": money(sum(r.net_payable or 0 for r in rows)),
        "listed": [
            {
                "worker": emp_names.get(r.employee_id) or lab_names.get(r.labour_id) or "Unknown",
                "worker_type": r.worker_type, "gross_earnings": r.gross_earnings, "advance_recovery": r.advance_recovery,
                "deductions": r.deductions, "net_payable": r.net_payable, "status": r.status,
                "generated_by": r.generated_by or NOT_RECORDED, "finalized_by": r.finalized_by or None,
            }
            for r in rows[: max(1, min(limit or 20, 30))]
        ],
    }


def get_worker_advances(db: Session, admin: AdminUser, worker_name: str = None, range: str = "month", from_date: str = None, to_date: str = None, limit: int = 20) -> dict:
    """Advances (loans) given to employees/labour, who gave it and why,
    and outstanding balance after recoveries."""
    if not check_permission(db, admin, "labour", "VIEW"):
        return _denied("labour")
    from app.labour.models import AdvanceRecovery, Labour, WorkerAdvance

    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    q = db.query(WorkerAdvance).filter(WorkerAdvance.advance_date >= start, WorkerAdvance.advance_date < end)
    emp_names = {e.id: e.name for e in db.query(Employee)}
    lab_names = {l.id: l.name for l in db.query(Labour)}
    rows = q.order_by(WorkerAdvance.advance_date.desc()).all()
    if worker_name:
        key = worker_name.strip().lower()
        rows = [r for r in rows if key in (emp_names.get(r.employee_id) or lab_names.get(r.labour_id) or "").lower()]
    listed = []
    for r in rows[: max(1, min(limit or 20, 30))]:
        recovered = db.query(func.coalesce(func.sum(AdvanceRecovery.amount), 0)).filter(AdvanceRecovery.advance_id == r.id).scalar() or 0
        listed.append({
            "worker": emp_names.get(r.employee_id) or lab_names.get(r.labour_id) or "Unknown",
            "amount": r.amount, "recovered": money(recovered), "outstanding": money(r.amount - recovered),
            "reason": r.reason or None, "given_by": r.created_by or NOT_RECORDED, "when": _fmt(r.advance_date),
        })
    return {
        "range": f"{from_date}..{to_date or from_date}" if from_date else range,
        "count": len(rows),
        "total_given": money(sum(r.amount or 0 for r in rows)),
        "listed": listed,
    }


# ---------- Communications (WhatsApp) ----------

def get_whatsapp_activity(db: Session, admin: AdminUser, status: str = None, range: str = "today", from_date: str = None, to_date: str = None, limit: int = 20) -> dict:
    """WhatsApp notifications sent to customers/drivers -- counts by
    status (sent/delivered/read/failed) and the failed ones with error."""
    if not check_permission(db, admin, "communications", "VIEW"):
        return _denied("communications")
    from app.communications.models import WhatsAppMessage

    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    q = db.query(WhatsAppMessage).filter(WhatsAppMessage.created_at >= start, WhatsAppMessage.created_at < end)
    if status:
        q = q.filter(WhatsAppMessage.status == status.strip().upper())
    rows = q.order_by(WhatsAppMessage.created_at.desc()).all()
    by_status: dict = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    failed = [r for r in rows if r.status == "FAILED"][: max(1, min(limit or 20, 30))]
    return {
        "range": f"{from_date}..{to_date or from_date}" if from_date else range,
        "count": len(rows),
        "by_status": by_status,
        "failed_messages": [
            {"when": _fmt(r.created_at), "to": r.customer_name or r.mobile, "template": r.template_name, "error": r.error_message or r.error_code or None}
            for r in failed
        ],
    }


# ---------- Website content (simple counts) ----------

def get_website_content_summary(db: Session, admin: AdminUser) -> dict:
    """Quick counts of website-facing content -- categories, plants
    (active/inactive), services, testimonials, blog posts, FAQs, pricing
    plans, gallery images, reviews."""
    if not check_permission(db, admin, "website", "VIEW"):
        return _denied("website")
    from app.models import FAQ, BlogPost, GalleryImage, PlantReview, PricingPlan, Service, Testimonial

    active_plants = db.query(func.count(Plant.id)).filter(Plant.is_active.is_(True)).scalar() or 0
    total_plants = db.query(func.count(Plant.id)).scalar() or 0
    return {
        "categories": db.query(func.count(Category.id)).scalar() or 0,
        "plants_active": active_plants,
        "plants_total": total_plants,
        "services": db.query(func.count(Service.id)).scalar() or 0,
        "testimonials": db.query(func.count(Testimonial.id)).scalar() or 0,
        "blog_posts": db.query(func.count(BlogPost.id)).scalar() or 0,
        "faqs": db.query(func.count(FAQ.id)).scalar() or 0,
        "pricing_plans": db.query(func.count(PricingPlan.id)).scalar() or 0,
        "gallery_images": db.query(func.count(GalleryImage.id)).scalar() or 0,
        "plant_reviews": db.query(func.count(PlantReview.id)).scalar() or 0,
    }


# ---------- Customer activity ----------

def get_customer_activity(db: Session, admin: AdminUser, name: str, limit: int = 20) -> dict:
    """Website login/activity log for one customer (the Customer Logs
    page) -- separate from purchase history."""
    if not check_permission(db, admin, "customers", "VIEW"):
        return _denied("customers")
    amb = _ambiguous_matches(db, name)
    if amb:
        return _ambiguity_reply(amb)
    customer = _find_customer(db, name)
    if not customer:
        return {"error": f"No customer found matching '{name}'."}
    rows = (
        db.query(CustomerActivityLog)
        .filter(CustomerActivityLog.customer_id == customer.id)
        .order_by(CustomerActivityLog.created_at.desc())
        .limit(max(1, min(limit or 20, 30)))
        .all()
    )
    return {
        "customer_name": customer.name,
        "count": len(rows),
        "activity": [{"when": _fmt(r.created_at), "action": r.action} for r in rows],
    }


def get_billing_audit(db: Session, admin: AdminUser, range: str = "month", from_date: str = None, to_date: str = None, limit: int = 20) -> dict:
    """Checks every offline invoice in the period for numbers that don't
    add up: line items vs invoice total, recorded payments vs amount_paid,
    balance_due vs total-minus-paid, and status that contradicts the
    balance. Use for 'bill match nahi ho raha', 'saare bills check karo'."""
    if not check_permission(db, admin, "accounting", "VIEW"):
        return _denied("accounting")
    start, end, err = _range(range, from_date, to_date)
    if err:
        return {"error": err}
    invoices = (
        db.query(Invoice)
        .filter(Invoice.invoice_date >= start, Invoice.invoice_date < end, Invoice.status != "Voided")
        .order_by(Invoice.invoice_date.desc())
        .limit(500)
        .all()
    )
    issues = []
    for inv in invoices:
        found = []
        items_total = round(sum(i.line_total or 0 for i in inv.items), 2)
        expected_total = round((inv.subtotal or 0) + (inv.tax_total or 0) - (inv.discount_total or 0), 2)
        if inv.items and abs(items_total - (inv.subtotal or 0)) > 0.01:
            found.append(f"line items add up to {items_total} but invoice subtotal is {inv.subtotal}")
        if abs(expected_total - (inv.total_amount or 0)) > 0.01:
            found.append(f"subtotal+tax-discount = {expected_total} but total_amount is {inv.total_amount}")
        paid = round(sum(p.amount or 0 for p in inv.payments), 2)
        if abs(paid - (inv.amount_paid or 0)) > 0.01:
            found.append(f"payments recorded add up to {paid} but amount_paid shows {inv.amount_paid}")
        expected_balance = round(max((inv.total_amount or 0) - paid, 0), 2)
        if abs(expected_balance - (inv.balance_due or 0)) > 0.01:
            found.append(f"balance_due is {inv.balance_due} but total minus payments = {expected_balance}")
        if inv.status == "Paid" and (inv.balance_due or 0) > 0.01:
            found.append(f"status is Paid but balance_due is {inv.balance_due}")
        if inv.sales_order and abs((inv.sales_order.total_amount or 0) - (inv.total_amount or 0)) > 0.01:
            found.append(f"invoice total {inv.total_amount} differs from its sales order total {inv.sales_order.total_amount}")
        if found:
            issues.append({
                "invoice_id": inv.id,
                "invoice_number": inv.invoice_number,
                "customer": inv.contact.name if inv.contact else None,
                "date": _fmt(inv.invoice_date),
                "problems": found,
            })
    return {
        "range": f"{from_date}..{to_date or from_date}" if from_date else range,
        "invoices_checked": len(invoices),
        "invoices_with_problems": len(issues),
        "listed": issues[: max(1, min(limit or 20, 30))],
        "note": "Only offline/accounting invoices are checked; none found means every checked invoice's numbers are internally consistent.",
    }


# name -> function. Every function's first two params are always (db, admin)
# -- execute_admin_tool below injects both itself; the model-supplied
# arguments can never override either one.
ADMIN_TOOLS = {
    "get_sales_summary": get_sales_summary,
    "get_customers_who_purchased": get_customers_who_purchased,
    "get_top_selling_plants": get_top_selling_plants,
    "get_pending_orders": get_pending_orders,
    "get_order_details": get_order_details,
    "search_customer": search_customer,
    "get_customer_purchase_history": get_customer_purchase_history,
    "get_customer_outstanding": get_customer_outstanding,
    "get_low_stock_plants": get_low_stock_plants,
    "get_pending_deliveries": get_pending_deliveries,
    "get_driver_details": get_driver_details,
    "get_customer_invoices": get_customer_invoices,
    "get_employee_details": get_employee_details,
    "get_inquiries": get_inquiries,
    "get_customer_counts": get_customer_counts,
    "get_business_summary": get_business_summary,
    "get_order_timeline": get_order_timeline,
    "get_payment_history": get_payment_history,
    "get_audit_history": get_audit_history,
    "get_inventory_history": get_inventory_history,
    "get_expenses": get_expenses,
    "get_purchase_summary": get_purchase_summary,
    "get_deliveries": get_deliveries,
    "get_delivery_timeline": get_delivery_timeline,
    "get_customer_timeline": get_customer_timeline,
    "get_admin_activity": get_admin_activity,
    "get_admin_risk_summary": get_admin_risk_summary,
    "get_price_overrides": get_price_overrides,
    "get_failed_logins": get_failed_logins,
    "get_voided_invoices": get_voided_invoices,
    "get_stock_adjustments": get_stock_adjustments,
    "get_attendance_summary": get_attendance_summary,
    "get_payroll_summary": get_payroll_summary,
    "get_worker_advances": get_worker_advances,
    "get_whatsapp_activity": get_whatsapp_activity,
    "get_website_content_summary": get_website_content_summary,
    "get_customer_activity": get_customer_activity,
    "get_billing_audit": get_billing_audit,
}

ADMIN_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_sales_summary",
            "description": "Get total sales (online + offline) for a date range, optionally filtered to just one channel. Use for 'today's sales', 'this month's sales', and follow-ups like 'online?' or 'offline?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "range": {"type": "string", "enum": ["today", "week", "month", "last_month", "year", "last_year"], "description": "Defaults to 'today'"},
                    "channel": {"type": "string", "enum": ["all", "online", "offline"], "description": "Defaults to 'all'"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customers_who_purchased",
            "description": "List which customers purchased (online and offline) during a date range, with the products each one bought. Use for 'aaj kin customers ne kya khareeda', 'today's customers', 'who bought what today'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "range": {"type": "string", "enum": ["today", "week", "month", "last_month", "year", "last_year"]},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_selling_plants",
            "description": "Get the best-selling plants by quantity for a date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "range": {"type": "string", "enum": ["today", "week", "month", "last_month", "year", "last_year"]},
                    "limit": {"type": "integer", "description": "How many to return, default 5"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pending_orders",
            "description": "List orders that are not yet Delivered or Cancelled.",
            "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_details",
            "description": "Get full details (items, status, payment, delivery) for one order by its numeric Order ID.",
            "parameters": {"type": "object", "properties": {"order_id": {"type": "integer"}}, "required": ["order_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_customer",
            "description": "Search for a customer by name to find their ID/mobile/email.",
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_purchase_history",
            "description": "Get a customer's order history by name -- last purchase date, total spent, and what they bought. Use `months` to scope to a recent window (e.g. 6 for 'last 6 months').",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "months": {"type": "integer"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_outstanding",
            "description": "Get how much a customer currently owes (unpaid invoice balance).",
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_low_stock_plants",
            "description": "List plants that are low on stock.",
            "parameters": {"type": "object", "properties": {"threshold": {"type": "integer"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pending_deliveries",
            "description": "List deliveries that haven't been completed yet.",
            "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_driver_details",
            "description": "Get full profile and delivery performance for one driver by name -- phone, address, assigned vehicle, total/completed/pending deliveries, recent delivery list.",
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_invoices",
            "description": "Get a customer's bills/invoices by name -- invoice number, status, amount, items, paid/balance. Works for website customers and offline/walk-in customers alike.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_employee_details",
            "description": "Get full profile for one employee by name -- role, department, contact info, status, salary, joining date. (Bank account details are never included.)",
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_business_summary",
            "description": "Get a quick overall snapshot: total sales, pending orders, pending deliveries, low stock count, for a date range.",
            "parameters": {"type": "object", "properties": {"range": {"type": "string", "enum": ["today", "week", "month"]}}},
        },
    },
    {"type": "function", "function": {"name": "get_order_timeline", "description": "Who did what on an online order and when (placed, acknowledged, team-confirmed, every status change + actor, rejection reason, stock moves).", "parameters": {"type": "object", "properties": {"order_id": {"type": "integer"}}, "required": ["order_id"]}}},
    {"type": "function", "function": {"name": "get_customer_timeline", "description": "Complete history of ONE customer oldest-first: creation (+who), orders, sales orders, invoices/voids, payments (+who recorded), stock moves, deliveries (+driver/vehicle changes). Use for 'complete history/timeline' questions.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "get_payment_history", "description": "Payments received/paid out for a period, optionally for one customer: totals by method (cash/UPI/...), who recorded each.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "direction": {"type": "string", "enum": ["in", "out", "both"]}, "range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_audit_history", "description": "Field-level change history (who changed what, old->new) of one accounting record by id.", "parameters": {"type": "object", "properties": {"entity": {"type": "string", "enum": ["invoice", "sales_order", "contact", "expense", "payment_in", "payment_out", "purchase_order", "bill"]}, "record_id": {"type": "integer"}}, "required": ["entity", "record_id"]}}},
    {"type": "function", "function": {"name": "get_inventory_history", "description": "Stock movement ledger (sold, restored, received, adjusted; before/after; who) for a plant or all plants.", "parameters": {"type": "object", "properties": {"plant_name": {"type": "string"}, "range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_expenses", "description": "Expenses total/paid/unpaid, by category, list with who entered.", "parameters": {"type": "object", "properties": {"range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}, "category": {"type": "string"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_purchase_summary", "description": "Stock purchases / supplier bills for a period, optionally by supplier.", "parameters": {"type": "object", "properties": {"range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}, "supplier": {"type": "string"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_deliveries", "description": "List deliveries for a date, filter by status/driver/vehicle/customer; counts per status and per driver.", "parameters": {"type": "object", "properties": {"range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}, "status": {"type": "string"}, "driver_name": {"type": "string"}, "vehicle": {"type": "string"}, "customer_name": {"type": "string"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_delivery_timeline", "description": "History of one delivery by number (e.g. DEL-12): creation, driver/vehicle assignment, status changes, completion, each with who.", "parameters": {"type": "object", "properties": {"delivery_number": {"type": "string"}}, "required": ["delivery_number"]}}},
    {"type": "function", "function": {"name": "get_admin_activity", "description": "What admins did (activity log) for a period, optionally one admin username. Needs Users & Roles permission.", "parameters": {"type": "object", "properties": {"username": {"type": "string"}, "range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_customer_counts", "description": "How many customers exist: online (website accounts) vs offline-only (walk-in/manual contacts), and the total. Use for 'kitne online customer hai', 'total customers kitne hain'.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_inquiries", "description": "Website contact/product enquiries: who asked, about which plant, when, and reply status (new/replied). Use for 'kisi customer ki enquiry aayi', 'naye enquiries'.", "parameters": {"type": "object", "properties": {"range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}, "status": {"type": "string", "description": "'new' or 'replied'"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_admin_risk_summary", "description": "Per-admin activity worth reviewing: invoices voided, orders cancelled, manual stock adjustments, price overrides, failed logins. Use for 'koi employee gadbadi toh nahi kar raha', 'suspicious activity', 'kisne zyada cancel/void kiye'.", "parameters": {"type": "object", "properties": {"username": {"type": "string"}, "range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}}}}},
    {"type": "function", "function": {"name": "get_price_overrides", "description": "Offline sales lines sold notably below the plant's catalog price (possible under-billing) -- who sold it and by how much.", "parameters": {"type": "object", "properties": {"range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}, "threshold_percent": {"type": "number"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_failed_logins", "description": "Failed login attempts (wrong password/unknown user/locked/inactive), optionally for one username. Security check.", "parameters": {"type": "object", "properties": {"username": {"type": "string"}, "range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_voided_invoices", "description": "All invoices voided in a period across all admins, with who voided each and the amount.", "parameters": {"type": "object", "properties": {"range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_stock_adjustments", "description": "Manual stock adjustments (not sale/purchase) -- who adjusted what plant, by how much, any note.", "parameters": {"type": "object", "properties": {"username": {"type": "string"}, "range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_attendance_summary", "description": "Attendance for salaried employees and daily-wage labour -- present/absent/overtime, optionally for one worker by name.", "parameters": {"type": "object", "properties": {"worker_name": {"type": "string"}, "range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_payroll_summary", "description": "Monthly payroll: gross earnings, advance recovery, deductions, net payable, status, who generated/finalized -- for a year/month, optionally one worker.", "parameters": {"type": "object", "properties": {"year": {"type": "integer"}, "month": {"type": "integer"}, "worker_name": {"type": "string"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_worker_advances", "description": "Advances/loans given to employees or labour -- amount, reason, who gave it, recovered vs outstanding.", "parameters": {"type": "object", "properties": {"worker_name": {"type": "string"}, "range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_whatsapp_activity", "description": "WhatsApp notification activity -- counts by status (sent/delivered/read/failed) and failed messages with their error.", "parameters": {"type": "object", "properties": {"status": {"type": "string"}, "range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "get_website_content_summary", "description": "Quick counts of website content: categories, plants, services, testimonials, blog posts, FAQs, pricing plans, gallery images, reviews.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_customer_activity", "description": "Website login/activity log for one customer by name (separate from purchase history).", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "get_billing_audit", "description": "Audit all invoices in a period for numbers that don't match (items vs total, payments vs amount paid, balance, status). Use for 'bill proper match nahi ho raha', 'saare bills khud check karo', 'accounts mein gadbad'.", "parameters": {"type": "object", "properties": {"range": {"type": "string", "enum": ["today", "yesterday", "day_before_yesterday", "last_7_days", "last_30_days", "week", "month", "last_month", "year", "last_year"]}, "from_date": {"type": "string", "description": "YYYY-MM-DD; overrides range"}, "to_date": {"type": "string", "description": "YYYY-MM-DD, with from_date"}, "limit": {"type": "integer"}}}}},
]


def execute_admin_tool(db: Session, admin: AdminUser, name: str, arguments: dict) -> dict:
    """Whitelisted dispatcher, same shape as the customer tools.py's
    execute_tool(). `admin` always comes from the gateway's own session
    lookup -- any `admin`/`db` keys the model tries to pass as arguments
    are stripped before the call, so a crafted prompt can never swap in a
    different admin's identity."""
    func_ = ADMIN_TOOLS.get(name)
    if not func_:
        return {"error": f"Unknown tool '{name}'."}
    args = {k: v for k, v in (arguments or {}).items() if k not in ("db", "admin")}
    try:
        return func_(db, admin, **args)
    except TypeError as exc:
        return {"error": f"Invalid arguments for {name}: {exc}"}
