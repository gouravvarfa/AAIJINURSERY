"""Read-only business analytics endpoints for the admin panel.

All routes require an authenticated admin session (Depends(get_current_admin)),
same as every other route in app/routers/api_admin.py. Every response includes
a `has_data` flag computed from the real underlying query result -- never
fabricated numbers, and the frontend renders "No Data Available" whenever
has_data is False instead of a chart full of zero-bars.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session

from app.analytics_utils import (
    FAST_MOVING_UNITS_90D,
    INACTIVE_DAYS,
    LOW_STOCK_THRESHOLD,
    MONTH_NAMES,
    NEW_CUSTOMER_DAYS,
    RANGE_LABELS,
    VIP_ORDER_COUNT,
    VIP_SPEND_THRESHOLD,
    combined_sale_lines,
    day_bucket,
    money,
    month_bucket,
    now_ist,
    pct_change,
    resolve_date_range,
    shift_range_back,
    to_utc,
    week_bucket,
    year_bucket,
)
from app.database import get_db
from app.deps import get_current_admin
from app.models import (
    ALL_ORDER_STATUSES,
    Category,
    Customer,
    MAIN_STATUSES,
    Order,
    OrderItem,
    Plant,
    Purchase,
    PurchaseItem,
    SiteVisit,
)
from app.schemas import (
    CategorySalesListOut,
    CategorySalesOut,
    CustomerAnalyticsOut,
    CustomerSegmentCountsOut,
    CustomerSegmentItemOut,
    CustomerSegmentListOut,
    InventoryAnalyticsOut,
    KpiSummaryOut,
    MonthlyOut,
    MonthPointOut,
    OrderStatusAnalyticsOut,
    OrderStatusCountOut,
    PlantPerformanceListOut,
    PlantPerformanceOut,
    ProfitAnalyticsOut,
    ProfitByCategoryOut,
    ProfitByMonthOut,
    PurchaseAnalyticsOut,
    PurchaseByCategoryOut,
    PurchaseByPlantOut,
    PurchaseMonthlyPointOut,
    RegistrationPointOut,
    RegistrationsOut,
    SalesPointOut,
    SiteVisitStatsOut,
    SalesSeriesOut,
    SalesTrendsOut,
    StockAlertItemOut,
    TrendLeaderOut,
    YearlyOut,
    YearSummaryOut,
)

router = APIRouter(prefix="/api/admin/analytics")

BUCKET_FNS = {"daily": day_bucket, "weekly": week_bucket, "monthly": month_bucket, "yearly": year_bucket}


def range_dep(
    range: str = Query("month", description="today|week|month|last_month|year|last_year|custom"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
    start, end = resolve_date_range(range, date_from, date_to)
    return range, start, end


# ---------- KPI summary ----------

@router.get("/summary", response_model=KpiSummaryOut)
def get_summary(
    range_info: tuple = Depends(range_dep),
    source: str = Query("", description="''=all (online+offline) | online | offline"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    range_key, start, end = range_info
    prev_start, prev_end = shift_range_back(start, end)

    def period_totals(period_start, period_end):
        """(total_sales, total_txns, completed, pending, cancelled) across
        online Orders and/or offline Invoices, per the `source` filter.
        Offline invoices have no delivery workflow of their own -- "Paid" is
        treated as completed, "Cancelled"/"Voided" as cancelled, everything
        else (Draft/Sent/PartiallyPaid/Overdue) as pending, the closest
        honest analog to the online Pending/Confirmed/.../Delivered flow."""
        sales, txns, completed, pending, cancelled = 0.0, 0, 0, 0, 0
        if source != "offline":
            row = (
                db.query(func.coalesce(func.sum(Order.total_amount), 0), func.count(Order.id))
                .filter(Order.created_at >= period_start, Order.created_at < period_end, Order.status != "Cancelled")
                .first()
            )
            sales += money(row[0])
            txns += int(row[1] or 0)
            status_counts = dict(
                db.query(Order.status, func.count(Order.id))
                .filter(Order.created_at >= period_start, Order.created_at < period_end)
                .group_by(Order.status)
                .all()
            )
            completed += status_counts.get("Delivered", 0)
            cancelled += status_counts.get("Cancelled", 0)
            pending += sum(status_counts.get(s, 0) for s in MAIN_STATUSES if s != "Delivered")
        if source != "online":
            from app.accounting.models import Invoice

            row = (
                db.query(func.coalesce(func.sum(Invoice.total_amount), 0), func.count(Invoice.id))
                .filter(
                    Invoice.invoice_date >= period_start,
                    Invoice.invoice_date < period_end,
                    Invoice.source == "offline",
                    Invoice.status != "Voided",
                )
                .first()
            )
            sales += money(row[0])
            txns += int(row[1] or 0)
            inv_status_counts = dict(
                db.query(Invoice.status, func.count(Invoice.id))
                .filter(Invoice.invoice_date >= period_start, Invoice.invoice_date < period_end, Invoice.source == "offline")
                .group_by(Invoice.status)
                .all()
            )
            completed += inv_status_counts.get("Paid", 0)
            cancelled += inv_status_counts.get("Cancelled", 0) + inv_status_counts.get("Voided", 0)
            pending += sum(
                inv_status_counts.get(s, 0) for s in ("Draft", "Sent", "PartiallyPaid", "Overdue")
            )
        return money(sales), txns, completed, pending, cancelled

    total_sales, total_orders, orders_completed, orders_pending, orders_cancelled = period_totals(start, end)
    prev_sales, _, _, _, _ = period_totals(prev_start, prev_end)
    sales_change_pct = pct_change(total_sales, prev_sales)

    combined_lines = combined_sale_lines(db, start, end, source)
    plants_sold = sum(int(r.quantity or 0) for r in combined_lines)
    varieties_sold = len({r.plant_id for r in combined_lines if r.plant_id is not None})

    total_customers = db.query(func.count(Customer.id)).scalar() or 0
    new_customers = (
        db.query(func.count(Customer.id))
        .filter(Customer.created_at >= start, Customer.created_at < end)
        .scalar()
        or 0
    )

    in_range_ids = (
        db.query(Order.customer_id)
        .filter(Order.created_at >= start, Order.created_at < end, Order.status != "Cancelled")
        .distinct()
    )
    returning_customers = (
        db.query(func.count(func.distinct(Order.customer_id)))
        .filter(
            Order.customer_id.in_(in_range_ids),
            Order.created_at < start,
            Order.status != "Cancelled",
        )
        .scalar()
        or 0
    )

    inv_row = (
        db.query(
            func.coalesce(func.sum(Plant.stock_quantity), 0),
            func.coalesce(
                func.sum(
                    case(
                        (and_(Plant.stock_quantity > 0, Plant.stock_quantity <= LOW_STOCK_THRESHOLD), 1),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(func.sum(case((Plant.stock_quantity == 0, 1), else_=0)), 0),
        )
        .filter(Plant.is_active == True)  # noqa: E712
        .first()
    )
    inventory_total, inventory_low, inventory_out = int(inv_row[0]), int(inv_row[1]), int(inv_row[2])

    purchase_cost = (
        db.query(func.coalesce(func.sum(PurchaseItem.total_cost), 0))
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .filter(Purchase.purchase_date >= start, Purchase.purchase_date < end)
        .scalar()
    )
    total_purchase_cost = money(purchase_cost)

    any_purchase_ever = (db.query(func.count(Purchase.id)).scalar() or 0) > 0
    gross_profit = money(total_sales - total_purchase_cost) if any_purchase_ever else None
    profit_margin_pct = (
        round(gross_profit / total_sales * 100, 1) if (gross_profit is not None and total_sales) else None
    )

    return KpiSummaryOut(
        range_label=RANGE_LABELS.get(range_key, range_key),
        total_sales=total_sales,
        sales_change_pct=sales_change_pct,
        total_orders=total_orders,
        orders_completed=orders_completed,
        orders_pending=orders_pending,
        orders_cancelled=orders_cancelled,
        total_customers=total_customers,
        new_customers_this_period=new_customers,
        returning_customers=returning_customers,
        plants_sold=plants_sold,
        varieties_sold=varieties_sold,
        inventory_total=inventory_total,
        inventory_low_stock=inventory_low,
        inventory_out_of_stock=inventory_out,
        total_purchase_cost=total_purchase_cost,
        gross_profit=gross_profit,
        profit_margin_pct=profit_margin_pct,
        has_data=total_orders > 0 or total_purchase_cost > 0,
    )


# ---------- Website visitors ----------

@router.get("/visits", response_model=SiteVisitStatsOut)
def get_site_visits(
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    now = now_ist()
    today_start = to_utc(datetime(now.year, now.month, now.day))
    week_start = to_utc(datetime(now.year, now.month, now.day) - timedelta(days=now.weekday()))
    month_start = to_utc(datetime(now.year, now.month, 1))

    total_visits = db.query(func.count(SiteVisit.id)).scalar() or 0
    visits_today = db.query(func.count(SiteVisit.id)).filter(SiteVisit.created_at >= today_start).scalar() or 0
    visits_this_week = db.query(func.count(SiteVisit.id)).filter(SiteVisit.created_at >= week_start).scalar() or 0
    visits_this_month = db.query(func.count(SiteVisit.id)).filter(SiteVisit.created_at >= month_start).scalar() or 0

    return SiteVisitStatsOut(
        total_visits=total_visits,
        visits_today=visits_today,
        visits_this_week=visits_this_week,
        visits_this_month=visits_this_month,
        has_data=total_visits > 0,
    )


# ---------- Sales over time ----------

@router.get("/sales", response_model=SalesSeriesOut)
def get_sales_series(
    granularity: str = Query("daily", description="daily|weekly|monthly|yearly"),
    range_info: tuple = Depends(range_dep),
    category_id: Optional[int] = Query(None),
    plant_id: Optional[int] = Query(None),
    source: str = Query("", description="''=all (online+offline) | online | offline"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    _, start, end = range_info
    bucket_fn = BUCKET_FNS.get(granularity, day_bucket)

    points_by_period = {}

    if source != "offline":
        bucket = bucket_fn(Order.created_at)
        query = (
            db.query(
                bucket.label("period"),
                func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
                func.count(func.distinct(Order.id)).label("orders"),
                func.coalesce(func.sum(OrderItem.quantity), 0).label("plants_sold"),
            )
            .join(OrderItem, OrderItem.order_id == Order.id)
            .filter(Order.created_at >= start, Order.created_at < end, Order.status != "Cancelled")
        )
        if category_id:
            query = query.join(Plant, Plant.id == OrderItem.plant_id).filter(Plant.category_id == category_id)
        if plant_id:
            query = query.filter(OrderItem.plant_id == plant_id)
        for r in query.group_by("period").order_by("period").all():
            p = points_by_period.setdefault(r.period, {"revenue": 0.0, "orders": 0, "plants_sold": 0})
            p["revenue"] += money(r.revenue)
            p["orders"] += r.orders
            p["plants_sold"] += int(r.plants_sold or 0)

    if source != "online":
        from app.accounting.models import Invoice, InvoiceItem

        bucket = bucket_fn(Invoice.invoice_date)
        query = (
            db.query(
                bucket.label("period"),
                func.coalesce(func.sum(Invoice.total_amount), 0).label("revenue"),
                func.count(func.distinct(Invoice.id)).label("orders"),
                func.coalesce(func.sum(InvoiceItem.quantity), 0).label("plants_sold"),
            )
            .join(InvoiceItem, InvoiceItem.invoice_id == Invoice.id)
            .filter(
                Invoice.invoice_date >= start,
                Invoice.invoice_date < end,
                Invoice.source == "offline",
                Invoice.status != "Voided",
            )
        )
        if category_id:
            query = query.join(Plant, Plant.id == InvoiceItem.plant_id).filter(Plant.category_id == category_id)
        if plant_id:
            query = query.filter(InvoiceItem.plant_id == plant_id)
        for r in query.group_by("period").order_by("period").all():
            p = points_by_period.setdefault(r.period, {"revenue": 0.0, "orders": 0, "plants_sold": 0})
            p["revenue"] += money(r.revenue)
            p["orders"] += r.orders
            p["plants_sold"] += int(r.plants_sold or 0)

    points = [
        SalesPointOut(period=period, revenue=money(v["revenue"]), orders=v["orders"], plants_sold=v["plants_sold"])
        for period, v in sorted(points_by_period.items())
    ]
    return SalesSeriesOut(granularity=granularity, points=points, has_data=len(points) > 0)


# ---------- Category breakdown ----------

@router.get("/categories", response_model=CategorySalesListOut)
def get_category_sales(
    range_info: tuple = Depends(range_dep),
    source: str = Query("", description="''=all (online+offline) | online | offline"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    _, start, end = range_info

    plant_category = dict(db.query(Plant.id, Plant.category_id).all())
    category_names = dict(db.query(Category.id, Category.name).all())

    lines = combined_sale_lines(db, start, end, source)
    agg = {}  # category_id -> {plants_sold, revenue, txn_ids}
    for line in lines:
        cat_id = plant_category.get(line.plant_id)
        if cat_id is None:
            continue
        bucket = agg.setdefault(cat_id, {"plants_sold": 0, "revenue": 0.0, "txn_ids": set()})
        bucket["plants_sold"] += int(line.quantity or 0)
        bucket["revenue"] += money(line.line_total)
        bucket["txn_ids"].add(line.txn_id)

    total_revenue = sum(money(b["revenue"]) for b in agg.values())
    total_plants_sold = sum(b["plants_sold"] for b in agg.values())
    categories = sorted(
        (
            CategorySalesOut(
                category_id=cat_id,
                category_name=category_names.get(cat_id, "Unknown"),
                plants_sold=b["plants_sold"],
                revenue=money(b["revenue"]),
                orders=len(b["txn_ids"]),
                pct_of_sales=round(money(b["revenue"]) / total_revenue * 100, 1) if total_revenue else 0,
            )
            for cat_id, b in agg.items()
        ),
        key=lambda c: c.revenue,
        reverse=True,
    )
    return CategorySalesListOut(
        categories=categories,
        total_revenue=total_revenue,
        total_plants_sold=total_plants_sold,
        has_data=len(categories) > 0,
    )


# ---------- Plants performance (heaviest endpoint) ----------

@router.get("/plants", response_model=PlantPerformanceListOut)
def get_plants_performance(
    range_info: tuple = Depends(range_dep),
    search: str = Query(""),
    category_id: Optional[int] = Query(None),
    stock_status: Optional[str] = Query(None, description="low|out|in_stock"),
    sort_by: str = Query("revenue", description="sold|revenue|profit|stock|last_sold|name"),
    sort_dir: str = Query("desc", description="asc|desc"),
    source: str = Query("", description="''=all (online+offline) | online | offline"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    _, start, end = range_info

    # Combined online (OrderItem) + offline (InvoiceItem) sale lines, unioned
    # at the raw-line level then re-aggregated by plant -- same approach as
    # combined_sale_lines() but kept as a SQL subquery here (not fetched into
    # Python) so pagination/sorting/search on the Plant table stay in SQL,
    # same as before this filter existed. Invoice.id is negated in the union
    # (see analytics_utils.combined_sale_lines for why) so COUNT(DISTINCT)
    # can't falsely merge an online order and an offline invoice that happen
    # to share the same numeric id.
    online_lines = (
        db.query(
            OrderItem.plant_id.label("plant_id"),
            OrderItem.quantity.label("quantity"),
            OrderItem.line_total.label("line_total"),
            Order.id.label("txn_id"),
            Order.created_at.label("sold_at"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.created_at >= start, Order.created_at < end, Order.status != "Cancelled")
    )
    from app.accounting.models import Invoice, InvoiceItem

    offline_lines = (
        db.query(
            InvoiceItem.plant_id.label("plant_id"),
            InvoiceItem.quantity.label("quantity"),
            InvoiceItem.line_total.label("line_total"),
            (-Invoice.id).label("txn_id"),
            Invoice.invoice_date.label("sold_at"),
        )
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .filter(
            Invoice.invoice_date >= start,
            Invoice.invoice_date < end,
            Invoice.source == "offline",
            Invoice.status != "Voided",
            InvoiceItem.plant_id.isnot(None),
        )
    )
    if source == "online":
        raw_lines = online_lines.subquery()
    elif source == "offline":
        raw_lines = offline_lines.subquery()
    else:
        raw_lines = online_lines.union_all(offline_lines).subquery()

    sales_sub = (
        db.query(
            raw_lines.c.plant_id.label("plant_id"),
            func.sum(raw_lines.c.quantity).label("total_sold"),
            func.sum(raw_lines.c.line_total).label("total_revenue"),
            func.count(func.distinct(raw_lines.c.txn_id)).label("order_count"),
            func.max(raw_lines.c.sold_at).label("last_sold_at"),
        )
        .group_by(raw_lines.c.plant_id)
        .subquery()
    )
    cost_sub = (
        db.query(
            PurchaseItem.plant_id.label("plant_id"),
            func.sum(PurchaseItem.total_cost).label("total_purchase_cost"),
            func.sum(PurchaseItem.quantity).label("total_purchased"),
        )
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .group_by(PurchaseItem.plant_id)
        .subquery()
    )

    query = (
        db.query(
            Plant,
            Category.name.label("category_name"),
            sales_sub.c.total_sold,
            sales_sub.c.total_revenue,
            sales_sub.c.order_count,
            sales_sub.c.last_sold_at,
            cost_sub.c.total_purchase_cost,
            cost_sub.c.total_purchased,
        )
        .join(Category, Category.id == Plant.category_id)
        .outerjoin(sales_sub, sales_sub.c.plant_id == Plant.id)
        .outerjoin(cost_sub, cost_sub.c.plant_id == Plant.id)
    )

    if search:
        query = query.filter(Plant.name.ilike(f"%{search}%"))
    if category_id:
        query = query.filter(Plant.category_id == category_id)
    if stock_status == "low":
        query = query.filter(Plant.stock_quantity > 0, Plant.stock_quantity <= LOW_STOCK_THRESHOLD)
    elif stock_status == "out":
        query = query.filter(Plant.stock_quantity == 0)
    elif stock_status == "in_stock":
        query = query.filter(Plant.stock_quantity > LOW_STOCK_THRESHOLD)

    total = query.count()

    sort_columns = {
        "sold": func.coalesce(sales_sub.c.total_sold, 0),
        "revenue": func.coalesce(sales_sub.c.total_revenue, 0),
        "stock": Plant.stock_quantity,
        "last_sold": sales_sub.c.last_sold_at,
        "name": Plant.name,
        # profit needs Python-side computation (weighted avg cost) -- sort by
        # revenue as the closest proxy at the SQL level, exact profit sort
        # happens client-side if needed for small pages.
        "profit": func.coalesce(sales_sub.c.total_revenue, 0),
    }
    sort_col = sort_columns.get(sort_by, sort_columns["revenue"])
    query = query.order_by(sort_col.asc() if sort_dir == "asc" else sort_col.desc())

    rows = query.offset((page - 1) * limit).limit(limit).all()

    # Percentile cutoffs for performance-status badges, computed over the FULL
    # (unpaginated, unfiltered-by-search) sold distribution for this period --
    # only plants with at least one sale participate in the ranking; zero-sale
    # plants are always "No Sales" regardless of percentile (handled below).
    all_sold = [row[0] for row in db.query(sales_sub.c.total_sold).all()]
    sorted_sold = sorted(all_sold, reverse=True)

    def performance_status(sold: int) -> str:
        if sold <= 0:
            return "No Sales"
        if not sorted_sold:
            return "Average"
        rank = sorted_sold.index(sold) if sold in sorted_sold else len(sorted_sold)
        pct_rank = rank / max(len(sorted_sold) - 1, 1)
        if pct_rank <= 0.1:
            return "Best Seller"
        if pct_rank <= 0.4:
            return "Growing"
        if pct_rank <= 0.75:
            return "Average"
        return "Low Sales"

    items = []
    for row in rows:
        plant = row[0]
        total_sold = int(row.total_sold or 0)
        total_revenue = money(row.total_revenue or 0)
        total_purchased = int(row.total_purchased or 0)
        total_purchase_cost = row.total_purchase_cost
        avg_purchase_cost = money(total_purchase_cost / total_purchased) if total_purchased else None
        profit = (
            money(total_revenue - avg_purchase_cost * total_sold) if avg_purchase_cost is not None else None
        )
        profit_pct = round(profit / total_revenue * 100, 1) if (profit is not None and total_revenue) else None
        items.append(
            PlantPerformanceOut(
                id=plant.id,
                name=plant.name,
                slug=plant.slug,
                image_url=plant.image_url,
                category_id=plant.category_id,
                category_name=row.category_name,
                price=plant.price,
                effective_price=plant.effective_price,
                stock_quantity=plant.stock_quantity,
                total_sold=total_sold,
                total_revenue=total_revenue,
                order_count=int(row.order_count or 0),
                last_sold_at=row.last_sold_at,
                avg_purchase_cost=avg_purchase_cost,
                total_purchased=total_purchased,
                profit=profit,
                profit_pct=profit_pct,
                performance_status=performance_status(total_sold),
            )
        )

    return PlantPerformanceListOut(
        items=items,
        total=total,
        page=page,
        pages=max(1, -(-total // limit)),
        has_data=total > 0,
    )


# ---------- Yearly / monthly drill-down ----------

def _year_summary(db: Session, year: int) -> YearSummaryOut:
    start = datetime(year, 1, 1)
    end = datetime(year + 1, 1, 1)

    sales_row = (
        db.query(func.coalesce(func.sum(Order.total_amount), 0), func.count(Order.id))
        .filter(Order.created_at >= start, Order.created_at < end, Order.status != "Cancelled")
        .first()
    )
    revenue, orders = money(sales_row[0]), int(sales_row[1] or 0)

    plants_sold = (
        db.query(func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.created_at >= start, Order.created_at < end, Order.status != "Cancelled")
        .scalar()
    )
    purchase_cost = (
        db.query(func.coalesce(func.sum(PurchaseItem.total_cost), 0))
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .filter(Purchase.purchase_date >= start, Purchase.purchase_date < end)
        .scalar()
    )
    new_customers = (
        db.query(func.count(Customer.id)).filter(Customer.created_at >= start, Customer.created_at < end).scalar()
    )
    any_purchase_ever = (db.query(func.count(Purchase.id)).scalar() or 0) > 0
    total_purchase_cost = money(purchase_cost)
    gross_profit = money(revenue - total_purchase_cost) if any_purchase_ever else None

    return YearSummaryOut(
        year=year,
        total_revenue=revenue,
        total_orders=orders,
        total_plants_sold=int(plants_sold or 0),
        total_purchase_cost=total_purchase_cost,
        gross_profit=gross_profit,
        new_customers=new_customers or 0,
        avg_order_value=money(revenue / orders) if orders else 0,
        has_data=orders > 0 or total_purchase_cost > 0,
    )


@router.get("/yearly", response_model=YearlyOut)
def get_yearly(
    year: int = Query(..., ge=2000, le=2100),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    year_summary = _year_summary(db, year)

    start = datetime(year, 1, 1)
    end = datetime(year + 1, 1, 1)
    bucket = month_bucket(Order.created_at)
    sales_rows = dict(
        (r.period, r)
        for r in db.query(
            bucket.label("period"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
            func.count(func.distinct(Order.id)).label("orders"),
        )
        .filter(Order.created_at >= start, Order.created_at < end, Order.status != "Cancelled")
        .group_by("period")
        .all()
    )
    plants_sold_rows = dict(
        db.query(
            month_bucket(Order.created_at).label("period"),
            func.coalesce(func.sum(OrderItem.quantity), 0),
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .filter(Order.created_at >= start, Order.created_at < end, Order.status != "Cancelled")
        .group_by("period")
        .all()
    )
    purchase_rows = dict(
        db.query(
            month_bucket(Purchase.purchase_date).label("period"),
            func.coalesce(func.sum(PurchaseItem.total_cost), 0),
        )
        .join(PurchaseItem, PurchaseItem.purchase_id == Purchase.id)
        .filter(Purchase.purchase_date >= start, Purchase.purchase_date < end)
        .group_by("period")
        .all()
    )
    any_purchase_ever = (db.query(func.count(Purchase.id)).scalar() or 0) > 0

    months = []
    for m in range(1, 13):
        period_key = f"{year:04d}-{m:02d}"
        row = sales_rows.get(period_key)
        revenue = money(row.revenue) if row else 0
        orders = int(row.orders) if row else 0
        purchase_cost = money(purchase_rows.get(period_key, 0))
        profit = money(revenue - purchase_cost) if any_purchase_ever else None
        months.append(
            MonthPointOut(
                month=m,
                label=MONTH_NAMES[m - 1],
                orders=orders,
                plants_sold=int(plants_sold_rows.get(period_key, 0)),
                revenue=revenue,
                purchase_cost=purchase_cost,
                profit=profit,
            )
        )

    previous_year = _year_summary(db, year - 1)
    growth_pct = pct_change(year_summary.total_revenue, previous_year.total_revenue)

    return YearlyOut(year=year_summary, months=months, previous_year=previous_year, growth_pct=growth_pct)


@router.get("/monthly", response_model=MonthlyOut)
def get_monthly(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)

    summary = get_summary(range_info=("custom", start, end), admin=admin, db=db)
    summary.range_label = f"{MONTH_NAMES[month - 1]} {year}"

    best_row = (
        db.query(
            month_bucket(Order.created_at).label("period"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
            func.count(func.distinct(Order.id)).label("orders"),
        )
        .filter(Order.status != "Cancelled")
        .group_by("period")
        .order_by(func.sum(Order.total_amount).desc())
        .first()
    )
    best_month = None
    if best_row:
        y, m = (int(x) for x in best_row.period.split("-"))
        plants_sold = (
            db.query(func.coalesce(func.sum(OrderItem.quantity), 0))
            .join(Order, Order.id == OrderItem.order_id)
            .filter(
                Order.created_at >= datetime(y, m, 1),
                Order.created_at < (datetime(y + 1, 1, 1) if m == 12 else datetime(y, m + 1, 1)),
                Order.status != "Cancelled",
            )
            .scalar()
        )
        best_month = MonthPointOut(
            month=m,
            label=f"{MONTH_NAMES[m - 1]} {y}",
            orders=int(best_row.orders),
            plants_sold=int(plants_sold or 0),
            revenue=money(best_row.revenue),
            purchase_cost=0,
            profit=None,
        )

    return MonthlyOut(year=year, month=month, summary=summary, best_performing_month=best_month)


# ---------- Customer analytics ----------

def _customer_stats(db: Session):
    return (
        db.query(
            Order.customer_id.label("customer_id"),
            func.sum(Order.total_amount).label("total_spent"),
            func.count(Order.id).label("order_count"),
            func.max(Order.created_at).label("last_order_at"),
        )
        .filter(Order.status != "Cancelled")
        .group_by(Order.customer_id)
        .all()
    )


def _segment_of(stat, customer_created_at) -> str:
    now = datetime.utcnow()
    is_new = customer_created_at and (now - customer_created_at).days < NEW_CUSTOMER_DAYS
    if stat is None:
        return "new" if is_new else "inactive"
    if stat.total_spent >= VIP_SPEND_THRESHOLD or stat.order_count >= VIP_ORDER_COUNT:
        return "vip"
    if is_new:
        return "new"
    if (now - stat.last_order_at).days > INACTIVE_DAYS:
        return "inactive"
    if stat.order_count == 1:
        return "one_time"
    if stat.order_count >= 2:
        return "regular"
    return "inactive"


@router.get("/customers", response_model=CustomerAnalyticsOut)
def get_customer_analytics(
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()
    total_customers = db.query(func.count(Customer.id)).scalar() or 0
    new_this_month = (
        db.query(func.count(Customer.id))
        .filter(Customer.created_at >= now - timedelta(days=30))
        .scalar()
        or 0
    )
    new_this_week = (
        db.query(func.count(Customer.id))
        .filter(Customer.created_at >= now - timedelta(days=7))
        .scalar()
        or 0
    )

    stats = _customer_stats(db)
    customers = {c.id: c for c in db.query(Customer.id, Customer.created_at).all()}

    segments = CustomerSegmentCountsOut()
    stat_by_customer = {s.customer_id: s for s in stats}
    for cid, cust in customers.items():
        seg = _segment_of(stat_by_customer.get(cid), cust.created_at)
        setattr(segments, seg, getattr(segments, seg) + 1)

    customers_with_orders = len(stats)
    returning_customers = sum(1 for s in stats if s.order_count >= 2)
    one_time_customers = sum(1 for s in stats if s.order_count == 1)
    repeat_customers = returning_customers
    retention_rate_pct = (
        round(returning_customers / customers_with_orders * 100, 1) if customers_with_orders else 0
    )
    avg_customer_order_value = (
        round(sum(s.total_spent for s in stats) / sum(s.order_count for s in stats), 2)
        if stats and sum(s.order_count for s in stats)
        else 0
    )
    avg_orders_per_customer = (
        round(sum(s.order_count for s in stats) / customers_with_orders, 2) if customers_with_orders else 0
    )

    return CustomerAnalyticsOut(
        total_customers=total_customers,
        new_this_month=new_this_month,
        new_this_week=new_this_week,
        returning_customers=returning_customers,
        one_time_customers=one_time_customers,
        repeat_customers=repeat_customers,
        retention_rate_pct=retention_rate_pct,
        avg_customer_order_value=avg_customer_order_value,
        avg_orders_per_customer=avg_orders_per_customer,
        segments=segments,
        has_data=total_customers > 0,
    )


@router.get("/customers/segment/{segment}", response_model=CustomerSegmentListOut)
def get_customer_segment(
    segment: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    stats = {s.customer_id: s for s in _customer_stats(db)}
    all_customers = db.query(Customer).all()

    matched = []
    for cust in all_customers:
        stat = stats.get(cust.id)
        if _segment_of(stat, cust.created_at) == segment:
            matched.append((cust, stat))

    total = len(matched)
    start_i = (page - 1) * limit
    page_items = matched[start_i : start_i + limit]

    items = [
        CustomerSegmentItemOut(
            id=cust.id,
            name=cust.name,
            email=cust.email,
            mobile=cust.mobile,
            total_spent=money(stat.total_spent) if stat else 0,
            order_count=stat.order_count if stat else 0,
            last_order_at=stat.last_order_at if stat else None,
            created_at=cust.created_at,
        )
        for cust, stat in page_items
    ]
    return CustomerSegmentListOut(
        segment=segment, items=items, total=total, page=page, pages=max(1, -(-total // limit))
    )


@router.get("/customers/registrations", response_model=RegistrationsOut)
def get_registrations(
    granularity: str = Query("daily", description="daily|weekly"),
    range_info: tuple = Depends(range_dep),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    _, start, end = range_info
    bucket_fn = week_bucket if granularity == "weekly" else day_bucket
    bucket = bucket_fn(Customer.created_at)

    rows = (
        db.query(bucket.label("period"), func.count(Customer.id).label("count"))
        .filter(Customer.created_at >= start, Customer.created_at < end)
        .group_by("period")
        .order_by("period")
        .all()
    )
    points = [RegistrationPointOut(period=r.period, new_customers=r.count) for r in rows]
    total_this_period = sum(p.new_customers for p in points)

    prev_start, prev_end = shift_range_back(start, end)
    total_prev_period = (
        db.query(func.count(Customer.id))
        .filter(Customer.created_at >= prev_start, Customer.created_at < prev_end)
        .scalar()
        or 0
    )

    return RegistrationsOut(
        points=points,
        total_new_this_period=total_this_period,
        growth_pct=pct_change(total_this_period, total_prev_period),
        has_data=len(points) > 0,
    )


# ---------- Purchase / procurement analytics ----------

@router.get("/purchases", response_model=PurchaseAnalyticsOut)
def get_purchase_analytics(
    range_info: tuple = Depends(range_dep),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    _, start, end = range_info

    totals = (
        db.query(
            func.coalesce(func.sum(PurchaseItem.total_cost), 0),
            func.coalesce(func.sum(PurchaseItem.quantity), 0),
            func.count(func.distinct(Purchase.id)),
        )
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .filter(Purchase.purchase_date >= start, Purchase.purchase_date < end)
        .first()
    )
    total_cost, total_qty, purchase_count = money(totals[0]), int(totals[1] or 0), int(totals[2] or 0)

    by_category = [
        PurchaseByCategoryOut(category_id=r.id, category_name=r.name, total_cost=money(r.total_cost))
        for r in (
            db.query(
                Category.id, Category.name, func.sum(PurchaseItem.total_cost).label("total_cost")
            )
            .join(Plant, Plant.category_id == Category.id)
            .join(PurchaseItem, PurchaseItem.plant_id == Plant.id)
            .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
            .filter(Purchase.purchase_date >= start, Purchase.purchase_date < end)
            .group_by(Category.id, Category.name)
            .order_by(func.sum(PurchaseItem.total_cost).desc())
            .all()
        )
    ]

    by_plant = [
        PurchaseByPlantOut(
            plant_id=r.plant_id,
            plant_name=r.plant_name,
            quantity_purchased=int(r.qty),
            total_cost=money(r.total_cost),
            avg_unit_cost=money(r.total_cost / r.qty) if r.qty else 0,
        )
        for r in (
            db.query(
                PurchaseItem.plant_id,
                func.max(PurchaseItem.plant_name).label("plant_name"),
                func.sum(PurchaseItem.quantity).label("qty"),
                func.sum(PurchaseItem.total_cost).label("total_cost"),
            )
            .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
            .filter(Purchase.purchase_date >= start, Purchase.purchase_date < end)
            .group_by(PurchaseItem.plant_id)
            .order_by(func.sum(PurchaseItem.total_cost).desc())
            .all()
        )
    ]

    monthly = [
        PurchaseMonthlyPointOut(period=r.period, total_cost=money(r.total_cost))
        for r in (
            db.query(
                month_bucket(Purchase.purchase_date).label("period"),
                func.sum(PurchaseItem.total_cost).label("total_cost"),
            )
            .join(PurchaseItem, PurchaseItem.purchase_id == Purchase.id)
            .filter(Purchase.purchase_date >= start, Purchase.purchase_date < end)
            .group_by("period")
            .order_by("period")
            .all()
        )
    ]

    return PurchaseAnalyticsOut(
        total_purchase_cost=total_cost,
        total_plants_purchased=total_qty,
        purchase_orders_count=purchase_count,
        by_category=by_category,
        by_plant=by_plant,
        monthly=monthly,
        has_data=purchase_count > 0,
    )


# ---------- Inventory analytics ----------

@router.get("/inventory", response_model=InventoryAnalyticsOut)
def get_inventory_analytics(
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    totals = (
        db.query(
            func.coalesce(func.sum(Plant.stock_quantity), 0),
            func.coalesce(
                func.sum(
                    case(
                        (and_(Plant.stock_quantity > 0, Plant.stock_quantity <= LOW_STOCK_THRESHOLD), 1),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(func.sum(case((Plant.stock_quantity == 0, 1), else_=0)), 0),
        )
        .filter(Plant.is_active == True)  # noqa: E712
        .first()
    )
    total_stock, low_count, out_count = int(totals[0]), int(totals[1]), int(totals[2])

    ninety_days_ago = datetime.utcnow() - timedelta(days=90)
    sold_90d = dict(
        db.query(OrderItem.plant_id, func.sum(OrderItem.quantity))
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.created_at >= ninety_days_ago, Order.status != "Cancelled")
        .group_by(OrderItem.plant_id)
        .all()
    )

    plants = db.query(Plant).filter(Plant.is_active == True).all()  # noqa: E712
    fast_moving = slow_moving = dead_stock = 0
    for p in plants:
        units_90d = int(sold_90d.get(p.id, 0) or 0)
        if units_90d >= FAST_MOVING_UNITS_90D:
            fast_moving += 1
        elif units_90d >= 1:
            slow_moving += 1
        elif p.stock_quantity > 0 and p.created_at <= ninety_days_ago:
            dead_stock += 1

    low_stock_items = [
        StockAlertItemOut(id=p.id, name=p.name, category_name=p.category.name, stock_quantity=p.stock_quantity)
        for p in db.query(Plant)
        .filter(Plant.is_active == True, Plant.stock_quantity > 0, Plant.stock_quantity <= LOW_STOCK_THRESHOLD)  # noqa: E712
        .limit(20)
        .all()
    ]
    out_of_stock_items = [
        StockAlertItemOut(id=p.id, name=p.name, category_name=p.category.name, stock_quantity=0)
        for p in db.query(Plant).filter(Plant.is_active == True, Plant.stock_quantity == 0).limit(20).all()  # noqa: E712
    ]

    return InventoryAnalyticsOut(
        total_stock=total_stock,
        low_stock_count=low_count,
        out_of_stock_count=out_count,
        fast_moving_count=fast_moving,
        slow_moving_count=slow_moving,
        dead_stock_count=dead_stock,
        low_stock_items=low_stock_items,
        out_of_stock_items=out_of_stock_items,
        has_data=len(plants) > 0,
    )


# ---------- Profit analytics ----------

@router.get("/profit", response_model=ProfitAnalyticsOut)
def get_profit_analytics(
    range_info: tuple = Depends(range_dep),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    _, start, end = range_info
    any_purchase_ever = (db.query(func.count(Purchase.id)).scalar() or 0) > 0

    total_revenue = money(
        db.query(func.coalesce(func.sum(Order.total_amount), 0))
        .filter(Order.created_at >= start, Order.created_at < end, Order.status != "Cancelled")
        .scalar()
    )
    total_purchase_cost = money(
        db.query(func.coalesce(func.sum(PurchaseItem.total_cost), 0))
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .filter(Purchase.purchase_date >= start, Purchase.purchase_date < end)
        .scalar()
    )
    gross_profit = money(total_revenue - total_purchase_cost) if any_purchase_ever else None
    profit_margin_pct = (
        round(gross_profit / total_revenue * 100, 1) if (gross_profit is not None and total_revenue) else None
    )

    revenue_by_cat = {
        r.id: money(r.revenue)
        for r in db.query(Category.id, func.sum(OrderItem.line_total).label("revenue"))
        .join(Plant, Plant.category_id == Category.id)
        .join(OrderItem, OrderItem.plant_id == Plant.id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.created_at >= start, Order.created_at < end, Order.status != "Cancelled")
        .group_by(Category.id)
        .all()
    }
    cost_by_cat = {
        r.id: money(r.cost)
        for r in db.query(Category.id, func.sum(PurchaseItem.total_cost).label("cost"))
        .join(Plant, Plant.category_id == Category.id)
        .join(PurchaseItem, PurchaseItem.plant_id == Plant.id)
        .join(Purchase, Purchase.id == PurchaseItem.purchase_id)
        .filter(Purchase.purchase_date >= start, Purchase.purchase_date < end)
        .group_by(Category.id)
        .all()
    }
    category_names = dict(db.query(Category.id, Category.name).all())
    by_category = []
    for cid, revenue in revenue_by_cat.items():
        cost = cost_by_cat.get(cid)
        profit = money(revenue - cost) if cost is not None else None
        by_category.append(
            ProfitByCategoryOut(
                category_id=cid,
                category_name=category_names.get(cid, "Unknown"),
                revenue=revenue,
                purchase_cost=cost,
                profit=profit,
                profit_pct=round(profit / revenue * 100, 1) if (profit is not None and revenue) else None,
            )
        )
    by_category.sort(key=lambda c: c.revenue, reverse=True)

    revenue_by_month = dict(
        db.query(month_bucket(Order.created_at).label("period"), func.sum(Order.total_amount))
        .filter(Order.created_at >= start, Order.created_at < end, Order.status != "Cancelled")
        .group_by("period")
        .all()
    )
    cost_by_month = dict(
        db.query(month_bucket(Purchase.purchase_date).label("period"), func.sum(PurchaseItem.total_cost))
        .join(PurchaseItem, PurchaseItem.purchase_id == Purchase.id)
        .filter(Purchase.purchase_date >= start, Purchase.purchase_date < end)
        .group_by("period")
        .all()
    )
    all_periods = sorted(set(revenue_by_month) | set(cost_by_month))
    by_month = []
    for period in all_periods:
        revenue = money(revenue_by_month.get(period, 0))
        cost = money(cost_by_month[period]) if period in cost_by_month else (0 if any_purchase_ever else None)
        profit = money(revenue - cost) if cost is not None else None
        by_month.append(ProfitByMonthOut(period=period, revenue=revenue, purchase_cost=cost, profit=profit))

    return ProfitAnalyticsOut(
        total_revenue=total_revenue,
        total_purchase_cost=total_purchase_cost,
        gross_profit=gross_profit,
        profit_margin_pct=profit_margin_pct,
        by_category=by_category,
        by_month=by_month,
        has_data=total_revenue > 0 or total_purchase_cost > 0,
    )


# ---------- Order status ----------

@router.get("/order-status", response_model=OrderStatusAnalyticsOut)
def get_order_status_analytics(
    range_info: tuple = Depends(range_dep),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    _, start, end = range_info
    rows = dict(
        (r[0], (r[1], money(r[2])))
        for r in db.query(Order.status, func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0))
        .filter(Order.created_at >= start, Order.created_at < end)
        .group_by(Order.status)
        .all()
    )
    statuses = [
        OrderStatusCountOut(status=s, count=rows.get(s, (0, 0))[0], revenue=rows.get(s, (0, 0))[1])
        for s in ALL_ORDER_STATUSES
    ]
    total_orders = sum(s.count for s in statuses)
    return OrderStatusAnalyticsOut(statuses=statuses, total_orders=total_orders, has_data=total_orders > 0)


# ---------- Sales trends / leaderboards ----------

@router.get("/trends", response_model=SalesTrendsOut)
def get_sales_trends(
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    best_day_units = (
        db.query(day_bucket(Order.created_at).label("period"), func.sum(OrderItem.quantity).label("v"))
        .join(OrderItem, OrderItem.order_id == Order.id)
        .filter(Order.status != "Cancelled")
        .group_by("period")
        .order_by(func.sum(OrderItem.quantity).desc())
        .first()
    )
    best_day_revenue = (
        db.query(day_bucket(Order.created_at).label("period"), func.sum(Order.total_amount).label("v"))
        .filter(Order.status != "Cancelled")
        .group_by("period")
        .order_by(func.sum(Order.total_amount).desc())
        .first()
    )
    best_month_units = (
        db.query(month_bucket(Order.created_at).label("period"), func.sum(OrderItem.quantity).label("v"))
        .join(OrderItem, OrderItem.order_id == Order.id)
        .filter(Order.status != "Cancelled")
        .group_by("period")
        .order_by(func.sum(OrderItem.quantity).desc())
        .first()
    )
    best_month_revenue = (
        db.query(month_bucket(Order.created_at).label("period"), func.sum(Order.total_amount).label("v"))
        .filter(Order.status != "Cancelled")
        .group_by("period")
        .order_by(func.sum(Order.total_amount).desc())
        .first()
    )
    best_category = (
        db.query(Category.name, func.sum(OrderItem.quantity).label("v"))
        .join(Plant, Plant.category_id == Category.id)
        .join(OrderItem, OrderItem.plant_id == Plant.id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status != "Cancelled")
        .group_by(Category.id, Category.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .first()
    )
    best_plant = (
        db.query(Plant.name, func.sum(OrderItem.quantity).label("v"))
        .join(OrderItem, OrderItem.plant_id == Plant.id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status != "Cancelled")
        .group_by(Plant.id, Plant.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .first()
    )

    stats = _customer_stats(db)
    highest_spender = max(stats, key=lambda s: s.total_spent, default=None)
    most_frequent = max(stats, key=lambda s: s.order_count, default=None)
    customer_names = dict(db.query(Customer.id, Customer.name).all())

    def leader(row, label_fmt, value_fmt):
        if not row:
            return None
        return TrendLeaderOut(label=label_fmt(row), value=value_fmt(row))

    highest_spender_leader = None
    if highest_spender:
        highest_spender_leader = TrendLeaderOut(
            label=customer_names.get(highest_spender.customer_id, "Unknown"),
            value=f"₹{money(highest_spender.total_spent)}",
        )
    most_frequent_leader = None
    if most_frequent:
        most_frequent_leader = TrendLeaderOut(
            label=customer_names.get(most_frequent.customer_id, "Unknown"),
            value=f"{most_frequent.order_count} orders",
        )

    has_data = any([best_day_units, best_month_units, best_category, best_plant])

    return SalesTrendsOut(
        best_selling_day=TrendLeaderOut(label=best_day_units.period, value=f"{int(best_day_units.v)} units")
        if best_day_units
        else None,
        highest_revenue_day=TrendLeaderOut(label=best_day_revenue.period, value=f"₹{money(best_day_revenue.v)}")
        if best_day_revenue
        else None,
        best_selling_month=TrendLeaderOut(label=best_month_units.period, value=f"{int(best_month_units.v)} units")
        if best_month_units
        else None,
        highest_revenue_month=TrendLeaderOut(
            label=best_month_revenue.period, value=f"₹{money(best_month_revenue.v)}"
        )
        if best_month_revenue
        else None,
        best_selling_category=TrendLeaderOut(label=best_category[0], value=f"{int(best_category[1])} units")
        if best_category
        else None,
        best_selling_plant=TrendLeaderOut(label=best_plant[0], value=f"{int(best_plant[1])} units")
        if best_plant
        else None,
        highest_spending_customer=highest_spender_leader,
        most_frequent_customer=most_frequent_leader,
        has_data=has_data,
    )
