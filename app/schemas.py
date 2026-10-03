from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    slug: str
    description: str
    image_url: str
    display_order: int


class CategoryIn(BaseModel):
    name: str
    description: str = ""
    image_url: str = ""
    display_order: int = 0


class PlantVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tray_size: int
    stock_quantity: int
    price: float


class PlantVariantIn(BaseModel):
    tray_size: int
    stock_quantity: int = 0


class PlantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category_id: int
    name: str
    slug: str
    description: str
    price: float
    discount_price: Optional[float] = None
    effective_price: float
    stock_quantity: int
    sku: str
    image_url: str
    care_level: str
    feature_list: List[str]
    is_featured: bool
    is_active: bool
    availability_status: str = "AVAILABLE"
    category: Optional[CategoryOut] = None
    variants: List[PlantVariantOut] = []
    average_rating: Optional[float] = None
    review_count: int = 0


class PlantIn(BaseModel):
    name: str
    category_id: int
    description: str = ""
    price: float = 0
    discount_price: Optional[float] = None
    stock_quantity: int = 0
    sku: str = ""
    image_url: str = ""
    care_level: str = "Easy"
    features: str = ""
    is_featured: bool = False
    is_active: bool = True
    availability_status: str = "AVAILABLE"
    variants: Optional[List[PlantVariantIn]] = None


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    slug: str
    description: str
    price: float
    price_unit: str
    feature_list: List[str]
    image_url: str
    display_order: int
    is_active: bool


class ServiceIn(BaseModel):
    name: str
    description: str = ""
    price: float = 0
    price_unit: str = "one-time"
    features: str = ""
    image_url: str = ""
    display_order: int = 0
    is_active: bool = True


class PricingPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    price: float
    billing_cycle: str
    feature_list: List[str]
    is_featured: bool
    display_order: int


class PricingPlanIn(BaseModel):
    name: str
    price: float = 0
    billing_cycle: str = "monthly"
    features: str = ""
    is_featured: bool = False
    display_order: int = 0


class FAQOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    question: str
    answer: str
    display_order: int
    is_active: bool


class FAQIn(BaseModel):
    question: str
    answer: str
    display_order: int = 0
    is_active: bool = True


class TestimonialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_name: str
    rating: int
    message: str
    image_url: str
    is_approved: bool
    created_at: datetime


class TestimonialIn(BaseModel):
    customer_name: str
    rating: int = 5
    message: str
    image_url: str = ""
    is_approved: bool = True


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plant_id: int
    customer_name: str
    rating: int
    comment: str
    status: str
    created_at: datetime
    updated_at: datetime


class ReviewIn(BaseModel):
    plant_id: int
    rating: int
    comment: str = ""


class PlantReviewsOut(BaseModel):
    average_rating: Optional[float] = None
    review_count: int
    rating_distribution: dict[int, int]
    reviews: List[ReviewOut]


class ReviewEligibilityOut(BaseModel):
    eligible: bool
    reason: str  # eligible | already_reviewed | not_delivered | not_purchased
    existing_review: Optional[ReviewOut] = None


class ReviewAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plant_id: int
    plant_name: str
    customer_id: int
    customer_name: str
    order_id: int
    rating: int
    comment: str
    status: str
    created_at: datetime
    updated_at: datetime


class ReviewModerateIn(BaseModel):
    status: str  # PUBLISHED | REJECTED | PENDING


class GalleryImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    image_url: str
    caption: str
    category: str
    display_order: int


class GalleryImageIn(BaseModel):
    image_url: str
    caption: str = ""
    category: str = ""
    display_order: int = 0


class BlogPostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    slug: str
    content: str
    excerpt: str
    image_url: str
    is_published: bool
    published_at: datetime


class BlogPostIn(BaseModel):
    title: str
    content: str
    excerpt: str = ""
    image_url: str = ""
    is_published: bool = True


class InquiryPlantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    slug: str
    image_url: str


class InquiryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    mobile: str
    requirement: str
    status: str
    plant_id: Optional[int] = None
    plant: Optional[InquiryPlantOut] = None
    created_at: datetime
    # Feature 1 additions -- all optional so this schema still serializes
    # legacy generic contact-form rows (which never set these) unchanged.
    customer_id: Optional[int] = None
    email: str = ""
    quantity: Optional[int] = None
    enquiry_number: Optional[str] = None
    plant_name_snapshot: str = ""
    updated_at: Optional[datetime] = None


