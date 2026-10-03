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

from app.accounting.models import Contact, Employee, Invoice, SalesOrder
from app.analytics_utils import money, now_ist, resolve_date_range, to_utc
from app.delivery.models import Delivery, Driver, DeliveryTrip
from app.models import AdminUser, Category, Customer, Order, OrderItem, Plant
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

def get_sales_summary(db: Session, admin: AdminUser, range: str = "today", channel: str = "all") -> dict:
    """channel: 'all' | 'online' | 'offline'. Covers 'today's sales', and
    conversational follow-ups like 'online?'/'offline?' after it -- the
    model re-calls this with channel set instead of needing a second tool."""
    if not check_permission(db, admin, "analytics", "VIEW"):
        return _denied("analytics")
    start, end = resolve_date_range(range)

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
        "range": range,
        "channel": channel,
        "online_sales": online_sales,
        "online_orders": online_orders,
        "offline_sales": offline_sales,
        "offline_invoices": offline_invoices,
        "total_sales": money(online_sales + offline_sales),
    }


def get_top_selling_plants(db: Session, admin: AdminUser, range: str = "month", limit: int = 5) -> dict:
    if not check_permission(db, admin, "analytics", "VIEW"):
        return _denied("analytics")
    from app.analytics_utils import combined_sale_lines

    start, end = resolve_date_range(range)
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
                "invoice_number": inv.invoice_number,
                "status": inv.status,
                "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
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


# name -> function. Every function's first two params are always (db, admin)
# -- execute_admin_tool below injects both itself; the model-supplied
# arguments can never override either one.
ADMIN_TOOLS = {
    "get_sales_summary": get_sales_summary,
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
    "get_business_summary": get_business_summary,
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
