from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


# ---------- Chart of Accounts ----------

class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    account_type: str
    parent_id: Optional[int] = None
    is_active: bool
    description: str


class AccountIn(BaseModel):
    code: str
    name: str
    account_type: str
    parent_id: Optional[int] = None
    is_active: bool = True
    description: str = ""


# ---------- Tax Rates ----------

class TaxRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    rate_percent: float
    is_active: bool


class TaxRateIn(BaseModel):
    name: str
    rate_percent: float = 0
    is_active: bool = True


# ---------- Contacts ----------

class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    contact_type: str
    name: str
    email: str
    phone: str
    address: str
    gstin: str
    source: str
    source_id: Optional[str] = None
    customer_id: Optional[int] = None
    is_active: bool
    created_at: datetime
    # Computed summary fields (filled in by the router, not the ORM object)
    total_sales: float = 0
    total_paid: float = 0
    outstanding: float = 0
    total_purchases: float = 0
    total_paid_out: float = 0
    payable: float = 0
    # Party 360 additions -- channel is *computed* from the source of this
    # party's actual linked transactions, never a fixed label on the
    # contact itself (a party can have both online and offline history).
    orders_count: int = 0
    invoices_count: int = 0
    bills_count: int = 0
    payments_count: int = 0
    last_transaction_date: Optional[datetime] = None
    online_sales: float = 0
    offline_sales: float = 0
    online_transaction_count: int = 0
    offline_transaction_count: int = 0
    channels: List[str] = []  # ["online"] | ["offline"] | ["online", "offline"] | []


class ContactIn(BaseModel):
    contact_type: str = "customer"
    name: str
    email: str = ""
    phone: str = ""
    address: str = ""
    gstin: str = ""
    is_active: bool = True


# ---------- Sales Orders ----------

class SalesOrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plant_id: Optional[int] = None
    description: str
    quantity: int
    unit_price: float
    tax_amount: float
    line_total: float


class SalesOrderItemIn(BaseModel):
    plant_id: Optional[int] = None
    description: str = ""
    quantity: int = 1
    unit_price: float = 0
    tax_rate_id: Optional[int] = None


class SalesOrderIn(BaseModel):
    contact_id: int
    order_date: datetime
    notes: str = ""
    items: List[SalesOrderItemIn]


class SalesOrderInvoiceRef(BaseModel):
    """Lightweight nested reference -- avoids a circular full-Invoice embed
    since Invoice itself embeds SalesOrderOut."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    invoice_number: str
    status: str


class SalesOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    contact_id: int
    order_number: str
    status: str
    order_date: datetime
    subtotal: float
    tax_total: float
    total_amount: float
    notes: str
    source: str
    source_id: Optional[str] = None
    order_ref_id: Optional[int] = None
    created_by: str
    created_at: datetime
    contact: Optional[ContactOut] = None
    items: List[SalesOrderItemOut] = []
    invoices: List[SalesOrderInvoiceRef] = []


# ---------- Invoices ----------

class InvoiceItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    description: str
    quantity: int
    unit_price: float
    tax_amount: float
    line_total: float


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sales_order_id: int
    contact_id: int
    invoice_number: str
    status: str
    invoice_date: datetime
    due_date: Optional[datetime] = None
    subtotal: float
    tax_total: float
    discount_total: float
    total_amount: float
    amount_paid: float
    balance_due: float
    source: str
    source_id: Optional[str] = None
    created_at: datetime
    contact: Optional[ContactOut] = None
    items: List[InvoiceItemOut] = []
    sales_order: Optional[SalesOrderOut] = None


class InvoiceConvertIn(BaseModel):
    """Manually convert an (offline) Sales Order into an Invoice."""
    due_date: Optional[datetime] = None


# ---------- Payments In ----------

class PaymentInIn(BaseModel):
    invoice_id: int
    amount: float
    method: str = "Cash"
    payment_date: datetime
    reference: str = ""
    notes: str = ""


class PaymentInOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    invoice_id: int
    contact_id: int
    amount: float
    method: str
    payment_date: datetime
    reference: str
    notes: str
    source: str
    source_id: Optional[str] = None
    created_at: datetime


# ---------- Purchase Orders ----------

class PurchaseOrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plant_id: int
    description: str
    quantity: int
    unit_price: float
    tax_amount: float
    line_total: float


class PurchaseOrderItemIn(BaseModel):
    plant_id: int
    description: str = ""
    quantity: int = 1
    unit_price: float = 0
    tax_rate_id: Optional[int] = None


class PurchaseOrderIn(BaseModel):
    contact_id: int
    order_date: datetime
    notes: str = ""
    items: List[PurchaseOrderItemIn]


class BillRef(BaseModel):
    """Lightweight nested reference to the existing Purchase table (the
    Bill concept), avoiding a full circular embed."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    invoice_number: str
    status: str
    total_cost: float


class PurchaseOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    contact_id: int
    order_number: str
    status: str
    order_date: datetime
    subtotal: float
    tax_total: float
    total_amount: float
    notes: str
    source: str
    source_id: Optional[str] = None
    created_by: str
    created_at: datetime
    contact: Optional[ContactOut] = None
    items: List[PurchaseOrderItemOut] = []
    # Filled in by the router (Purchase has no ORM relationship back to
    # PurchaseOrder, only a plain purchase_order_id column) -- avoids a
    # circular import between the two modules.
    bill: Optional[BillRef] = None


class PurchaseOrderConvertIn(BaseModel):
    """Manually convert a Purchase Order into a Bill (the existing Purchase
    table)."""
    due_date: Optional[datetime] = None


# ---------- Bills (existing Purchase table, exposed here for linking) ----------

class BillItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plant_id: int
    plant_name: str
    quantity: int
    unit_cost: float
    total_cost: float


class BillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    purchase_date: datetime
    supplier: str
    invoice_number: str
    total_cost: float
    status: str
    due_date: Optional[datetime] = None
    source: str
    contact_id: Optional[int] = None
    purchase_order_id: Optional[int] = None
    # Computed summary fields (filled in by the router -- Purchase itself has
    # no amount_paid/balance_due columns, only PaymentOut rows against it)
    amount_paid: float = 0
    balance_due: float = 0
    contact: Optional[ContactOut] = None
    items: List[BillItemOut] = []


# ---------- Expenses ----------

class ExpenseIn(BaseModel):
    category: str
    account_id: Optional[int] = None
    contact_id: Optional[int] = None
    description: str = ""
    expense_date: datetime
    amount: float
    tax_amount: float = 0
    reference: str = ""
    notes: str = ""


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: str
    account_id: Optional[int] = None
    contact_id: Optional[int] = None
    description: str
    expense_date: datetime
    amount: float
    tax_amount: float
    total_amount: float
    amount_paid: float
    balance_due: float
    status: str
    reference: str
    notes: str
    source: str
    source_id: Optional[str] = None
    created_by: str
    created_at: datetime
    account: Optional[AccountOut] = None
    contact: Optional[ContactOut] = None


# ---------- Payments Out ----------

class PaymentOutIn(BaseModel):
    purchase_id: Optional[int] = None
    expense_id: Optional[int] = None
    amount: float
    method: str = "Cash"
    payment_date: datetime
    reference: str = ""
    notes: str = ""


class PaymentOutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    purchase_id: Optional[int] = None
    expense_id: Optional[int] = None
    contact_id: Optional[int] = None
    amount: float
    method: str
    payment_date: datetime
    reference: str
    notes: str
    source: str
    source_id: Optional[str] = None
    created_at: datetime


# ---------- Employees ----------

