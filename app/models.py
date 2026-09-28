from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base

# Order lifecycle
MAIN_STATUSES = [
    "Pending",
    "Confirmed",
    "Processing",
    "Packed",
    "Shipped",
    "Out For Delivery",
    "Delivered",
]
EXTRA_STATUSES = ["Cancelled", "Refund Initiated", "Refund Completed", "Returned"]
ALL_ORDER_STATUSES = MAIN_STATUSES + EXTRA_STATUSES
CANCELLABLE_STATUSES = {"Pending", "Confirmed"}
PAYMENT_STATUSES = ["Pending", "Paid", "Failed", "Refund Initiated", "Refund Completed"]

# Feature 2 (delivery feasibility + team confirmation) -- see Order model
# comment for why these live on a separate axis from `status` above.
TEAM_CONFIRMATION_STATUSES = ["PENDING", "CONFIRMED", "DELIVERY_UNAVAILABLE"]
DELIVERY_FEASIBILITY_STATUSES = ["PENDING", "APPROVED", "NOT_AVAILABLE", "NEEDS_REVIEW"]
DELIVERY_COST_MODES = ["AUTO", "MANUAL", "FREE"]
DELIVERY_REJECTION_REASONS = [
    "Too far", "No delivery route", "Vehicle unavailable",
    "Quantity too large", "Temporary restriction", "Other",
]

# New Order Alert + Call Management -- another independent axis on Order,
# same pattern as team_confirmation_status above. Deliberately NOT tied to
# team_confirmation_status: this tracks "did we phone the customer", a
# separate concern from delivery feasibility/cost, and doesn't gate it.
CALL_STATUSES = ["PENDING", "CALLED", "NO_ANSWER", "CALL_BACK", "CONFIRMED"]


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    slug = Column(String(140), unique=True, nullable=False, index=True)
    description = Column(Text, default="")
    image_url = Column(String(300), default="")
    display_order = Column(Integer, default=0)

    plants = relationship("Plant", back_populates="category", cascade="all, delete-orphan")

#  - AVAILABLE: normal purchase flow (Add to Cart / Buy Now), unchanged
#  - OUT_OF_STOCK: today's plain "can't buy this" state, no Enquire button
#  - ENQUIRY_AVAILABLE: hides Add to Cart / Buy Now, shows Enquire Now instead
# "DISABLED" from the product spec maps directly onto the existing
# `is_active` flag (already hides a plant from the site entirely) --
# deliberately not duplicated as a 4th value here, to avoid two flags that
# could disagree with each other.
PLANT_AVAILABILITY_STATUSES = ["AVAILABLE", "OUT_OF_STOCK", "ENQUIRY_AVAILABLE"]


class Plant(Base):
    __tablename__ = "plants"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    slug = Column(String(170), unique=True, nullable=False, index=True)
    description = Column(Text, default="")
    price = Column(Float, nullable=False, default=0, index=True)
    discount_price = Column(Float, nullable=True)
    stock_quantity = Column(Integer, default=0, index=True)
    sku = Column(String(50), default="")
    image_url = Column(String(300), default="")
    care_level = Column(String(50), default="Easy")
    features = Column(Text, default="")  # newline separated bullet features
    is_featured = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True, index=True)
    # Admin-controlled explicitly -- never auto-derived from stock_quantity,
    # so an OUT_OF_STOCK plant only becomes enquirable when the nursery
    # deliberately marks it so.
    availability_status = Column(String(20), nullable=False, default="AVAILABLE")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    category = relationship("Category", back_populates="plants")
    variants = relationship("PlantVariant", back_populates="plant", cascade="all, delete-orphan")
    reviews = relationship("PlantReview", back_populates="plant", cascade="all, delete-orphan")

    @property
    def feature_list(self):
        return [f.strip() for f in (self.features or "").split("\n") if f.strip()]

    @property
    def effective_price(self):
        return self.discount_price if self.discount_price else self.price

    @property
    def _published_reviews(self):
        return [r for r in self.reviews if r.status == "PUBLISHED"]

    @property
    def review_count(self):
        return len(self._published_reviews)

    @property
    def average_rating(self):
        published = self._published_reviews
        if not published:
            return None
        return round(sum(r.rating for r in published) / len(published), 2)


