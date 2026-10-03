"""Phase 3 reporting endpoints. Every report is read-only and derives
entirely from Phase 1/2 tables plus the existing Plant/Purchase tables --
nothing here writes anything.

Note on the Balance Sheet: this system has no full double-entry ledger
(no per-transaction debit/credit journal), so it is necessarily a
simplified approximation -- receivables + an estimated inventory valuation
as "assets", payables as "liabilities", and cumulative net profit as
"equity". It will not necessarily balance to the cent the way a true
double-entry balance sheet would; it is presented as a summary, not an
audited statement.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.accounting.models import (
    Contact,
    Expense,
    Invoice,
    InvoiceItem,
    PaymentIn,
    PaymentOut,
    SalesOrder,
    SalesOrderItem,
    TaxRate,
)
from app.accounting.schemas import (
    AgingReportOut,
    AgingRow,
    AnomalyReportOut,
    AnomalyRow,
    CashFlowForecastOut,
    CashFlowOut,
    CashFlowRow,
    CategoryAmountRow,
    ContactOutstandingRow,
    CustomerOutstandingOut,
    CustomerSegmentationOut,
    CustomerSegmentRow,
    ExpenseReportOut,
    ItemForecastRow,
    ItemSalesReportOut,
    ItemSalesRow,
    MonthlyAmountRow,
    PaymentLedgerRow,
    PaymentsReportOut,
    ProfitLossOut,
    PurchaseReportOut,
    BalanceSheetOut,
    SalesForecastOut,
    SalesReportOut,
    SeasonalPatternOut,
    SeasonalPatternRow,
    SupplierOutstandingOut,
    TaxReportOut,
    TaxReportRow,
)
from app.accounting.stats_utils import linear_forecast, mean_stddev
from app.analytics_utils import (
    MONTH_NAMES,
    RANGE_LABELS,
    money,
    month_bucket,
    now_ist,
    resolve_date_range,
    to_utc,
)
from app.database import get_db
from app.deps import get_current_admin
from app.models import Plant, Purchase, PurchaseItem

router = APIRouter(prefix="/reports", tags=["accounting-reports"])

# Tunable thresholds for the "Level 1" analytics features below -- single
# edit point, matching the existing convention in app/analytics_utils.py.
ANOMALY_MIN_SAMPLE_SIZE = 5  # need at least this many data points before flagging outliers means anything
ANOMALY_STD_MULTIPLIER = 2
SEGMENT_AT_RISK_DAYS = 90
SEGMENT_VIP_MIN_FREQUENCY = 5
SEGMENT_VIP_MIN_MONETARY = 5000


def _next_period_label(period: str) -> str:
    """'2026-08' -> '2026-09' (rolls over to next year at December)."""
    year, month = map(int, period.split("-"))
    month += 1
    if month > 12:
        month = 1
        year += 1
    return f"{year:04d}-{month:02d}"


def range_dep(
    range: str = Query("month", description="today|week|month|last_month|year|last_year|custom"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
    start, end = resolve_date_range(range, date_from, date_to)
    return range, start, end


# ---------- Sales Report ----------

@router.get("/sales", response_model=SalesReportOut)
def sales_report(
    range_info: tuple = Depends(range_dep),
    source: Optional[str] = Query(None, description="online|offline -- omit for both (default, unchanged behavior)"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    range_key, start, end = range_info
    base_filters = [Invoice.invoice_date >= start, Invoice.invoice_date < end, Invoice.status != "Voided"]
    # `source` only narrows total_sales/invoice_count/monthly `rows` below --
    # online_sales/offline_sales stay full-range totals regardless, so the
    # existing Accounting Reports page (which never passes this param) keeps
    # getting the exact same response it always has.
    if source in ("online", "offline"):
        base_filters.append(Invoice.source == source)

    base = db.query(Invoice).filter(*base_filters)
    total_sales = money(db.query(func.coalesce(func.sum(Invoice.total_amount), 0)).filter(*base_filters).scalar())
    online_sales = money(db.query(func.coalesce(func.sum(
        case((Invoice.source == "online", Invoice.total_amount), else_=0)
    ), 0)).filter(Invoice.invoice_date >= start, Invoice.invoice_date < end, Invoice.status != "Voided").scalar())
    offline_sales = money(db.query(func.coalesce(func.sum(
        case((Invoice.source == "offline", Invoice.total_amount), else_=0)
    ), 0)).filter(Invoice.invoice_date >= start, Invoice.invoice_date < end, Invoice.status != "Voided").scalar())
    invoice_count = base.count()

    monthly = (
        db.query(month_bucket(Invoice.invoice_date), func.sum(Invoice.total_amount), func.count(Invoice.id))
        .filter(*base_filters)
        .group_by(month_bucket(Invoice.invoice_date))
        .order_by(month_bucket(Invoice.invoice_date))
        .all()
    )
    rows = [MonthlyAmountRow(period=p, amount=money(a), count=c) for p, a, c in monthly]

    return SalesReportOut(
        range_label=RANGE_LABELS.get(range_key, range_key),
        total_sales=total_sales,
        online_sales=online_sales,
        offline_sales=offline_sales,
        invoice_count=invoice_count,
        rows=rows,
    )


# ---------- Purchase Report ----------

@router.get("/purchases", response_model=PurchaseReportOut)
def purchase_report(
    range_info: tuple = Depends(range_dep),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    range_key, start, end = range_info
    total_purchases = money(
        db.query(func.coalesce(func.sum(Purchase.total_cost), 0))
        .filter(Purchase.purchase_date >= start, Purchase.purchase_date < end, Purchase.status != "Voided")
        .scalar()
    )
    bill_count = (
        db.query(func.count(Purchase.id))
        .filter(Purchase.purchase_date >= start, Purchase.purchase_date < end, Purchase.status != "Voided")
        .scalar()
        or 0
    )
    monthly = (
        db.query(month_bucket(Purchase.purchase_date), func.sum(Purchase.total_cost), func.count(Purchase.id))
        .filter(Purchase.purchase_date >= start, Purchase.purchase_date < end, Purchase.status != "Voided")
        .group_by(month_bucket(Purchase.purchase_date))
        .order_by(month_bucket(Purchase.purchase_date))
        .all()
    )
    rows = [MonthlyAmountRow(period=p, amount=money(a), count=c) for p, a, c in monthly]

    return PurchaseReportOut(
        range_label=RANGE_LABELS.get(range_key, range_key),
        total_purchases=total_purchases,
        bill_count=bill_count,
        rows=rows,
    )


# ---------- Expense Report ----------

@router.get("/expenses", response_model=ExpenseReportOut)
def expense_report(
    range_info: tuple = Depends(range_dep),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    range_key, start, end = range_info
    q = db.query(Expense).filter(
        Expense.expense_date >= start, Expense.expense_date < end, Expense.status != "Voided"
    )
    total_expenses = money(
        db.query(func.coalesce(func.sum(Expense.total_amount), 0))
        .filter(Expense.expense_date >= start, Expense.expense_date < end, Expense.status != "Voided")
        .scalar()
    )
    expense_count = q.count()

    by_category = (
        db.query(Expense.category, func.sum(Expense.total_amount), func.count(Expense.id))
        .filter(Expense.expense_date >= start, Expense.expense_date < end, Expense.status != "Voided")
        .group_by(Expense.category)
        .order_by(func.sum(Expense.total_amount).desc())
        .all()
    )
    rows = [CategoryAmountRow(label=cat or "Uncategorized", amount=money(a), count=c) for cat, a, c in by_category]

    return ExpenseReportOut(
        range_label=RANGE_LABELS.get(range_key, range_key),
        total_expenses=total_expenses,
        expense_count=expense_count,
        rows=rows,
    )


# ---------- Profit & Loss ----------

@router.get("/profit-loss", response_model=ProfitLossOut)
def profit_loss_report(
    range_info: tuple = Depends(range_dep),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    range_key, start, end = range_info
    income = money(
        db.query(func.coalesce(func.sum(Invoice.total_amount), 0))
        .filter(Invoice.invoice_date >= start, Invoice.invoice_date < end, Invoice.status != "Voided")
        .scalar()
    )
    cogs = money(
        db.query(func.coalesce(func.sum(Purchase.total_cost), 0))
        .filter(Purchase.purchase_date >= start, Purchase.purchase_date < end)
        .scalar()
    )
    expenses = money(
        db.query(func.coalesce(func.sum(Expense.total_amount), 0))
        .filter(Expense.expense_date >= start, Expense.expense_date < end, Expense.status != "Voided")
        .scalar()
    )
    gross_profit = money(income - cogs)
    net_profit = money(gross_profit - expenses)

    return ProfitLossOut(
        range_label=RANGE_LABELS.get(range_key, range_key),
        income=income,
        cogs=cogs,
        gross_profit=gross_profit,
        expenses=expenses,
        net_profit=net_profit,
    )


# ---------- Balance Sheet (simplified, as-of today) ----------

@router.get("/balance-sheet", response_model=BalanceSheetOut)
def balance_sheet_report(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    receivables = money(
        db.query(func.coalesce(func.sum(Invoice.balance_due), 0))
        .filter(Invoice.status.notin_(["Voided", "Cancelled"]))
        .scalar()
    )
    payables_bills = money(
        db.query(func.coalesce(func.sum(Purchase.total_cost), 0))
        .filter(Purchase.status.notin_(["Paid", "Voided", "Cancelled"]))
        .scalar()
    )
    payables_expenses = money(
        db.query(func.coalesce(func.sum(Expense.balance_due), 0))
        .filter(Expense.status.notin_(["Paid", "Voided"]))
        .scalar()
    )
    payables = money(payables_bills + payables_expenses)

    # Inventory valuation: average historical unit cost per plant (from
    # PurchaseItem) x current stock; falls back to current sale price for a
    # plant that has never been logged through a Purchase/Bill.
    cost_rows = (
        db.query(
            PurchaseItem.plant_id,
            func.sum(PurchaseItem.total_cost),
            func.sum(PurchaseItem.quantity),
        )
        .group_by(PurchaseItem.plant_id)
        .all()
    )
    avg_cost = {pid: (total / qty if qty else 0) for pid, total, qty in cost_rows if qty}
    inventory_value = 0.0
    for plant in db.query(Plant.id, Plant.stock_quantity, Plant.price).all():
        unit_cost = avg_cost.get(plant.id, plant.price)
        inventory_value += (plant.stock_quantity or 0) * unit_cost
    inventory_value = money(inventory_value)

    total_assets = money(receivables + inventory_value)
    total_liabilities = payables

    all_time_income = money(
        db.query(func.coalesce(func.sum(Invoice.total_amount), 0))
        .filter(Invoice.status != "Voided")
        .scalar()
    )
    all_time_cogs = money(
        db.query(func.coalesce(func.sum(Purchase.total_cost), 0))
        .filter(Purchase.status != "Voided")
        .scalar()
    )
    all_time_expenses = money(
        db.query(func.coalesce(func.sum(Expense.total_amount), 0))
        .filter(Expense.status != "Voided")
        .scalar()
    )
    retained_earnings = money(all_time_income - all_time_cogs - all_time_expenses)
    total_equity = retained_earnings

    return BalanceSheetOut(
        as_of=to_utc(now_ist()),
        receivables=receivables,
        inventory_value=inventory_value,
        total_assets=total_assets,
        payables=payables,
        total_liabilities=total_liabilities,
        retained_earnings=retained_earnings,
        total_equity=total_equity,
    )


# ---------- Cash Flow ----------

@router.get("/cash-flow", response_model=CashFlowOut)
def cash_flow_report(
    range_info: tuple = Depends(range_dep),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    range_key, start, end = range_info
    in_rows = dict(
        db.query(month_bucket(PaymentIn.payment_date), func.sum(PaymentIn.amount))
        .filter(PaymentIn.payment_date >= start, PaymentIn.payment_date < end)
        .group_by(month_bucket(PaymentIn.payment_date))
        .all()
    )
    out_rows = dict(
        db.query(month_bucket(PaymentOut.payment_date), func.sum(PaymentOut.amount))
        .filter(PaymentOut.payment_date >= start, PaymentOut.payment_date < end)
        .group_by(month_bucket(PaymentOut.payment_date))
        .all()
    )
    periods = sorted(set(in_rows) | set(out_rows))
    rows = []
    for p in periods:
        cash_in = money(in_rows.get(p, 0))
        cash_out = money(out_rows.get(p, 0))
        rows.append(CashFlowRow(period=p, cash_in=cash_in, cash_out=cash_out, net=money(cash_in - cash_out)))

    total_in = money(sum(r.cash_in for r in rows))
    total_out = money(sum(r.cash_out for r in rows))

    return CashFlowOut(
        range_label=RANGE_LABELS.get(range_key, range_key),
        total_in=total_in,
        total_out=total_out,
        net=money(total_in - total_out),
        rows=rows,
    )


# ---------- Aging reports ----------

def _bucket_days(days: int, buckets: AgingReportOut, amount: float):
    if days <= 0:
        buckets.current += amount
    elif days <= 30:
        buckets.days_0_30 += amount
    elif days <= 60:
        buckets.days_31_60 += amount
    elif days <= 90:
        buckets.days_61_90 += amount
    else:
        buckets.days_90_plus += amount
    buckets.total += amount


@router.get("/receivables-aging", response_model=AgingReportOut)
def receivables_aging_report(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    now = now_ist()
    out = AgingReportOut()
    invoices = (
        db.query(Invoice)
        .filter(Invoice.status.notin_(["Voided", "Cancelled"]), Invoice.balance_due > 0)
        .all()
    )
    for inv in invoices:
        reference_date = inv.due_date or inv.invoice_date
        days = (now.replace(tzinfo=None) - reference_date).days
        _bucket_days(days, out, inv.balance_due)
        out.rows.append(
            AgingRow(
                id=inv.id,
                number=inv.invoice_number,
                contact_name=inv.contact.name if inv.contact else "",
                due_date=inv.due_date,
                days_overdue=max(days, 0),
                balance_due=money(inv.balance_due),
            )
        )
    out.rows.sort(key=lambda r: r.days_overdue, reverse=True)
    out.current, out.days_0_30, out.days_31_60, out.days_61_90, out.days_90_plus, out.total = (
        money(out.current), money(out.days_0_30), money(out.days_31_60),
        money(out.days_61_90), money(out.days_90_plus), money(out.total),
    )
    return out


@router.get("/payables-aging", response_model=AgingReportOut)
def payables_aging_report(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    now = now_ist()
    out = AgingReportOut()

    bills = db.query(Purchase).filter(Purchase.status.notin_(["Paid", "Voided", "Cancelled"])).all()
    for bill in bills:
        reference_date = bill.due_date or bill.purchase_date
        days = (now.replace(tzinfo=None) - reference_date).days
        balance = bill.total_cost  # Purchase has no amount_paid column of its own
        contact_name = bill.contact.name if getattr(bill, "contact", None) else bill.supplier
        _bucket_days(days, out, balance)
        out.rows.append(
            AgingRow(
                id=bill.id,
                number=bill.invoice_number or f"Bill #{bill.id}",
                contact_name=contact_name or "",
                due_date=bill.due_date,
                days_overdue=max(days, 0),
                balance_due=money(balance),
            )
        )

    expenses = db.query(Expense).filter(Expense.status.notin_(["Paid", "Voided"])).all()
    for exp in expenses:
        days = (now.replace(tzinfo=None) - exp.expense_date).days
        _bucket_days(days, out, exp.balance_due)
        out.rows.append(
            AgingRow(
                id=exp.id,
                number=f"Expense #{exp.id}",
                contact_name=exp.contact.name if exp.contact else exp.category,
                due_date=None,
                days_overdue=max(days, 0),
                balance_due=money(exp.balance_due),
            )
        )

    out.rows.sort(key=lambda r: r.days_overdue, reverse=True)
    out.current, out.days_0_30, out.days_31_60, out.days_61_90, out.days_90_plus, out.total = (
        money(out.current), money(out.days_0_30), money(out.days_31_60),
        money(out.days_61_90), money(out.days_90_plus), money(out.total),
    )
    return out


# ---------- Customer / Supplier Outstanding ----------

@router.get("/customer-outstanding", response_model=CustomerOutstandingOut)
def customer_outstanding_report(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    contacts = db.query(Contact).filter(Contact.contact_type.in_(["customer", "both"])).all()
    rows = []
    for c in contacts:
        total_sales = money(
            db.query(func.coalesce(func.sum(Invoice.total_amount), 0))
            .filter(Invoice.contact_id == c.id, Invoice.status != "Voided")
            .scalar()
        )
        total_paid = money(
            db.query(func.coalesce(func.sum(PaymentIn.amount), 0)).filter(PaymentIn.contact_id == c.id).scalar()
        )
        outstanding = money(total_sales - total_paid)
        if outstanding > 0:
            rows.append(ContactOutstandingRow(contact_id=c.id, name=c.name, total=total_sales, paid=total_paid, outstanding=outstanding))
    rows.sort(key=lambda r: r.outstanding, reverse=True)
    return CustomerOutstandingOut(total_outstanding=money(sum(r.outstanding for r in rows)), rows=rows)


@router.get("/supplier-outstanding", response_model=SupplierOutstandingOut)
def supplier_outstanding_report(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    contacts = db.query(Contact).filter(Contact.contact_type.in_(["supplier", "both"])).all()
    rows = []
    for c in contacts:
        total_purchases = money(
            db.query(func.coalesce(func.sum(Purchase.total_cost), 0)).filter(Purchase.contact_id == c.id).scalar()
        )
        total_paid_out = money(
            db.query(func.coalesce(func.sum(PaymentOut.amount), 0)).filter(PaymentOut.contact_id == c.id).scalar()
        )
        payable = money(total_purchases - total_paid_out)
        if payable > 0:
            rows.append(ContactOutstandingRow(contact_id=c.id, name=c.name, total=total_purchases, paid=total_paid_out, outstanding=payable))
    rows.sort(key=lambda r: r.outstanding, reverse=True)
    return SupplierOutstandingOut(total_payable=money(sum(r.outstanding for r in rows)), rows=rows)


# ---------- Tax Report ----------

@router.get("/tax", response_model=TaxReportOut)
def tax_report(
    range_info: tuple = Depends(range_dep),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Output tax is computed from real Invoice line items (Bills, which
    reuse the existing Purchase/PurchaseItem tables, have no per-line tax
    columns, so there is no "input tax from Bills" side to report here --
    only from not-yet-billed Purchase Order lines, which is out of scope for
    a paid-tax report). This report is therefore output-tax-only until a
    future phase adds tax tracking to Bills."""
    range_key, start, end = range_info
    rows_data = (
        db.query(
            InvoiceItem.tax_rate_id,
            func.coalesce(func.sum(InvoiceItem.tax_amount), 0),
        )
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .filter(Invoice.invoice_date >= start, Invoice.invoice_date < end, Invoice.status != "Voided")
        .group_by(InvoiceItem.tax_rate_id)
        .all()
    )
    tax_rates = {t.id: t for t in db.query(TaxRate).all()}
    rows = []
    for rate_id, tax_amount in rows_data:
        rate = tax_rates.get(rate_id)
        rows.append(
            TaxReportRow(
                tax_rate_id=rate_id,
                name=rate.name if rate else "No tax rate",
                rate_percent=rate.rate_percent if rate else 0,
                output_tax=money(tax_amount),
                input_tax=0,
                net_tax=money(tax_amount),
            )
        )
    rows.sort(key=lambda r: r.output_tax, reverse=True)
    total_output = money(sum(r.output_tax for r in rows))

    return TaxReportOut(
        range_label=RANGE_LABELS.get(range_key, range_key),
        total_output_tax=total_output,
        total_input_tax=0,
        net_tax=total_output,
        rows=rows,
    )


