"""Controlled tools the AI is allowed to call. This is the ONLY place the AI
layer touches the database -- every function here is plain, synchronous,
read-only, reuses the same models/queries the rest of the app already
trusts, and returns plain JSON-serializable dicts (never ORM objects, never
raw SQL). The LLM itself never sees a database connection or session.

Every tool takes `db` plus whatever arguments the model's tool-call
provides, and an optional `customer_id` for the handful of tools that are
scoped to "my own data" -- get_order_status / get_my_orders_count check
customer_id themselves and simply refuse (return an error dict, never raise)
if it's missing, so a logged-out visitor can never be tricked into pulling
another customer's order history through a crafted prompt.
"""
import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Category, Order, Plant
from app.settings_helper import get_settings

MAX_RESULTS = 8


def _find_plant_by_name(db: Session, name: str) -> Plant | None:
    """Looks up one plant by name the way a customer actually types it, not
    by exact substring. Plant names like "1057 (TOMATO)" have spacing/
    punctuation a plain `ILIKE %name%` is too strict about -- "1057(TOMATO)"
    or "1057 tomato" (both things a real user -- or a model echoing a
    product-card title back -- would type) wouldn't match that name as one
    contiguous substring even though they clearly mean the same plant.
    Instead: split the query into alphanumeric tokens and require every
    token to appear somewhere in the name, in any order/spacing."""
    tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", name) if t]
    if not tokens:
        return None
    q = db.query(Plant).filter(Plant.is_active.is_(True))
    for t in tokens:
        q = q.filter(Plant.name.ilike(f"%{t}%"))
    plant = q.first()
    if plant:
        return plant
    # Fallback: the plain substring match still catches names with no
    # separators at all between tokens, or a single-word query.
    return db.query(Plant).filter(Plant.is_active.is_(True), Plant.name.ilike(f"%{name.strip()}%")).first()


def _plant_summary(plant: Plant) -> dict:
    variants = [{"tray_size": v.tray_size, "price": v.price} for v in (plant.variants or [])]
    return {
        "name": plant.name,
        "slug": plant.slug,
        "category": plant.category.name if plant.category else None,
        "price": plant.price,
        "effective_price": plant.effective_price,
        "stock_quantity": plant.stock_quantity,
        "availability_status": plant.availability_status,
        "care_level": plant.care_level,
        "variants": variants,
    }


def search_plants(db: Session, query: str = "", category: str = "", max_price: float = None, in_stock_only: bool = False) -> dict:
    """Search the real plant catalog -- same Plant table / is_active filter
    the public /api/plants endpoint and website Shop page use."""
    q = db.query(Plant).filter(Plant.is_active.is_(True))
    if query:
        # Tokenized, not one exact substring -- see _find_plant_by_name for
        # why ("1057(TOMATO)" vs the stored "1057 (TOMATO)", etc.).
        for t in re.split(r"[^a-zA-Z0-9]+", query):
            if t:
                q = q.filter(or_(Plant.name.ilike(f"%{t}%"), Plant.description.ilike(f"%{t}%")))
    if category:
        q = q.join(Category, Category.id == Plant.category_id).filter(Category.name.ilike(f"%{category.strip()}%"))
    if max_price is not None:
        q = q.filter(Plant.price <= max_price)
    if in_stock_only:
        q = q.filter(Plant.stock_quantity > 0)
    results = q.limit(MAX_RESULTS).all()
    return {"count": len(results), "plants": [_plant_summary(p) for p in results]}


def get_product(db: Session, name: str) -> dict:
    """Look up one plant by (approximate) name -- for 'tell me about the
    Tomato plant' type questions."""
    if not name:
        return {"error": "A plant name is required."}
    plant = _find_plant_by_name(db, name)
    if not plant:
        return {"error": f"No plant found matching '{name}'."}
    summary = _plant_summary(plant)
    summary["description"] = plant.description
    summary["features"] = plant.feature_list
    return summary


def check_stock(db: Session, name: str) -> dict:
    """Stock-only lookup -- deliberately a separate tool from get_product so
    the model reaches for the cheapest/most specific tool for a plain
    'is X in stock' question."""
    if not name:
        return {"error": "A plant name is required."}
    plant = _find_plant_by_name(db, name)
    if not plant:
        return {"error": f"No plant found matching '{name}'."}
    return {
        "name": plant.name,
        "stock_quantity": plant.stock_quantity,
        "in_stock": plant.stock_quantity > 0,
        "availability_status": plant.availability_status,
    }


def get_price(db: Session, name: str) -> dict:
    if not name:
        return {"error": "A plant name is required."}
    plant = _find_plant_by_name(db, name)
    if not plant:
        return {"error": f"No plant found matching '{name}'."}
    out = {"name": plant.name, "price": plant.price, "effective_price": plant.effective_price}
    if plant.discount_price:
        out["discount_price"] = plant.discount_price
    if plant.variants:
        out["tray_options"] = [{"tray_size": v.tray_size, "price": v.price} for v in plant.variants]
    return out