class PlantVariant(Base):
    """A tray-size option for seedlings sold in bulk (e.g. 125 or 150 plants per tray)."""

    __tablename__ = "plant_variants"
    __table_args__ = (
        UniqueConstraint("plant_id", "tray_size", name="uq_variant_plant_traysize"),
        # Admin edits replace all of a plant's variants via delete-then-recreate; without
        # true AUTOINCREMENT, SQLite can reuse a just-deleted id for the new row, which
        # would let a stale variant_id sitting in someone's cart silently resolve to a
        # different (wrong-price) tray option instead of failing the "no longer available" check.
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, index=True)
    plant_id = Column(Integer, ForeignKey("plants.id"), nullable=False, index=True)
    tray_size = Column(Integer, nullable=False)
    stock_quantity = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    plant = relationship("Plant", back_populates="variants")

    @property
    def price(self):
        return round(self.plant.price * self.tray_size, 2) if self.plant else 0


REVIEW_STATUSES = ["PENDING", "PUBLISHED", "REJECTED"]


class PlantReview(Base):
    """A star rating + comment on a plant, restricted to a customer whose
    order containing that plant has reached "Delivered" -- this is checked
    server-side against Order/OrderItem at creation time (never trusted from
    the client) and the qualifying order_id is stored alongside the review.
    One review per customer per plant, enforced at the database level (not
    just in the API), since a race between two tabs submitting at once could
    otherwise slip past an application-level check alone."""

    __tablename__ = "plant_reviews"
    __table_args__ = (
        UniqueConstraint("plant_id", "customer_id", name="uq_review_plant_customer"),
    )

    id = Column(Integer, primary_key=True, index=True)
    plant_id = Column(Integer, ForeignKey("plants.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, default="")
    # New reviews start PENDING and only count toward the public rating /
    # show up on the site once an admin moderates them to PUBLISHED -- see
    # PlantReview docstring and api_admin.py's /reviews endpoints.
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    plant = relationship("Plant", back_populates="reviews")
    customer = relationship("Customer")
    order = relationship("Order")

    @property
    def customer_name(self):
        return self.customer.name if self.customer else ""

    @property
    def plant_name(self):
        return self.plant.name if self.plant else ""


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    slug = Column(String(170), unique=True, nullable=False, index=True)
    description = Column(Text, default="")
    price = Column(Float, nullable=False, default=0)
    price_unit = Column(String(50), default="one-time")  # e.g. one-time, /visit, /month
    features = Column(Text, default="")
    image_url = Column(String(300), default="")
    display_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)

    @property
    def feature_list(self):
        return [f.strip() for f in (self.features or "").split("\n") if f.strip()]


class PricingPlan(Base):
    __tablename__ = "pricing_plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    price = Column(Float, nullable=False, default=0)
    billing_cycle = Column(String(30), default="monthly")  # monthly, yearly, one-time
    features = Column(Text, default="")
    is_featured = Column(Boolean, default=False)
    display_order = Column(Integer, default=0)

    @property
    def feature_list(self):
        return [f.strip() for f in (self.features or "").split("\n") if f.strip()]


class FAQ(Base):
    __tablename__ = "faqs"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(String(300), nullable=False)
    answer = Column(Text, nullable=False)
    display_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)


class Testimonial(Base):
    __tablename__ = "testimonials"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String(120), nullable=False)
    rating = Column(Integer, default=5)
    message = Column(Text, nullable=False)
    image_url = Column(String(300), default="")
    is_approved = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class GalleryImage(Base):
    __tablename__ = "gallery_images"

    id = Column(Integer, primary_key=True, index=True)
    image_url = Column(String(300), nullable=False)
    caption = Column(String(200), default="")
    category = Column(String(100), default="")
    display_order = Column(Integer, default=0)


class BlogPost(Base):
    __tablename__ = "blog_posts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    slug = Column(String(220), unique=True, nullable=False, index=True)
    content = Column(Text, nullable=False)
    excerpt = Column(String(400), default="")
    image_url = Column(String(300), default="")
    is_published = Column(Boolean, default=True)
    published_at = Column(DateTime, default=datetime.utcnow)


# Feature 1 (out-of-stock product enquiry): extends the existing generic
# contact-form Inquiry model rather than duplicating it with a parallel
# table. The legacy 3-value status set (new/contacted/closed) stays valid
# unchanged for old rows and the general "Enquire About This Plant" contact
# link; these 3 new values are additive, for the dedicated product-enquiry
# flow only.
INQUIRY_STATUSES = ["new", "contacted", "preparing", "available", "rejected", "closed"]