class EmployeeIn(BaseModel):
    name: str
    role: str = ""
    email: str = ""
    phone: str = ""
    salary: float = 0
    joining_date: Optional[datetime] = None
    is_active: bool = True
    notes: str = ""


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    role: str
    email: str
    phone: str
    salary: float
    joining_date: Optional[datetime] = None
    is_active: bool
    notes: str
    created_at: datetime


# ---------- Audit Log ----------

class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    table_name: str
    record_id: int
    action: str
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    changed_by: str
    changed_at: datetime


# ---------- Overview dashboard ----------

class AccountingOverviewOut(BaseModel):
    range_label: str
    total_sales: float = 0
    total_purchases: float = 0
    receivables: float = 0
    payables: float = 0
    total_expenses: float = 0
    net_profit: Optional[float] = None
    online_sales: float = 0
    offline_sales: float = 0
    pending_invoices: int = 0
    paid_invoices: int = 0
    pending_bills: int = 0
    new_contacts_this_period: int = 0
    has_data: bool = False


# ---------- Reports (Phase 3) ----------

class MonthlyAmountRow(BaseModel):
    period: str  # "YYYY-MM"
    amount: float = 0
    count: int = 0


class SalesReportOut(BaseModel):
    range_label: str
    total_sales: float = 0
    online_sales: float = 0
    offline_sales: float = 0
    invoice_count: int = 0
    rows: List[MonthlyAmountRow] = []


class PurchaseReportOut(BaseModel):
    range_label: str
    total_purchases: float = 0
    bill_count: int = 0
    rows: List[MonthlyAmountRow] = []


class CategoryAmountRow(BaseModel):
    label: str
    amount: float = 0
    count: int = 0


class ExpenseReportOut(BaseModel):
    range_label: str
    total_expenses: float = 0
    expense_count: int = 0
    rows: List[CategoryAmountRow] = []


class ProfitLossOut(BaseModel):
    range_label: str
    income: float = 0
    cogs: float = 0
    gross_profit: float = 0
    expenses: float = 0
    net_profit: float = 0


class BalanceSheetOut(BaseModel):
    as_of: datetime
    receivables: float = 0
    inventory_value: float = 0
    total_assets: float = 0
    payables: float = 0
    total_liabilities: float = 0
    retained_earnings: float = 0
    total_equity: float = 0


class CashFlowRow(BaseModel):
    period: str
    cash_in: float = 0
    cash_out: float = 0
    net: float = 0


class CashFlowOut(BaseModel):
    range_label: str
    total_in: float = 0
    total_out: float = 0
    net: float = 0
    rows: List[CashFlowRow] = []


class AgingRow(BaseModel):
    id: int
    number: str
    contact_name: str
    due_date: Optional[datetime] = None
    days_overdue: int = 0
    balance_due: float = 0


class AgingReportOut(BaseModel):
    current: float = 0
    days_0_30: float = 0
    days_31_60: float = 0
    days_61_90: float = 0
    days_90_plus: float = 0
    total: float = 0
    rows: List[AgingRow] = []


class ContactOutstandingRow(BaseModel):
    contact_id: int
    name: str
    total: float = 0
    paid: float = 0
    outstanding: float = 0


class CustomerOutstandingOut(BaseModel):
    total_outstanding: float = 0
    rows: List[ContactOutstandingRow] = []


class SupplierOutstandingOut(BaseModel):
    total_payable: float = 0
    rows: List[ContactOutstandingRow] = []


class TaxReportRow(BaseModel):
    tax_rate_id: Optional[int] = None
    name: str
    rate_percent: float = 0
    output_tax: float = 0
    input_tax: float = 0
    net_tax: float = 0


class TaxReportOut(BaseModel):
    range_label: str
    total_output_tax: float = 0
    total_input_tax: float = 0
    net_tax: float = 0
    rows: List[TaxReportRow] = []


class ItemSalesRow(BaseModel):
    plant_id: Optional[int] = None
    name: str
    quantity: int = 0
    revenue: float = 0
    online_quantity: int = 0
    offline_quantity: int = 0