# ---------- Item-wise Sales Report ----------

@router.get("/item-sales", response_model=ItemSalesReportOut)
def item_sales_report(
    range_info: tuple = Depends(range_dep),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    range_key, start, end = range_info
    rows_data = (
        db.query(
            SalesOrderItem.plant_id,
            SalesOrderItem.description,
            func.sum(SalesOrderItem.quantity),
            func.sum(SalesOrderItem.line_total),
            func.sum(case((SalesOrder.source == "online", SalesOrderItem.quantity), else_=0)),
            func.sum(case((SalesOrder.source == "offline", SalesOrderItem.quantity), else_=0)),
        )
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.sales_order_id)
        .join(Invoice, Invoice.sales_order_id == SalesOrder.id)
        .filter(Invoice.invoice_date >= start, Invoice.invoice_date < end, Invoice.status != "Voided")
        .group_by(SalesOrderItem.plant_id, SalesOrderItem.description)
        .order_by(func.sum(SalesOrderItem.line_total).desc())
        .all()
    )
    rows = [
        ItemSalesRow(
            plant_id=plant_id,
            name=description or "Unknown item",
            quantity=int(qty or 0),
            revenue=money(revenue),
            online_quantity=int(online_qty or 0),
            offline_quantity=int(offline_qty or 0),
        )
        for plant_id, description, qty, revenue, online_qty, offline_qty in rows_data
    ]

    return ItemSalesReportOut(
        range_label=RANGE_LABELS.get(range_key, range_key),
        total_quantity=sum(r.quantity for r in rows),
        total_revenue=money(sum(r.revenue for r in rows)),
        rows=rows,
    )