class Inquiry(Base):
    __tablename__ = "inquiries"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    mobile = Column(String(30), nullable=False)
    requirement = Column(Text, default="")
    status = Column(String(30), default="new")  # see INQUIRY_STATUSES
    plant_id = Column(Integer, ForeignKey("plants.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Added for the dedicated product-enquiry flow (Feature 1) -- all
    # nullable/defaulted so existing generic contact-form rows are
    # unaffected and the existing /inquiries endpoint needs no changes.
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    email = Column(String(180), default="")
    quantity = Column(Integer, nullable=True)
    enquiry_number = Column(String(30), nullable=True, unique=True, index=True)
    plant_name_snapshot = Column(String(150), default="")
    updated_at = Column(DateTime, nullable=True)

    plant = relationship("Plant")
    customer = relationship("Customer")


class InquiryStatusHistory(Base):
    """Timestamped status history for Feature 1 enquiries only -- distinct
    from AdminActivityLog (which is a shallow one-line-per-action log) and
    from Developer Live Logs (which is unrelated runtime/job output)."""

    __tablename__ = "inquiry_status_history"

    id = Column(Integer, primary_key=True, index=True)
    inquiry_id = Column(Integer, ForeignKey("inquiries.id"), nullable=False, index=True)
    old_status = Column(String(30), default="")
    new_status = Column(String(30), nullable=False)
    note = Column(String(300), default="")
    changed_by = Column(String(80), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class SiteSetting(Base):
    __tablename__ = "site_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, default="")


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(80), unique=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    # "developer" | "super_access" | "admin" | "custom". Widened (Developer
    # Dashboard RBAC phase) from the original "admin"/"developer" pair --
    # this column was never DB-constrained, only checked in application
    # code, so every existing `role == "developer"` check keeps working
    # unchanged for the two original values.
    role = Column(String(20), nullable=False, default="admin")
    created_at = Column(DateTime, default=datetime.utcnow)
    # Accounting module (Phase 4): a separate permission axis from `role`
    # above (which only governs Website Management / developer access).
    # NULL means "not yet assigned" -- treated as Viewer everywhere it's read.
    accounting_role = Column(String(20), nullable=True)

    # --- Developer Dashboard RBAC (module-level permissions, sessions, lockout) ---
    is_active = Column(Boolean, nullable=False, default=True)
    locked_until = Column(DateTime, nullable=True)
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    # Only meaningful when role == "custom" -- points at the Role row whose
    # RolePermission matrix defines this admin's module-level access.
    custom_role_id = Column(Integer, ForeignKey("roles.id"), nullable=True)


class AdminActivityLog(Base):
    __tablename__ = "admin_activity_log"

    id = Column(Integer, primary_key=True, index=True)
    admin_username = Column(String(80), nullable=False)
    action = Column(String(50), nullable=False)
    # Was String(200); widened to Text so RBAC audit entries (role/permission
    # changes) can store a JSON before/after diff. SQLite gives VARCHAR(200)
    # and TEXT identical storage affinity, so no ALTER TABLE is needed for
    # this change -- existing rows are read back exactly as before.
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class Role(Base):
    """A Developer-defined role governing module-level access (VIEW/CREATE/
    EDIT/DELETE/EXPORT/PRINT/APPROVE/CANCEL per module) for `custom`-role
    AdminUsers, plus the two seeded system rows ("Admin (Default)" and
    "Super Access") used to look up their matrices uniformly. This axis is
    layered ON TOP OF -- not a replacement for -- the existing
    `accounting_role` axis, which keeps governing fine-grained writes inside
    Accounting/Delivery/Labour exactly as before."""

    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(80), unique=True, nullable=False)
    description = Column(Text, default="")
    is_system = Column(Boolean, nullable=False, default=False)
    created_by = Column(String(80), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    permissions = relationship("RolePermission", back_populates="role", cascade="all, delete-orphan")


class RolePermission(Base):
    """One row per (role, module): the module-level action flags a member
    of that role is granted. Absence of a row for a given module means no
    access to that module at all (default deny)."""

    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "module", name="uq_role_module"),)

    id = Column(Integer, primary_key=True, index=True)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False, index=True)
    module = Column(String(40), nullable=False)

    can_view = Column(Boolean, nullable=False, default=False)
    can_create = Column(Boolean, nullable=False, default=False)
    can_edit = Column(Boolean, nullable=False, default=False)
    can_delete = Column(Boolean, nullable=False, default=False)
    can_export = Column(Boolean, nullable=False, default=False)
    can_print = Column(Boolean, nullable=False, default=False)
    can_approve = Column(Boolean, nullable=False, default=False)
    can_cancel = Column(Boolean, nullable=False, default=False)

    role = relationship("Role", back_populates="permissions")