class ItemSalesReportOut(BaseModel):
    range_label: str
    total_quantity: int = 0
    total_revenue: float = 0
    rows: List[ItemSalesRow] = []


class PaymentLedgerRow(BaseModel):
    date: datetime
    direction: str  # "in" | "out"
    method: str
    amount: float = 0
    contact_name: str = ""
    reference: str = ""


class PaymentsReportOut(BaseModel):
    range_label: str
    total_in: float = 0
    total_out: float = 0
    net: float = 0
    rows: List[PaymentLedgerRow] = []


# ---------- "Level 1" Analytics: Forecasting / Anomaly / Segmentation ----------

class ItemForecastRow(BaseModel):
    plant_id: Optional[int] = None
    name: str
    forecast_quantity: int = 0


class SalesForecastOut(BaseModel):
    history: List[MonthlyAmountRow] = []
    forecast_period: str
    forecast_amount: float = 0
    top_plant_forecasts: List[ItemForecastRow] = []
    has_data: bool = False


class CashFlowForecastOut(BaseModel):
    history: List[CashFlowRow] = []
    forecast_period: str
    forecast_cash_in: float = 0
    forecast_cash_out: float = 0
    forecast_net: float = 0
    has_data: bool = False


class AnomalyRow(BaseModel):
    date: datetime
    type: str  # invoice | expense | payment_in | payment_out
    reference: str
    amount: float
    expected_range: str
    reason: str


class AnomalyReportOut(BaseModel):
    rows: List[AnomalyRow] = []
    total_flagged: int = 0


class CustomerSegmentRow(BaseModel):
    contact_id: int
    name: str
    recency_days: Optional[int] = None
    frequency: int = 0
    monetary: float = 0
    segment: str


class CustomerSegmentationOut(BaseModel):
    rows: List[CustomerSegmentRow] = []
    segment_counts: dict = {}


class SeasonalPatternRow(BaseModel):
    month: int
    month_name: str
    avg_sales: float = 0
    years_counted: int = 0


class SeasonalPatternOut(BaseModel):
    rows: List[SeasonalPatternRow] = []
    peak_month: Optional[str] = None
    low_month: Optional[str] = None
    has_data: bool = False


# ---------- Parties (360-degree party profile) ----------

class PartyStatementRow(BaseModel):
    date: datetime
    transaction: str
    reference: str
    source: str  # online | offline
    debit: float = 0
    credit: float = 0
    balance: float = 0


class PartyStatementOut(BaseModel):
    opening_balance: float = 0
    rows: List[PartyStatementRow] = []
    closing_balance: float = 0


class PartyTimelineRow(BaseModel):
    date: datetime
    type: str  # sales_order | invoice | payment_in | purchase_order | bill | payment_out | expense
    label: str
    reference: str
    source: str  # online | offline
    amount: Optional[float] = None
    link_type: str  # matches frontend route segment
    link_id: int


class PartyTimelineOut(BaseModel):
    rows: List[PartyTimelineRow] = []


class PartyItemRow(BaseModel):
    plant_id: Optional[int] = None
    name: str
    quantity: int = 0
    total_value: float = 0
    last_transaction: Optional[datetime] = None


class PartyItemsOut(BaseModel):
    sold: List[PartyItemRow] = []
    purchased: List[PartyItemRow] = []


class PartyDuplicateMatch(BaseModel):
    id: int
    name: str
    phone: str
    email: str
    source: str
    contact_type: str
    matched_on: str  # phone | email | gstin | name


class PartyDuplicateCheckOut(BaseModel):
    matches: List[PartyDuplicateMatch] = []


class PartyDashboardSummaryOut(BaseModel):
    total_parties: int = 0
    online_only: int = 0
    offline_only: int = 0
    both_channels: int = 0
    customers: int = 0
    suppliers: int = 0
    both_types: int = 0
