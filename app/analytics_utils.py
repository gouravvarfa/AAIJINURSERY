"""Shared helpers for the admin analytics endpoints (app/routers/api_admin_analytics.py).
All `created_at`/`purchase_date` columns app-wide are stored as naive UTC
(`datetime.utcnow()`), but the nursery's business timezone is IST (UTC+5:30).
Bucketing "Today"/"This Month"/etc. directly against raw UTC values would
misclassify anything placed after 6:30pm IST into the wrong day -- every helper
below shifts to IST before bucketing or computing "now".
"""
from datetime import datetime, timedelta

from sqlalchemy import func

IST = timedelta(hours=5, minutes=30)

# Tunable thresholds -- single edit point if the business wants different cutoffs.
LOW_STOCK_THRESHOLD = 20
FAST_MOVING_UNITS_90D = 20
INACTIVE_DAYS = 90
NEW_CUSTOMER_DAYS = 30
VIP_SPEND_THRESHOLD = 15000
VIP_ORDER_COUNT = 10

def local_dt(column):
    """Shift a naive-UTC DateTime column to IST before any strftime bucketing.
    SQLite's datetime() requires each modifier as a separate argument -- a single
    combined string like "+5 hours 30 minutes" is invalid and silently returns
    NULL (confirmed: it doesn't raise, every row just buckets into a NULL group,
    which looks like "no data" rather than an obvious error)."""
    return func.datetime(column, "+5 hours", "+30 minutes")

def day_bucket(column):
    return func.strftime("%Y-%m-%d", local_dt(column))

def week_bucket(column):
    return func.strftime("%Y-W%W", local_dt(column))

def month_bucket(column):
    return func.strftime("%Y-%m", local_dt(column))

def year_bucket(column):
    return func.strftime("%Y", local_dt(column))

def money(x):
    return round(float(x or 0), 2)

def now_ist():
    return datetime.utcnow() + IST

def to_utc(dt_ist):
    return dt_ist - IST

def _month_start(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

def _add_months(dt, n):
    month = dt.month - 1 + n
    year = dt.year + month // 12
    month = month % 12 + 1
    return dt.replace(year=year, month=month)

def resolve_date_range(range_key: str, custom_from: datetime = None, custom_to: datetime = None):
    """today|week|month|last_month|year|last_year|custom -> (start, end) as
    UTC-naive datetimes suitable for filtering created_at columns directly."""
    now = now_ist()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if range_key == "today":
        start, end = today_start, today_start + timedelta(days=1)
    elif range_key == "week":
        start = today_start - timedelta(days=today_start.weekday())
        end = start + timedelta(days=7)
    elif range_key == "month":
        start = _month_start(today_start)
        end = _add_months(start, 1)
    elif range_key == "last_month":
        this_month_start = _month_start(today_start)
        start = _add_months(this_month_start, -1)
        end = this_month_start
    elif range_key == "year":
        start = today_start.replace(month=1, day=1)
        end = start.replace(year=start.year + 1)
    elif range_key == "last_year":
        this_year_start = today_start.replace(month=1, day=1)
        start = this_year_start.replace(year=this_year_start.year - 1)
        end = this_year_start
    elif range_key == "custom" and custom_from is not None:
        start = custom_from
        end = (custom_to + timedelta(days=1)) if custom_to else now
    else:
        # sane default: this month
        start = _month_start(today_start)
        end = _add_months(start, 1)

    return to_utc(start), to_utc(end)

def shift_range_back(start: datetime, end: datetime):
    """Equal-length immediately-preceding period, for '% vs previous period' KPIs."""
    length = end - start
    return start - length, start

RANGE_LABELS = {
    "today": "Today",
    "week": "This Week",
    "month": "This Month",
    "last_month": "Last Month",
    "year": "This Year",
    "last_year": "Last Year",
    "custom": "Custom Range",
}

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def combined_sale_lines(db, start, end, source: str = ""):
    """One unified list of sale line-items spanning BOTH online website
    orders and offline (manually entered) Accounting invoices, so
    plant/category-level analytics (Top Plants, Categories, Plants
    Performance, Trends) can include offline sales, not just online ones.

    `source`: "" (both), "online", or "offline".

    Each row exposes: plant_id, quantity, line_total, txn_id, created_at --
    the same shape regardless of which table it came from, so callers never
    need to know which source a row originated from. Plain Python-side
    merge (not a SQL UNION) because the two source tables have genuinely
    different join chains; dataset sizes here are small enough that this
    is simpler and just as fast as building a UNION query.

    Offline rows only exist from the point InvoiceItem.plant_id started
    being populated (see convert_to_invoice / sync.py) -- older offline
    invoices created before that fix have no plant attribution and are
    excluded here the same way a line with no plant would be (can't
    attribute a NULL plant to any plant/category).
    """
    from app.models import Order, OrderItem

    rows = []
    if source != "offline":
        online = (
            db.query(
                OrderItem.plant_id.label("plant_id"),
                OrderItem.quantity.label("quantity"),
                OrderItem.line_total.label("line_total"),
                Order.id.label("txn_id"),
                Order.created_at.label("created_at"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .filter(Order.created_at >= start, Order.created_at < end, Order.status != "Cancelled")
            .all()
        )
        rows.extend(online)

    if source != "online":
        from app.accounting.models import Invoice, InvoiceItem

        offline = (
            db.query(
                InvoiceItem.plant_id.label("plant_id"),
                InvoiceItem.quantity.label("quantity"),
                InvoiceItem.line_total.label("line_total"),
                # Negated: Order.id and Invoice.id are separate numeric
                # sequences that can collide (both start at 1) -- online
                # txn_id is always a positive Order.id, so a negative
                # Invoice.id guarantees no false "same transaction" merge
                # when counting distinct transactions across both sources.
                (-Invoice.id).label("txn_id"),
                Invoice.invoice_date.label("created_at"),
            )
            .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .filter(
                Invoice.invoice_date >= start,
                Invoice.invoice_date < end,
                Invoice.status != "Voided",
                Invoice.source == "offline",
                InvoiceItem.plant_id.isnot(None),
            )
            .all()
        )
        rows.extend(offline)

    return rows

def pct_change(current, previous):
    """Percentage change from previous -> current. None if previous is 0/None
    (division by zero would be meaningless, not "0% change")."""
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)