def get_order_status(db: Session, customer_id: int | None, order_id: int = None) -> dict:
    """Scoped to the CALLING customer only -- customer_id comes from the
    gateway's own session lookup, never from the model/user turn, so a
    crafted message like 'show me order_id=999 for customer 12' can never
    reach another customer's data: the WHERE clause below always also
    requires Order.customer_id == customer_id."""
    if not customer_id:
        return {"error": "Please log in to check your order status."}
    q = db.query(Order).filter(Order.customer_id == customer_id)
    if order_id:
        order = q.filter(Order.id == order_id).first()
        if not order:
            return {"error": f"No order #{order_id} found on your account."}
        return {
            "id": order.id,
            "status": order.status,
            "payment_status": order.payment_status,
            "total_amount": order.total_amount,
            "tracking_number": order.tracking_number,
            "delivery_partner": order.delivery_partner,
            "expected_delivery_date": order.expected_delivery_date.isoformat() if order.expected_delivery_date else None,
        }
    orders = q.order_by(Order.created_at.desc()).limit(5).all()
    return {
        "recent_orders": [
            {"id": o.id, "status": o.status, "total_amount": o.total_amount, "created_at": o.created_at.isoformat()}
            for o in orders
        ]
    }


def get_my_orders_count(db: Session, customer_id: int | None) -> dict:
    if not customer_id:
        return {"error": "Please log in to check your orders."}
    rows = db.query(Order.status).filter(Order.customer_id == customer_id).all()
    by_status: dict[str, int] = {}
    for (status,) in rows:
        by_status[status] = by_status.get(status, 0) + 1
    return {"total_orders": len(rows), "by_status": by_status}


def get_delivery_info(db: Session) -> dict:
    s = get_settings(db)
    return {
        "delivery_timeline": s.get("delivery_days", ""),
        "payment_methods": s.get("payment_methods", ""),
        "refund_policy": s.get("refund_policy", ""),
    }


def get_nursery_info(db: Session) -> dict:
    s = get_settings(db)
    return {
        "business_name": s.get("business_name", ""),
        "tagline": s.get("tagline", ""),
        "about": s.get("about_text", ""),
        "phone": s.get("phone", ""),
        "whatsapp": s.get("whatsapp", ""),
        "email": s.get("email", ""),
        "address": s.get("address", ""),
        "working_hours": s.get("working_hours", ""),
    }


# name -> (callable, needs_customer_id)
# needs_customer_id tools get the gateway's own session-derived customer_id
# injected automatically -- the model can never set/override it itself,
# even if it tries to pass a "customer_id" argument (TOOLS wrapper below
# strips any such key from the model-supplied arguments first).
TOOLS = {
    "search_plants": (search_plants, False),
    "get_product": (get_product, False),
    "check_stock": (check_stock, False),
    "get_price": (get_price, False),
    "get_order_status": (get_order_status, True),
    "get_my_orders_count": (get_my_orders_count, True),
    "get_delivery_info": (get_delivery_info, False),
    "get_nursery_info": (get_nursery_info, False),
}

# OpenAI-style function-calling schema, shared verbatim by every provider
# (Gemini's adapter translates this, see providers.py). Customer-facing only
# -- an Admin AI tool set would be a separate, smaller TOOL_SCHEMAS list,
# never this one, when that's built later.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_plants",
            "description": "Search the nursery's plant catalog by keyword, category, max price, or stock availability.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search text, e.g. plant name or type"},
                    "category": {"type": "string", "description": "Category name, e.g. Indoor, Flowering"},
                    "max_price": {"type": "number", "description": "Maximum price in rupees"},
                    "in_stock_only": {"type": "boolean", "description": "Only show plants currently in stock"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product",
            "description": "Get full details (description, features, price, stock) for one specific plant by name.",
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_stock",
            "description": "Check whether a specific plant is in stock and how many units are available.",
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_price",
            "description": "Get the price (and tray-size pricing if applicable) for a specific plant.",
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "Get the status of the logged-in customer's own order. Omit order_id to list their recent orders.",
            "parameters": {"type": "object", "properties": {"order_id": {"type": "integer"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_orders_count",
            "description": "Get how many orders the logged-in customer has placed in total, broken down by status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_delivery_info",
            "description": "Get the nursery's delivery timeline, accepted payment methods, and refund/replacement policy.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_nursery_info",
            "description": "Get general info about the nursery business: name, address, phone, working hours.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def execute_tool(db: Session, customer_id: int | None, name: str, arguments: dict) -> dict:
    """Single, whitelisted entry point the gateway uses to run a model-
    requested tool call -- an unknown tool name can never fall through to
    arbitrary code, it just returns an error dict the model can see and
    recover from."""
    entry = TOOLS.get(name)
    if not entry:
        return {"error": f"Unknown tool '{name}'."}
    func, needs_customer = entry
    args = {k: v for k, v in (arguments or {}).items() if k != "customer_id" and k != "db"}
    try:
        if needs_customer:
            return func(db, customer_id, **args)
        return func(db, **args)
    except TypeError as exc:
        return {"error": f"Invalid arguments for {name}: {exc}"}