# ---------- Payments Report (combined ledger) ----------

@router.get("/payments", response_model=PaymentsReportOut)
def payments_report(
    range_info: tuple = Depends(range_dep),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    range_key, start, end = range_info
    ins = (
        db.query(PaymentIn)
        .filter(PaymentIn.payment_date >= start, PaymentIn.payment_date < end)
        .all()
    )
    outs = (
        db.query(PaymentOut)
        .filter(PaymentOut.payment_date >= start, PaymentOut.payment_date < end)
        .all()
    )
    rows = []
    for p in ins:
        rows.append(
            PaymentLedgerRow(
                date=p.payment_date, direction="in", method=p.method, amount=money(p.amount),
                contact_name=p.contact.name if p.contact else "", reference=p.reference,
            )
        )
    for p in outs:
        rows.append(
            PaymentLedgerRow(
                date=p.payment_date, direction="out", method=p.method, amount=money(p.amount),
                contact_name=p.contact.name if p.contact else "", reference=p.reference,
            )
        )
    rows.sort(key=lambda r: r.date, reverse=True)

    total_in = money(sum(r.amount for r in rows if r.direction == "in"))
    total_out = money(sum(r.amount for r in rows if r.direction == "out"))

    return PaymentsReportOut(
        range_label=RANGE_LABELS.get(range_key, range_key),
        total_in=total_in,
        total_out=total_out,
        net=money(total_in - total_out),
        rows=rows,
    )


# ---------- "Level 1" Analytics (pure Python stats, no ML library) ----------

def _n_months_ago(dt: datetime, n: int) -> datetime:
    month_index = dt.month - 1 - n
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    return dt.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)