class InquiryIn(BaseModel):
    name: str
    mobile: str
    requirement: str = ""
    plant_id: Optional[int] = None


class InquiryStatusIn(BaseModel):
    status: str
    note: str = ""


class InquiryStatusHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    old_status: str
    new_status: str
    note: str
    changed_by: str
    created_at: datetime


class EnquiryCreateIn(BaseModel):
    """The dedicated Feature 1 "Enquire Now" flow -- distinct from the
    generic InquiryIn used by the site's general contact form, even though
    both write to the same underlying table. plant_id and quantity are
    required here since a product enquiry without either doesn't make
    sense; the generic contact form's plant_id stays optional."""

    plant_id: int
    quantity: int = Field(gt=0, default=1)
    name: str
    mobile: str
    email: str = ""
    message: str = ""


class UnifiedLoginIn(BaseModel):
    identifier: str
    password: str


class GoogleAuthIn(BaseModel):
    credential: str  # the ID token JWT from Google Identity Services


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    created_at: Optional[datetime] = None
    is_active: bool = True
    custom_role_id: Optional[int] = None


class AdminUserCreateIn(BaseModel):
    username: str
    password: str
    role: str = "admin"
    custom_role_id: Optional[int] = None


class AdminPasswordResetIn(BaseModel):
    password: str


class AdminRoleIn(BaseModel):
    role: str
    custom_role_id: Optional[int] = None


class ActivityLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    admin_username: str
    action: str
    detail: str
    created_at: datetime


class SystemInfoOut(BaseModel):
    counts: dict[str, int]
    session_secret_is_default: bool


# ---------- Developer Dashboard RBAC ----------


class RolePermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    module: str
    can_view: bool
    can_create: bool
    can_edit: bool
    can_delete: bool
    can_export: bool
    can_print: bool
    can_approve: bool
    can_cancel: bool


class RolePermissionIn(BaseModel):
    module: str
    can_view: bool = False
    can_create: bool = False
    can_edit: bool = False
    can_delete: bool = False
    can_export: bool = False
    can_print: bool = False
    can_approve: bool = False
    can_cancel: bool = False


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    is_system: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
    user_count: int = 0
    permissions: list[RolePermissionOut] = []


class RoleCreateIn(BaseModel):
    name: str
    description: str = ""


class RoleUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[list[RolePermissionIn]] = None


class PermissionOverrideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    module: str
    action: str
    effect: str
    granted_by: str
    reason: str
    created_at: datetime
    expires_at: Optional[datetime] = None


class PermissionOverrideIn(BaseModel):
    module: str
    action: str
    effect: str  # "ALLOW" | "DENY"
    reason: str = ""
    expires_at: Optional[datetime] = None


class AdminSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    ip_address: str
    user_agent: str
    created_at: datetime
    last_seen_at: datetime
    revoked_at: Optional[datetime] = None
    is_current: bool = False


class LoginAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    identifier: str
    ip_address: str
    user_agent: str
    success: bool
    reason: str
    created_at: datetime


class SettingsIn(BaseModel):
    values: dict[str, str]


# ---------- Customers / Cart / Orders ----------


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    mobile: str
    created_at: Optional[datetime] = None


class CustomerRegisterIn(BaseModel):
    name: str
    email: EmailStr
    mobile: str = ""
    password: str = Field(min_length=8)


