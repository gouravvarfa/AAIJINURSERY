"""Tool whitelist for the Admin Assistant (the restricted, day-to-day-operations
chatbot -- NOT "Ask AAIJI").

Access control is built from three layers, none of which is the system prompt:

1. Allow-list. Only the tools named in ADMIN_ASSISTANT_TOOL_NAMES (plus the two
   new product tools below) exist for this chatbot. The owner/developer-level
   tools in app/ai/admin_tools.py -- sales/revenue totals, business summary,
   staff/employee activity, audits, accounting, payroll, security, WhatsApp
   logs -- are simply not registered here, so the model cannot call them and
   the dispatcher answers "Unknown tool" if it tries to.
2. Per-tool RBAC. Every reused tool already calls check_permission() for its
   own module before touching the database; the two new tools do the same.
3. Output scrubbing. A few reused tools also return *who on staff* created or
   added a record. That is staff-activity information, so ACTOR_KEYS are
   removed from every result before it can reach the model.

The dispatcher also re-checks the developer ON/OFF switch on every call, so a
tool call can never run while the chatbot is switched off.

Read-only by design: nothing in this file writes to the database.
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai.admin_assistant_gate import ADMIN_CHATBOT_OFF_MESSAGE, is_admin_chatbot_enabled
from app.ai.admin_tools import ADMIN_TOOL_SCHEMAS, ADMIN_TOOLS, _denied
from app.models import AdminUser, Category, Plant
from app.permissions import check_permission

MAX_PLANT_RESULTS = 10

# Reused as-is from admin_tools.py (same functions, same permission checks).
ADMIN_ASSISTANT_TOOL_NAMES = [
    "get_pending_orders",
    "get_order_details",
    "search_customer",
    "get_customer_counts",
    "get_recent_customers",
    "get_inquiries",
    "get_low_stock_plants",
    "get_pending_deliveries",
    "get_deliveries",
    "get_website_content_summary",
]

# Keys that identify which staff member performed an action. Removed from
# every tool result (at any nesting depth) -- who-did-what, and per-driver
# workload, is owner/developer information.
ACTOR_KEYS = {
    "added_by", "created_by", "recorded_by", "approved_by", "changed_by", "updated_by",
    "team_confirmed_by", "assigned_by", "by", "by_driver",
}


def _scrub(value):
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k not in ACTOR_KEYS}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


# ---------- New read-only product tools ----------

def search_plants(db: Session, admin: AdminUser, name: str = "", category: str = "", limit: int = 5) -> dict:
    """Product details for the Plants page: price, stock and availability."""
    if not check_permission(db, admin, "products", "VIEW"):
        return _denied("products")
    q = db.query(Plant).join(Category, Plant.category_id == Category.id)
    for token in str(name or "").split():
        q = q.filter(Plant.name.ilike(f"%{token}%"))
    if category:
        q = q.filter(Category.name.ilike(f"%{str(category).strip()}%"))
    limit = max(1, min(int(limit or 5), MAX_PLANT_RESULTS))
    plants = q.order_by(Plant.name.asc()).limit(limit).all()
    return {
        "count": len(plants),
        "plants": [
            {
                "name": p.name,
                "category": p.category.name if p.category else None,
                "price": p.price,
                "discount_price": p.discount_price,
                "stock_quantity": p.stock_quantity,
                "availability_status": p.availability_status,
                "is_active": bool(p.is_active),
                "sku": p.sku or None,
            }
            for p in plants
        ],
    }


def list_categories(db: Session, admin: AdminUser) -> dict:
    """Product categories with how many plants each holds."""
    if not check_permission(db, admin, "products", "VIEW"):
        return _denied("products")
    rows = (
        db.query(Category.name, func.count(Plant.id))
        .outerjoin(Plant, Plant.category_id == Category.id)
        .group_by(Category.id)
        .order_by(Category.display_order.asc(), Category.name.asc())
        .all()
    )
    return {"count": len(rows), "categories": [{"name": n, "plants": c} for n, c in rows]}


_NEW_TOOLS = {"search_plants": search_plants, "list_categories": list_categories}

_NEW_SCHEMAS = [
    {"type": "function", "function": {
        "name": "search_plants",
        "description": "Look up plants/products by name and/or category: price, discount price, stock quantity, availability and whether it is active. Use for 'is plant ka stock/price kya hai', 'is X available?'.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Plant name or part of it; omit to list by category only."},
            "category": {"type": "string", "description": "Category name or part of it."},
            "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {
        "name": "list_categories",
        "description": "All product categories with the number of plants in each.",
        "parameters": {"type": "object", "properties": {}}}},
]

ADMIN_ASSISTANT_TOOLS = {**{n: ADMIN_TOOLS[n] for n in ADMIN_ASSISTANT_TOOL_NAMES}, **_NEW_TOOLS}
ADMIN_ASSISTANT_SCHEMAS = [
    s for s in ADMIN_TOOL_SCHEMAS if s["function"]["name"] in ADMIN_ASSISTANT_TOOL_NAMES
] + _NEW_SCHEMAS

# Import-time guard: every whitelisted tool must have exactly one schema.
assert {s["function"]["name"] for s in ADMIN_ASSISTANT_SCHEMAS} == set(ADMIN_ASSISTANT_TOOLS)


def execute_admin_assistant_tool(db: Session, admin: AdminUser, name: str, arguments: dict) -> dict:
    """Whitelisted dispatcher. `admin` always comes from the gateway's own
    session lookup; any `db`/`admin` keys the model supplies are dropped."""
    if not is_admin_chatbot_enabled(db):
        return {"error": ADMIN_CHATBOT_OFF_MESSAGE}
    func_ = ADMIN_ASSISTANT_TOOLS.get(name)
    if not func_:
        return {"error": f"Unknown tool '{name}'."}
    args = {k: v for k, v in (arguments or {}).items() if k not in ("db", "admin")}
    try:
        return _scrub(func_(db, admin, **args))
    except (TypeError, ValueError) as exc:
        return {"error": f"Invalid arguments for {name}: {exc}"}