class UserPermissionOverride(Base):
    """Developer-granted per-user exception to their role's permissions --
    either an explicit ALLOW (grants something their role doesn't) or an
    explicit DENY (takes away something their role would otherwise grant).
    See app/permissions.py for the precedence order this participates in."""

    __tablename__ = "user_permission_overrides"
    __table_args__ = (
        UniqueConstraint("admin_user_id", "module", "action", name="uq_override_user_module_action"),
    )

    id = Column(Integer, primary_key=True, index=True)
    admin_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=False, index=True)
    module = Column(String(40), nullable=False)
    action = Column(String(20), nullable=False)
    effect = Column(String(10), nullable=False)  # "ALLOW" | "DENY"
    granted_by = Column(String(80), nullable=False)
    reason = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


class AdminSession(Base):
    """A server-side record of one logged-in admin browser session, so the
    Developer Dashboard can list/revoke sessions -- something the previous
    pure-signed-cookie session (no DB record at all) could never support.
    `session_token` is the value stored inside the existing Starlette
    session cookie; revoking sets `revoked_at` so the next request bearing
    that cookie is rejected in app/deps.py:get_current_admin."""

    __tablename__ = "admin_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_token = Column(String(64), unique=True, nullable=False, index=True)
    admin_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=False, index=True)
    username = Column(String(80), nullable=False)
    ip_address = Column(String(64), default="")
    user_agent = Column(String(300), default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_seen_at = Column(DateTime, default=datetime.utcnow, index=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(80), nullable=True)
    revoke_reason = Column(String(200), nullable=True)


class LoginAttempt(Base):
    """Every admin login attempt (success or failure), used for the
    Developer Dashboard's login-attempt view and for lockout after repeated
    failures. Customer login attempts are also recorded here (harmless,
    same shape) but are not currently subject to lockout."""

    __tablename__ = "login_attempts"

    id = Column(Integer, primary_key=True, index=True)
    identifier = Column(String(180), nullable=False, index=True)
    ip_address = Column(String(64), default="")
    user_agent = Column(String(300), default="")
    success = Column(Boolean, nullable=False)
    reason = Column(String(80), default="")  # bad_password / unknown_user / locked / inactive
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class CustomerActivityLog(Base):
    __tablename__ = "customer_activity_log"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    action = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(180), unique=True, nullable=False, index=True)
    mobile = Column(String(30), default="")
    hashed_password = Column(String(200), nullable=False)
    reset_token = Column(String(100), nullable=True, index=True)
    reset_token_expires = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("customer_id", "plant_id", "variant_id", name="uq_cart_customer_plant_variant"),
    )

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    plant_id = Column(Integer, ForeignKey("plants.id"), nullable=False, index=True)
    variant_id = Column(Integer, ForeignKey("plant_variants.id"), nullable=True)
    quantity = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    plant = relationship("Plant")
    variant = relationship("PlantVariant")

    @property
    def unit_price(self):
        if self.variant_id:
            return self.variant.price if self.variant else (self.plant.effective_price if self.plant else 0)
        return self.plant.effective_price if self.plant else 0