class CustomerLoginIn(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    password: str = Field(min_length=8)


class CartPlantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    slug: str
    image_url: str
    effective_price: float
    stock_quantity: int


class CartItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plant_id: int
    variant_id: Optional[int] = None
    quantity: int
    unit_price: float
    plant: Optional[CartPlantOut] = None
    variant: Optional[PlantVariantOut] = None


class CartAddIn(BaseModel):
    plant_id: int
    variant_id: Optional[int] = None
    quantity: int = 1


class CartUpdateIn(BaseModel):
    quantity: int


class WishlistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plant_id: int
    created_at: datetime
    plant: Optional[CartPlantOut] = None


class WishlistAddIn(BaseModel):
    plant_id: int


class WishlistStatusOut(BaseModel):
    in_wishlist: bool


class AddressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    mobile: str
    line1: str
    line2: str
    city: str
    state: str
    pincode: str
    address_type: str
    is_default: bool
    created_at: datetime


class AddressIn(BaseModel):
    full_name: str
    mobile: str
    line1: str
    line2: str = ""
    city: str
    state: str
    pincode: str
    address_type: str = "Home"
    is_default: bool = False


class CheckoutIn(BaseModel):
    delivery_name: str
    delivery_mobile: str
    delivery_line1: str
    delivery_line2: str = ""
    delivery_city: str
    delivery_state: str
    delivery_pincode: str
    payment_method: str = "COD"
    buy_now_plant_id: Optional[int] = None
    buy_now_variant_id: Optional[int] = None
    buy_now_quantity: int = 1
    idempotency_key: Optional[str] = None


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plant_id: Optional[int] = None
    plant_name: str
    plant_image_url: str
    plant_slug: Optional[str] = None
    variant_id: Optional[int] = None
    tray_size: Optional[int] = None
    unit_price: float
    quantity: int
    line_total: float


class OrderStatusHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    old_status: Optional[str] = None
    new_status: str
    updated_by: str
    remarks: str
    created_at: datetime


class OrderSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    payment_status: str
    total_amount: float
    created_at: datetime
    customer: Optional[CustomerOut] = None
    items: List[OrderItemOut] = []


class OrderSummaryAdminOut(OrderSummaryOut):
    """New Order Alert + Call Management queue view -- admin-only fields
    layered onto the same list endpoint/shape customers also use."""
    delivery_name: str = ""
    delivery_mobile: str = ""
    delivery_city: str = ""
    delivery_pincode: str = ""
    call_status: str = "PENDING"
    assigned_to: str = ""
    order_acknowledged: bool = False
    team_confirmation_status: str = "PENDING"


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    payment_status: str
    payment_method: str
    razorpay_order_id: Optional[str] = None
    subtotal: float
    shipping_fee: float
    total_amount: float
    delivery_name: str
    delivery_mobile: str
    delivery_line1: str
    delivery_line2: str
    delivery_city: str
    delivery_state: str
    delivery_pincode: str
    tracking_number: str
    delivery_partner: str
    expected_delivery_date: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    notes: str
    created_at: datetime
    updated_at: datetime
    customer: Optional[CustomerOut] = None
    items: List[OrderItemOut] = []
    history: List[OrderStatusHistoryOut] = []
    # Feature 2 (delivery feasibility + team confirmation) -- deliberately
    # excludes delivery_rejection_reason (see OrderAdminOut below): section
    # 16 says never expose the internal reason to the customer.
    team_confirmation_status: str = "PENDING"
    delivery_feasibility: str = "PENDING"
    delivery_distance_km: Optional[float] = None
    delivery_cost_calculated: Optional[float] = None
    delivery_cost_mode: str = "MANUAL"
    delivery_review_notes: str = ""


class OrderAdminOut(OrderOut):
    """Same as OrderOut, plus fields customers don't need: the internal
    rejection reason (section 16) and who/when confirmed the order."""
    delivery_rejection_reason: str = ""
    team_confirmed_by: str = ""
    team_confirmed_at: Optional[datetime] = None
    # New Order Alert + Call Management
    call_status: str = "PENDING"
    assigned_to: str = ""
    order_acknowledged: bool = False
    acknowledged_by: str = ""
    acknowledged_at: Optional[datetime] = None


class OrderCallStatusIn(BaseModel):
    call_status: str
    note: str = ""


class OrderAssignIn(BaseModel):
    assigned_to: Optional[str] = None  # admin username, or None to unassign


class OrderCancelIn(BaseModel):
    remarks: str = ""


class RazorpayVerifyIn(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class PaymentFailedIn(BaseModel):
    reason: str = ""


class OrderDeliveryReviewIn(BaseModel):
    """Team's delivery feasibility + cost review (Feature 2, section 10-12).
    Separate from OrderConfirmIn -- a team can save a review (e.g. mark
    NEEDS_REVIEW, jot notes) without that being the final confirm/reject
    decision yet."""
    delivery_feasibility: str  # PENDING | APPROVED | NOT_AVAILABLE | NEEDS_REVIEW
    distance_km: Optional[float] = None
    cost_mode: str = "MANUAL"  # AUTO | MANUAL | FREE
    final_delivery_cost: Optional[float] = None
    notes: str = ""


class OrderConfirmIn(BaseModel):
    remarks: str = ""


class OrderRejectDeliveryIn(BaseModel):
    reason: str  # one of DELIVERY_REJECTION_REASONS
    detail: str = ""  # free text, used when reason == "Other"


class CustomerAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    mobile: str
    created_at: Optional[datetime] = None
    order_count: int = 0


class CustomerOrderOut(OrderSummaryOut):
    items: List[OrderItemOut] = []


class CustomerAdminDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    mobile: str
    created_at: Optional[datetime] = None
    total_orders: int = 0
    total_spent: float = 0
    avg_order_value: float = 0
    last_order_date: Optional[datetime] = None
    status: str = "inactive"  # "active" | "inactive", see analytics segmentation thresholds
    orders: List[CustomerOrderOut] = []


class OrderAdminUpdateIn(BaseModel):
    status: Optional[str] = None
    tracking_number: Optional[str] = None
    delivery_partner: Optional[str] = None
    expected_delivery_date: Optional[datetime] = None
    payment_status: Optional[str] = None
    notes: Optional[str] = None
    remarks: str = ""


# ---------- Purchases (procurement) ----------

class PurchaseItemIn(BaseModel):
    plant_id: int
    quantity: int
    unit_cost: float


class PurchaseIn(BaseModel):
    purchase_date: datetime
    supplier: str = ""
    invoice_number: str = ""
    notes: str = ""
    items: List[PurchaseItemIn]


class PurchaseItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plant_id: int
    plant_name: str
    quantity: int
    unit_cost: float
    total_cost: float


class PurchaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    purchase_date: datetime
    supplier: str
    invoice_number: str
    notes: str
    total_cost: float
    created_by: str
    created_at: datetime
    items: List[PurchaseItemOut] = []


# ---------- Analytics ----------

class KpiSummaryOut(BaseModel):
    range_label: str
    total_sales: float = 0
    sales_change_pct: Optional[float] = None
    total_orders: int = 0
    orders_completed: int = 0
    orders_pending: int = 0
    orders_cancelled: int = 0
    total_customers: int = 0
    new_customers_this_period: int = 0
    returning_customers: int = 0
    plants_sold: int = 0
    varieties_sold: int = 0
    inventory_total: int = 0
    inventory_low_stock: int = 0
    inventory_out_of_stock: int = 0
    total_purchase_cost: float = 0
    gross_profit: Optional[float] = None
    profit_margin_pct: Optional[float] = None
    has_data: bool = False


class SalesPointOut(BaseModel):
    period: str
    revenue: float = 0
    orders: int = 0
    plants_sold: int = 0


class SalesSeriesOut(BaseModel):
    granularity: str
    points: List[SalesPointOut] = []
    has_data: bool = False


class CategorySalesOut(BaseModel):
    category_id: int
    category_name: str
    plants_sold: int = 0
    revenue: float = 0
    orders: int = 0
    pct_of_sales: float = 0


class CategorySalesListOut(BaseModel):
    categories: List[CategorySalesOut] = []
    total_revenue: float = 0
    total_plants_sold: int = 0
    has_data: bool = False


class PlantPerformanceOut(BaseModel):
    id: int
    name: str
    slug: str
    image_url: str
    category_id: int
    category_name: str
    price: float
    effective_price: float
    stock_quantity: int
    total_sold: int = 0
    total_revenue: float = 0
    order_count: int = 0
    last_sold_at: Optional[datetime] = None
    avg_purchase_cost: Optional[float] = None
    total_purchased: int = 0
    profit: Optional[float] = None
    profit_pct: Optional[float] = None
    performance_status: str = "No Sales"  # Best Seller | Growing | Average | Low Sales | No Sales


class PlantPerformanceListOut(BaseModel):
    items: List[PlantPerformanceOut] = []
    total: int = 0
    page: int = 1
    pages: int = 1
    has_data: bool = False


class MonthPointOut(BaseModel):
    month: int  # 1-12
    label: str  # "January"
    orders: int = 0
    plants_sold: int = 0
    revenue: float = 0
    purchase_cost: float = 0
    profit: Optional[float] = None


class YearSummaryOut(BaseModel):
    year: int
    total_revenue: float = 0
    total_orders: int = 0
    total_plants_sold: int = 0
    total_purchase_cost: float = 0
    gross_profit: Optional[float] = None
    new_customers: int = 0
    avg_order_value: float = 0
    has_data: bool = False


class YearlyOut(BaseModel):
    year: YearSummaryOut
    months: List[MonthPointOut] = []
    previous_year: Optional[YearSummaryOut] = None
    growth_pct: Optional[float] = None


class MonthlyOut(BaseModel):
    year: int
    month: int
    summary: KpiSummaryOut
    best_performing_month: Optional[MonthPointOut] = None


class CustomerSegmentCountsOut(BaseModel):
    vip: int = 0
    regular: int = 0
    new: int = 0
    one_time: int = 0
    inactive: int = 0


class CustomerAnalyticsOut(BaseModel):
    total_customers: int = 0
    new_this_month: int = 0
    new_this_week: int = 0
    returning_customers: int = 0
    one_time_customers: int = 0
    repeat_customers: int = 0
    retention_rate_pct: float = 0
    avg_customer_order_value: float = 0
    avg_orders_per_customer: float = 0
    segments: CustomerSegmentCountsOut = CustomerSegmentCountsOut()
    has_data: bool = False


class CustomerSegmentItemOut(BaseModel):
    id: int
    name: str
    email: str
    mobile: str
    total_spent: float = 0
    order_count: int = 0
    last_order_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class CustomerSegmentListOut(BaseModel):
    segment: str
    items: List[CustomerSegmentItemOut] = []
    total: int = 0
    page: int = 1
    pages: int = 1


class RegistrationPointOut(BaseModel):
    period: str
    new_customers: int = 0


class RegistrationsOut(BaseModel):
    points: List[RegistrationPointOut] = []
    total_new_this_period: int = 0
    growth_pct: Optional[float] = None
    has_data: bool = False


class PurchaseByCategoryOut(BaseModel):
    category_id: int
    category_name: str
    total_cost: float = 0


class PurchaseByPlantOut(BaseModel):
    plant_id: int
    plant_name: str
    quantity_purchased: int = 0
    total_cost: float = 0
    avg_unit_cost: float = 0


class PurchaseMonthlyPointOut(BaseModel):
    period: str
    total_cost: float = 0


class PurchaseAnalyticsOut(BaseModel):
    total_purchase_cost: float = 0
    total_plants_purchased: int = 0
    purchase_orders_count: int = 0
    by_category: List[PurchaseByCategoryOut] = []
    by_plant: List[PurchaseByPlantOut] = []
    monthly: List[PurchaseMonthlyPointOut] = []
    has_data: bool = False


class StockAlertItemOut(BaseModel):
    id: int
    name: str
    category_name: str
    stock_quantity: int


class InventoryAnalyticsOut(BaseModel):
    total_stock: int = 0
    low_stock_count: int = 0
    out_of_stock_count: int = 0
    fast_moving_count: int = 0
    slow_moving_count: int = 0
    dead_stock_count: int = 0
    low_stock_items: List[StockAlertItemOut] = []
    out_of_stock_items: List[StockAlertItemOut] = []
    has_data: bool = False


class ProfitByCategoryOut(BaseModel):
    category_id: int
    category_name: str
    revenue: float = 0
    purchase_cost: Optional[float] = None
    profit: Optional[float] = None
    profit_pct: Optional[float] = None


class ProfitByMonthOut(BaseModel):
    period: str
    revenue: float = 0
    purchase_cost: Optional[float] = None
    profit: Optional[float] = None


class ProfitAnalyticsOut(BaseModel):
    total_revenue: float = 0
    total_purchase_cost: float = 0
    gross_profit: Optional[float] = None
    profit_margin_pct: Optional[float] = None
    by_category: List[ProfitByCategoryOut] = []
    by_month: List[ProfitByMonthOut] = []
    has_data: bool = False


class OrderStatusCountOut(BaseModel):
    status: str
    count: int = 0
    revenue: float = 0


class OrderStatusAnalyticsOut(BaseModel):
    statuses: List[OrderStatusCountOut] = []
    total_orders: int = 0
    has_data: bool = False


class TrendLeaderOut(BaseModel):
    label: str
    value: str
    detail: str = ""


class SalesTrendsOut(BaseModel):
    best_selling_day: Optional[TrendLeaderOut] = None
    highest_revenue_day: Optional[TrendLeaderOut] = None
    best_selling_month: Optional[TrendLeaderOut] = None
    highest_revenue_month: Optional[TrendLeaderOut] = None
    best_selling_category: Optional[TrendLeaderOut] = None
    best_selling_plant: Optional[TrendLeaderOut] = None
    highest_spending_customer: Optional[TrendLeaderOut] = None
    most_frequent_customer: Optional[TrendLeaderOut] = None
    has_data: bool = False