@router.get("/sales-forecast", response_model=SalesForecastOut)
def sales_forecast_report(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Simple least-squares trend line over the trailing 6 months of real
    Invoice data, extrapolated one month forward -- no ML library."""
    monthly = (
        db.query(month_bucket(Invoice.invoice_date), func.sum(Invoice.total_amount))
        .filter(Invoice.status != "Voided")
        .group_by(month_bucket(Invoice.invoice_date))
        .order_by(month_bucket(Invoice.invoice_date))
        .all()
    )
    monthly = monthly[-6:]
    history = [MonthlyAmountRow(period=p, amount=money(a)) for p, a in monthly]
    has_data = len(history) > 0

    forecast_amount = linear_forecast([r.amount for r in history]) if has_data else 0.0
    forecast_period = _next_period_label(history[-1].period) if history else ""

    period_start = _n_months_ago(datetime.utcnow(), 3)
    item_rows = (
        db.query(SalesOrderItem.plant_id, SalesOrderItem.description, func.sum(SalesOrderItem.quantity))
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.sales_order_id)
        .join(Invoice, Invoice.sales_order_id == SalesOrder.id)
        .filter(Invoice.invoice_date >= period_start, Invoice.status != "Voided")
        .group_by(SalesOrderItem.plant_id, SalesOrderItem.description)
        .order_by(func.sum(SalesOrderItem.quantity).desc())
        .limit(5)
        .all()
    )
    top_plant_forecasts = [
        ItemForecastRow(plant_id=pid, name=desc or "Unknown item", forecast_quantity=round((qty or 0) / 3))
        for pid, desc, qty in item_rows
    ]

    return SalesForecastOut(
        history=history,
        forecast_period=forecast_period,
        forecast_amount=forecast_amount,
        top_plant_forecasts=top_plant_forecasts,
        has_data=has_data,
    )


@router.get("/cash-flow-forecast", response_model=CashFlowForecastOut)
def cash_flow_forecast_report(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    in_rows = dict(
        db.query(month_bucket(PaymentIn.payment_date), func.sum(PaymentIn.amount))
        .group_by(month_bucket(PaymentIn.payment_date))
        .all()
    )
    out_rows = dict(
        db.query(month_bucket(PaymentOut.payment_date), func.sum(PaymentOut.amount))
        .group_by(month_bucket(PaymentOut.payment_date))
        .all()
    )
    periods = sorted(set(in_rows) | set(out_rows))[-6:]
    history = []
    for p in periods:
        cash_in = money(in_rows.get(p, 0))
        cash_out = money(out_rows.get(p, 0))
        history.append(CashFlowRow(period=p, cash_in=cash_in, cash_out=cash_out, net=money(cash_in - cash_out)))

    has_data = len(history) > 0
    forecast_cash_in = linear_forecast([r.cash_in for r in history]) if has_data else 0.0
    forecast_cash_out = linear_forecast([r.cash_out for r in history]) if has_data else 0.0
    forecast_period = _next_period_label(history[-1].period) if history else ""

    return CashFlowForecastOut(
        history=history,
        forecast_period=forecast_period,
        forecast_cash_in=forecast_cash_in,
        forecast_cash_out=forecast_cash_out,
        forecast_net=money(forecast_cash_in - forecast_cash_out),
        has_data=has_data,
    )


def _flag_anomalies(rows, amount_fn, date_fn, type_label, reference_fn):
    flagged = []
    amounts = [amount_fn(r) for r in rows]
    if len(amounts) < ANOMALY_MIN_SAMPLE_SIZE:
        return flagged
    mean, std = mean_stddev(amounts)
    if std <= 0:
        return flagged
    low = max(mean - ANOMALY_STD_MULTIPLIER * std, 0)
    high = mean + ANOMALY_STD_MULTIPLIER * std
    for r in rows:
        amount = amount_fn(r)
        if amount < low or amount > high:
            flagged.append(
                AnomalyRow(
                    date=date_fn(r), type=type_label, reference=reference_fn(r), amount=money(amount),
                    expected_range=f"Rs {money(low)} - Rs {money(high)}",
                    reason="Unusually high amount" if amount > mean else "Unusually low amount",
                )
            )
    return flagged


@router.get("/anomalies", response_model=AnomalyReportOut)
def anomaly_report(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Flags transactions more than 2 standard deviations from that
    category's historical mean -- a classic, dependency-free outlier
    detection technique. Needs at least a handful of data points per
    category before it can say anything meaningful."""
    rows = []
    rows += _flag_anomalies(
        db.query(Expense).filter(Expense.status != "Voided").all(),
        lambda e: e.total_amount, lambda e: e.expense_date, "expense",
        lambda e: f"{e.category} #{e.id}",
    )
    rows += _flag_anomalies(
        db.query(Invoice).filter(Invoice.status != "Voided").all(),
        lambda i: i.total_amount, lambda i: i.invoice_date, "invoice",
        lambda i: i.invoice_number,
    )
    rows += _flag_anomalies(
        db.query(PaymentOut).all(),
        lambda p: p.amount, lambda p: p.payment_date, "payment_out",
        lambda p: p.reference or f"Payment #{p.id}",
    )
    rows += _flag_anomalies(
        db.query(Purchase).all(),
        lambda b: b.total_cost, lambda b: b.purchase_date, "bill",
        lambda b: b.invoice_number or f"Bill #{b.id}",
    )
    rows.sort(key=lambda r: r.date, reverse=True)
    return AnomalyReportOut(rows=rows, total_flagged=len(rows))


@router.get("/customer-segmentation", response_model=CustomerSegmentationOut)
def customer_segmentation_report(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Simple RFM (Recency/Frequency/Monetary) rule-based segmentation --
    no clustering library needed, just bucketing against tunable
    thresholds defined at the top of this file."""
    contacts = db.query(Contact).filter(Contact.contact_type.in_(["customer", "both"])).all()
    now = now_ist().replace(tzinfo=None)
    rows = []
    segment_counts = {}

    for c in contacts:
        invoices = db.query(Invoice).filter(Invoice.contact_id == c.id, Invoice.status != "Voided").all()
        if not invoices:
            continue
        frequency = len(invoices)
        monetary = money(sum(i.total_amount for i in invoices))
        last_date = max(i.invoice_date for i in invoices)
        recency_days = (now - last_date).days

        if recency_days > SEGMENT_AT_RISK_DAYS:
            segment = "At Risk"
        elif frequency >= SEGMENT_VIP_MIN_FREQUENCY and monetary >= SEGMENT_VIP_MIN_MONETARY:
            segment = "VIP"
        elif frequency == 1:
            segment = "New"
        else:
            segment = "Regular"

        segment_counts[segment] = segment_counts.get(segment, 0) + 1
        rows.append(
            CustomerSegmentRow(
                contact_id=c.id, name=c.name, recency_days=recency_days,
                frequency=frequency, monetary=monetary, segment=segment,
            )
        )

    rows.sort(key=lambda r: r.monetary, reverse=True)
    return CustomerSegmentationOut(rows=rows, segment_counts=segment_counts)


@router.get("/seasonal-pattern", response_model=SeasonalPatternOut)
def seasonal_pattern_report(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Average sales per calendar month-of-year across all available years
    -- reveals which months are historically busy/slow seasons."""
    monthly_totals = (
        db.query(month_bucket(Invoice.invoice_date), func.sum(Invoice.total_amount))
        .filter(Invoice.status != "Voided")
        .group_by(month_bucket(Invoice.invoice_date))
        .all()
    )
    month_values = {m: [] for m in range(1, 13)}
    for period, amount in monthly_totals:
        _, month_str = period.split("-")
        month_values[int(month_str)].append(amount or 0)

    rows = []
    for m in range(1, 13):
        values = month_values[m]
        avg = money(sum(values) / len(values)) if values else 0.0
        rows.append(SeasonalPatternRow(month=m, month_name=MONTH_NAMES[m - 1], avg_sales=avg, years_counted=len(values)))

    counted_rows = [r for r in rows if r.years_counted > 0]
    has_data = len(counted_rows) > 0
    peak = max(counted_rows, key=lambda r: r.avg_sales, default=None)
    low = min(counted_rows, key=lambda r: r.avg_sales, default=None)

    return SeasonalPatternOut(
        rows=rows,
        peak_month=peak.month_name if peak else None,
        low_month=low.month_name if low else None,
        has_data=has_data,
    )