class WishlistItem(Base):
    __tablename__ = "wishlist_items"
    __table_args__ = (UniqueConstraint("customer_id", "plant_id", name="uq_wishlist_customer_plant"),)

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    plant_id = Column(Integer, ForeignKey("plants.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    plant = relationship("Plant")


class Address(Base):
    __tablename__ = "addresses"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    full_name = Column(String(120), nullable=False)
    mobile = Column(String(30), nullable=False)
    line1 = Column(String(200), nullable=False)
    line2 = Column(String(200), default="")
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=False)
    pincode = Column(String(20), nullable=False)
    address_type = Column(String(20), default="Home")
    is_default = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    status = Column(String(30), default="Pending", index=True)
    payment_status = Column(String(30), default="Pending")
    payment_method = Column(String(30), default="COD")

    subtotal = Column(Float, default=0)
    shipping_fee = Column(Float, default=0)
    total_amount = Column(Float, default=0)

    razorpay_order_id = Column(String(100), nullable=True, index=True)
    razorpay_payment_id = Column(String(100), nullable=True)
    razorpay_signature = Column(String(255), nullable=True)
    idempotency_key = Column(String(64), nullable=True, index=True)

    delivery_name = Column(String(120), default="")
    delivery_mobile = Column(String(30), default="")
    delivery_line1 = Column(String(200), default="")
    delivery_line2 = Column(String(200), default="")
    delivery_city = Column(String(100), default="")
    delivery_state = Column(String(100), default="")
    delivery_pincode = Column(String(20), default="")

    # Feature 2 (delivery feasibility + team confirmation): an independent
    # axis from `status`/`payment_status`, same pattern as accounting_role/
    # business_role_id being separate axes on AdminUser -- keeps the
    # existing MAIN_STATUSES/_validate_status_transition forward-only order
    # lifecycle completely untouched. `shipping_fee` above IS the final
    # delivery cost once the team sets one; delivery_cost_calculated is
    # kept separately only for transparency (section 12: show both).
    team_confirmation_status = Column(String(30), nullable=False, default="PENDING")
    delivery_feasibility = Column(String(30), nullable=False, default="PENDING")
    delivery_distance_km = Column(Float, nullable=True)
    delivery_cost_calculated = Column(Float, nullable=True)
    delivery_cost_mode = Column(String(20), nullable=False, default="MANUAL")
    delivery_review_notes = Column(Text, default="")
    # Internal-only -- never included in the customer-facing OrderOut
    # schema (section 16: don't expose internal reasons to the customer).
    delivery_rejection_reason = Column(String(200), default="")
    team_confirmed_by = Column(String(80), default="")
    team_confirmed_at = Column(DateTime, nullable=True)

    # New Order Alert + Call Management -- independent of the above.
    call_status = Column(String(20), nullable=False, default="PENDING")
    assigned_to = Column(String(80), default="")  # AdminUser.username, or "" = unassigned
    order_acknowledged = Column(Boolean, nullable=False, default=False)
    acknowledged_by = Column(String(80), default="")
    acknowledged_at = Column(DateTime, nullable=True)

    tracking_number = Column(String(100), default="")
    delivery_partner = Column(String(100), default="")
    expected_delivery_date = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    notes = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = relationship("Customer")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    history = relationship(
        "OrderStatusHistory",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderStatusHistory.created_at",
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    plant_id = Column(Integer, ForeignKey("plants.id"), nullable=True)
    plant_name = Column(String(150), default="")
    plant_image_url = Column(String(300), default="")
    variant_id = Column(Integer, nullable=True)
    tray_size = Column(Integer, nullable=True)
    unit_price = Column(Float, default=0)
    quantity = Column(Integer, default=1)
    line_total = Column(Float, default=0)

    order = relationship("Order", back_populates="items")
    plant = relationship("Plant")

    @property
    def plant_slug(self):
        return self.plant.slug if self.plant else None


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    old_status = Column(String(30), nullable=True)
    new_status = Column(String(30), nullable=False)
    updated_by = Column(String(80), default="")
    remarks = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    order = relationship("Order", back_populates="history")


class Purchase(Base):
    """A procurement event/invoice -- one or more PurchaseItem batches. Recording a
    Purchase increments Plant.stock_quantity by each item's quantity. Deleting a
    Purchase does NOT decrement stock back out (received stock may already be sold
    or mixed with other stock by deletion time) -- admin UI must warn on delete."""

    __tablename__ = "purchases"

    id = Column(Integer, primary_key=True, index=True)
    purchase_date = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    supplier = Column(String(150), default="")
    invoice_number = Column(String(80), default="")
    notes = Column(Text, default="")
    total_cost = Column(Float, default=0)  # denormalized sum of item.total_cost
    created_by = Column(String(80), default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Added for the Accounting module (columns backfilled via an ALTER TABLE
    # shim in app/main.py, same pattern as every other schema change there) --
    # this lets the existing Purchase/PurchaseItem feature also serve as the
    # "Bill" concept in Accounting's UI, without a duplicate table.
    status = Column(String(20), nullable=False, default="Paid", index=True)
    due_date = Column(DateTime, nullable=True)
    source = Column(String(10), nullable=False, default="offline", index=True)
    contact_id = Column(Integer, nullable=True, index=True)
    # Phase 2: set when this Purchase/Bill was created by converting an
    # accounting Purchase Order -- plain Integer (no FK object), same
    # precedent as contact_id above.
    purchase_order_id = Column(Integer, nullable=True, index=True)

    items = relationship("PurchaseItem", back_populates="purchase", cascade="all, delete-orphan")


class PurchaseItem(Base):
    """One plant batch within a Purchase. unit_cost/total_cost are stored (not
    derived) so historical analytics stay accurate even if cost varies batch to
    batch -- mirrors how OrderItem snapshots unit_price at checkout."""

    __tablename__ = "purchase_items"

    id = Column(Integer, primary_key=True, index=True)
    purchase_id = Column(Integer, ForeignKey("purchases.id"), nullable=False, index=True)
    plant_id = Column(Integer, ForeignKey("plants.id"), nullable=False, index=True)
    plant_name = Column(String(150), default="")  # snapshot vs. later plant rename/delete
    quantity = Column(Integer, nullable=False, default=0)
    unit_cost = Column(Float, nullable=False, default=0)
    total_cost = Column(Float, default=0)  # = quantity * unit_cost at write time

    purchase = relationship("Purchase", back_populates="items")
    plant = relationship("Plant")
