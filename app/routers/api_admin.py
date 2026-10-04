import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from slugify import slugify
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.accounting.sync import sync_order_to_accounting
from app.analytics_utils import INACTIVE_DAYS
from app.audit import SUPER_ACCESS_GRANTED, SUPER_ACCESS_REVOKED, record_admin_audit
from app.auth import hash_password
from app.database import get_db
from app.deps import get_current_admin, get_current_developer
from app.inventory import adjust_stock, restore_stock
from app.permissions import require_permission
from app.models import (
    CANCELLABLE_STATUSES,
    FAQ,
    AdminActivityLog,
    AdminSession,
    AdminUser,
    BlogPost,
    Category,
    Customer,
    CustomerActivityLog,
    CALL_STATUSES,
    DELIVERY_COST_MODES,
    DELIVERY_FEASIBILITY_STATUSES,
    DELIVERY_REJECTION_REASONS,
    GalleryImage,
    INQUIRY_STATUSES,
    Inquiry,
    InquiryStatusHistory,
    MAIN_STATUSES,
    Order,
    OrderItem,
    OrderStatusHistory,
    PAYMENT_STATUSES,
    PLANT_AVAILABILITY_STATUSES,
    Plant,
    PlantReview,
    PlantVariant,
    PricingPlan,
    Purchase,
    PurchaseItem,
    REVIEW_STATUSES,
    Role,
    Service,
    SiteSetting,
    Testimonial,
)
from app.notifications import (
    notify_delivery_confirmed,
    notify_delivery_unavailable,
    notify_order_cancelled,
    notify_order_status,
)
from app.schemas import (
    ActivityLogOut,
    AdminPasswordResetIn,
    AdminRoleIn,
    AdminUserCreateIn,
    AdminUserOut,
    BlogPostIn,
    BlogPostOut,
    CategoryIn,
    CategoryOut,
    CustomerAdminDetailOut,
    CustomerAdminOut,
    CustomerOrderOut,
    FAQIn,
    FAQOut,
    GalleryImageIn,
    GalleryImageOut,
    InquiryOut,
    InquiryStatusHistoryOut,
    InquiryStatusIn,
    OrderAdminOut,
    OrderAdminUpdateIn,
    OrderAssignIn,
    OrderCallStatusIn,
    OrderCancelIn,
    OrderConfirmIn,
    OrderDeliveryReviewIn,
    OrderOut,
    OrderRejectDeliveryIn,
    OrderSummaryAdminOut,
    OrderSummaryOut,
    PlantIn,
    PlantOut,
    PlantVariantIn,
    PricingPlanIn,
    PricingPlanOut,
    PurchaseIn,
    PurchaseOut,
    ReviewAdminOut,
    ReviewModerateIn,
    ServiceIn,
    ServiceOut,
    SettingsIn,
    SystemInfoOut,
    TestimonialIn,
    TestimonialOut,
)
from app.settings_helper import get_settings


def log_activity(db: Session, admin_username: str, action: str, detail: str = ""):
    db.add(AdminActivityLog(admin_username=admin_username, action=action, detail=detail))
    db.commit()

router = APIRouter(prefix="/api/admin")


def unique_slug(db: Session, model, base_text: str, exclude_id: Optional[int] = None) -> str:
    base = slugify(base_text)
    slug = base
    counter = 2
    while True:
        query = db.query(model).filter(model.slug == slug)
        if exclude_id is not None:
            query = query.filter(model.id != exclude_id)
        if not query.first():
            return slug
        slug = f"{base}-{counter}"
        counter += 1


def get_or_404(db: Session, model, item_id: int):
    item = db.query(model).filter(model.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
    return item


def _validate_variants(variants: list[PlantVariantIn], price: float) -> None:
    if not variants:
        return
    if price <= 0:
        raise HTTPException(
            status_code=400, detail="Price per plant must be greater than 0 for tray products"
        )
    seen_sizes = set()
    for v in variants:
        if v.tray_size <= 0:
            raise HTTPException(status_code=400, detail="Tray size must be greater than 0")
        if v.stock_quantity < 0:
            raise HTTPException(status_code=400, detail="Tray stock cannot be negative")
        if v.tray_size in seen_sizes:
            raise HTTPException(status_code=400, detail=f"Duplicate tray size: {v.tray_size}")
        seen_sizes.add(v.tray_size)


def _validate_availability_status(value: str) -> None:
    if value not in PLANT_AVAILABILITY_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"availability_status must be one of: {', '.join(PLANT_AVAILABILITY_STATUSES)}",
        )


# ---------- Auth ----------
# Note: the real, live login path is POST /auth/login in app/api_public.py
# (unified_login) -- that's the only one frontend/src ever calls. The
# `/login` route that used to live here was dead code (unreferenced from
# any frontend page) and has been removed rather than kept as a second,
# unhardened path once /auth/login gains lockout/session/audit logic.


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    user = db.query(AdminUser).filter(AdminUser.username == admin).first()
    return {"username": admin, "role": user.role if user else "admin"}


# ---------- Admin management ----------

@router.get("/admins", response_model=list[AdminUserOut])
def list_admins(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return db.query(AdminUser).order_by(AdminUser.id).all()


ADMIN_ROLES = ("admin", "developer", "super_access", "custom")


def _validate_role_payload(db: Session, role: str, custom_role_id: Optional[int]) -> None:
    if role not in ADMIN_ROLES:
        raise HTTPException(status_code=400, detail=f"Role must be one of {ADMIN_ROLES}")
    if role == "custom":
        if not custom_role_id or not db.query(Role).filter(Role.id == custom_role_id, Role.is_system.is_(False)).first():
            raise HTTPException(status_code=400, detail="custom_role_id must reference an existing custom role")


@router.post("/admins", response_model=AdminUserOut, status_code=201)
def create_admin(
    payload: AdminUserCreateIn,
    admin: str = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    username = payload.username.strip()
    if not username or not payload.password:
        raise HTTPException(status_code=400, detail="Username and password are required")
    _validate_role_payload(db, payload.role, payload.custom_role_id)
    if db.query(AdminUser).filter(AdminUser.username == username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    item = AdminUser(
        username=username,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        custom_role_id=payload.custom_role_id if payload.role == "custom" else None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    log_activity(db, admin, "admin_created", username)
    if payload.role == "super_access":
        record_admin_audit(admin, SUPER_ACCESS_GRANTED, {"username": username})
    return item


@router.put("/admins/{item_id}/password", response_model=AdminUserOut)
def reset_admin_password(
    item_id: int,
    payload: AdminPasswordResetIn,
    admin: str = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    item = get_or_404(db, AdminUser, item_id)
    if not payload.password:
        raise HTTPException(status_code=400, detail="Password is required")
    item.hashed_password = hash_password(payload.password)
    # A password reset should invalidate every existing browser session for
    # this account -- otherwise a session opened with the OLD password stays
    # logged in indefinitely after the reset.
    now = datetime.utcnow()
    revoked = (
        db.query(AdminSession)
        .filter(AdminSession.admin_user_id == item.id, AdminSession.revoked_at.is_(None))
        .all()
    )
    for sess in revoked:
        sess.revoked_at = now
        sess.revoked_by = admin
        sess.revoke_reason = "password_reset"
    db.commit()
    log_activity(db, admin, "password_reset", item.username)
    return item


@router.put("/admins/{item_id}/role", response_model=AdminUserOut)
def change_admin_role(
    item_id: int,
    payload: AdminRoleIn,
    admin: str = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    item = get_or_404(db, AdminUser, item_id)
    _validate_role_payload(db, payload.role, payload.custom_role_id)
    if item.role == "developer" and payload.role != "developer":
        remaining = db.query(AdminUser).filter(AdminUser.role == "developer", AdminUser.id != item_id).count()
        if remaining == 0:
            raise HTTPException(status_code=400, detail="Cannot demote the last remaining developer")

    was_super_access = item.role == "super_access"
    item.role = payload.role
    item.custom_role_id = payload.custom_role_id if payload.role == "custom" else None
    db.commit()
    log_activity(db, admin, "role_changed", f"{item.username} -> {payload.role}")
    if payload.role == "super_access" and not was_super_access:
        record_admin_audit(admin, SUPER_ACCESS_GRANTED, {"username": item.username})
    elif was_super_access and payload.role != "super_access":
        record_admin_audit(admin, SUPER_ACCESS_REVOKED, {"username": item.username})
    return item


@router.delete("/admins/{item_id}", status_code=204)
def delete_admin(
    item_id: int,
    admin: str = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    item = get_or_404(db, AdminUser, item_id)
    if item.username == admin:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if item.role == "developer":
        remaining = db.query(AdminUser).filter(AdminUser.role == "developer", AdminUser.id != item_id).count()
        if remaining == 0:
            raise HTTPException(status_code=400, detail="Cannot delete the last remaining developer")
    db.delete(item)
    db.commit()
    log_activity(db, admin, "admin_deleted", item.username)


@router.get("/activity-log", response_model=list[ActivityLogOut])
def list_activity_log(admin: str = Depends(get_current_developer), db: Session = Depends(get_db)):
    return db.query(AdminActivityLog).order_by(AdminActivityLog.created_at.desc()).limit(100).all()


@router.get("/system-info", response_model=SystemInfoOut)
def system_info(admin: str = Depends(get_current_developer), db: Session = Depends(get_db)):
    counts = {
        "categories": db.query(Category).count(),
        "plants": db.query(Plant).count(),
        "services": db.query(Service).count(),
        "testimonials": db.query(Testimonial).count(),
        "gallery_images": db.query(GalleryImage).count(),
        "blog_posts": db.query(BlogPost).count(),
        "inquiries": db.query(Inquiry).count(),
        "customers": db.query(Customer).count(),
        "orders": db.query(Order).count(),
        "admin_users": db.query(AdminUser).count(),
    }
    return SystemInfoOut(counts=counts, session_secret_is_default="SESSION_SECRET_KEY" not in os.environ)


@router.get("/backup")
def download_backup(admin: str = Depends(get_current_developer)):
    # The live DB lives wherever DATABASE_URL points (shared/ on the server,
    # not the code directory), and copying a SQLite file mid-write can yield
    # a corrupt backup -- so take a consistent snapshot via sqlite3's backup API.
    import sqlite3
    import tempfile

    from starlette.background import BackgroundTask

    from app.database import engine

    src_path = engine.url.database
    if not src_path or not os.path.exists(src_path):
        raise HTTPException(status_code=500, detail="Database file not found.")
    fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(tmp_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M")
    return FileResponse(
        tmp_path,
        filename=f"aaiji_nursery_backup_{stamp}.db",
        media_type="application/octet-stream",
        background=BackgroundTask(os.remove, tmp_path),
    )


# ---------- Dashboard ----------

@router.get("/dashboard")
def dashboard(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    counts = {
        "categories": db.query(Category).count(),
        "plants": db.query(Plant).count(),
        "services": db.query(Service).count(),
        "inquiries": db.query(Inquiry).count(),
        "testimonials": db.query(Testimonial).count(),
        "blog_posts": db.query(BlogPost).count(),
        "customer_logins": db.query(CustomerActivityLog).filter(CustomerActivityLog.action == "login").count(),
    }
    recent_inquiries = (
        db.query(Inquiry)
        .options(joinedload(Inquiry.plant))
        .order_by(Inquiry.created_at.desc())
        .limit(5)
        .all()
    )

    # New Order Alert + Call Management stats (section 9).
    order_stats = {
        "new_orders": db.query(Order).filter(Order.status == "Pending").count(),
        "calls_pending": db.query(Order).filter(
            Order.status == "Pending", Order.call_status.in_(["PENDING", "NO_ANSWER", "CALL_BACK"])
        ).count(),
        "preparing": db.query(Order).filter(Order.status == "Processing").count(),
        "out_for_delivery": db.query(Order).filter(Order.status == "Out For Delivery").count(),
        "delivered": db.query(Order).filter(Order.status == "Delivered").count(),
    }

    recent_new_orders = (
        db.query(Order)
        .options(joinedload(Order.customer))
        .filter(Order.status == "Pending")
        .order_by(Order.created_at.desc())
        .limit(10)
        .all()
    )

    return {
        "counts": counts,
        "order_stats": order_stats,
        "recent_new_orders": [OrderSummaryAdminOut.model_validate(o) for o in recent_new_orders],
        "recent_inquiries": [InquiryOut.model_validate(i) for i in recent_inquiries],
    }


@router.get("/customer-logs", dependencies=[Depends(require_permission("customers", "VIEW"))])
def list_customer_logs(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    purchased_ids = {row[0] for row in db.query(Order.customer_id).distinct().all()}
    logs = (
        db.query(CustomerActivityLog, Customer)
        .join(Customer, Customer.id == CustomerActivityLog.customer_id)
        .filter(CustomerActivityLog.customer_id.notin_(purchased_ids) if purchased_ids else True)
        .order_by(CustomerActivityLog.created_at.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": log.id,
            "customer_id": customer.id,
            "customer_name": customer.name,
            "customer_email": customer.email,
            "action": log.action,
            "created_at": log.created_at,
        }
        for log, customer in logs
    ]


# ---------- Categories ----------

@router.get("/categories", dependencies=[Depends(require_permission("products", "VIEW"))], response_model=list[CategoryOut])
def list_categories(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return db.query(Category).order_by(Category.display_order).all()


@router.post("/categories", dependencies=[Depends(require_permission("products", "CREATE"))], response_model=CategoryOut, status_code=201)
def create_category(
    payload: CategoryIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = Category(
        name=payload.name.strip(),
        slug=unique_slug(db, Category, payload.name),
        description=payload.description.strip(),
        image_url=payload.image_url.strip(),
        display_order=payload.display_order,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/categories/{item_id}", dependencies=[Depends(require_permission("products", "EDIT"))], response_model=CategoryOut)
def update_category(
    item_id: int,
    payload: CategoryIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    item = get_or_404(db, Category, item_id)
    if item.name != payload.name.strip():
        item.slug = unique_slug(db, Category, payload.name, exclude_id=item.id)
    item.name = payload.name.strip()
    item.description = payload.description.strip()
    item.image_url = payload.image_url.strip()
    item.display_order = payload.display_order
    db.commit()
    db.refresh(item)
    return item


@router.delete("/categories/{item_id}", dependencies=[Depends(require_permission("products", "DELETE"))], status_code=204)
def delete_category(
    item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = get_or_404(db, Category, item_id)
    db.delete(item)
    db.commit()


# ---------- Plants ----------

@router.get("/plants", dependencies=[Depends(require_permission("products", "VIEW"))], response_model=list[PlantOut])
def list_plants(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return (
        db.query(Plant)
        .options(selectinload(Plant.variants))
        .order_by(Plant.category_id)
        .all()
    )


@router.post("/plants", dependencies=[Depends(require_permission("products", "CREATE"))], response_model=PlantOut, status_code=201)
def create_plant(
    payload: PlantIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    _validate_variants(payload.variants or [], payload.price)
    _validate_availability_status(payload.availability_status)
    item = Plant(
        name=payload.name.strip(),
        slug=unique_slug(db, Plant, payload.name),
        category_id=payload.category_id,
        description=payload.description.strip(),
        price=payload.price,
        discount_price=payload.discount_price,
        stock_quantity=payload.stock_quantity,
        sku=payload.sku.strip(),
        image_url=payload.image_url.strip(),
        care_level=payload.care_level.strip(),
        features=payload.features.strip(),
        is_featured=payload.is_featured,
        is_active=payload.is_active,
        availability_status=payload.availability_status,
    )
    db.add(item)
    db.flush()

    if payload.variants:
        for v in payload.variants:
            db.add(PlantVariant(plant_id=item.id, tray_size=v.tray_size, stock_quantity=v.stock_quantity))
        item.stock_quantity = sum(v.stock_quantity for v in payload.variants)

    db.commit()
    db.refresh(item)
    return item


@router.put("/plants/{item_id}", dependencies=[Depends(require_permission("products", "EDIT"))], response_model=PlantOut)
def update_plant(
    item_id: int,
    payload: PlantIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    item = get_or_404(db, Plant, item_id)
    _validate_variants(payload.variants or [], payload.price)
    _validate_availability_status(payload.availability_status)
    if item.name != payload.name.strip():
        item.slug = unique_slug(db, Plant, payload.name, exclude_id=item.id)
    item.name = payload.name.strip()
    item.category_id = payload.category_id
    item.description = payload.description.strip()
    item.price = payload.price
    item.discount_price = payload.discount_price
    item.stock_quantity = payload.stock_quantity
    item.sku = payload.sku.strip()
    item.image_url = payload.image_url.strip()
    item.care_level = payload.care_level.strip()
    item.features = payload.features.strip()
    item.is_featured = payload.is_featured
    item.is_active = payload.is_active
    item.availability_status = payload.availability_status

    if payload.variants is not None:
        db.query(PlantVariant).filter(PlantVariant.plant_id == item.id).delete()
        for v in payload.variants:
            db.add(PlantVariant(plant_id=item.id, tray_size=v.tray_size, stock_quantity=v.stock_quantity))
        if payload.variants:
            item.stock_quantity = sum(v.stock_quantity for v in payload.variants)

    db.commit()
    db.refresh(item)
    return item


@router.delete("/plants/{item_id}", dependencies=[Depends(require_permission("products", "DELETE"))], status_code=204)
def delete_plant(
    item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = get_or_404(db, Plant, item_id)
    db.delete(item)
    db.commit()


# ---------- Purchases (procurement) ----------

@router.get("/purchases", dependencies=[Depends(require_permission("products", "VIEW"))], response_model=list[PurchaseOut])
def list_purchases(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return (
        db.query(Purchase)
        .options(selectinload(Purchase.items))
        .order_by(Purchase.purchase_date.desc())
        .all()
    )


@router.post("/purchases", dependencies=[Depends(require_permission("products", "CREATE"))], response_model=PurchaseOut, status_code=201)
def create_purchase(
    payload: PurchaseIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    if not payload.items:
        raise HTTPException(status_code=400, detail="At least one purchase item is required")
    plant_ids = {i.plant_id for i in payload.items}
    plants = {p.id: p for p in db.query(Plant).filter(Plant.id.in_(plant_ids)).all()}
    missing = plant_ids - plants.keys()
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown plant id(s): {sorted(missing)}")

    purchase = Purchase(
        purchase_date=payload.purchase_date,
        supplier=payload.supplier.strip(),
        invoice_number=payload.invoice_number.strip(),
        notes=payload.notes.strip(),
        created_by=admin,
    )
    db.add(purchase)
    db.flush()

    total = 0.0
    for item in payload.items:
        if item.quantity <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be greater than 0")
        if item.unit_cost < 0:
            raise HTTPException(status_code=400, detail="Unit cost cannot be negative")
        plant = plants[item.plant_id]
        line_total = round(item.quantity * item.unit_cost, 2)
        db.add(
            PurchaseItem(
                purchase_id=purchase.id,
                plant_id=plant.id,
                plant_name=plant.name,
                quantity=item.quantity,
                unit_cost=item.unit_cost,
                total_cost=line_total,
            )
        )
        # procurement receipt increments live stock -- reference is per
        # purchase+plant since one Purchase can list several plants
        adjust_stock(
            db,
            plant_id=plant.id,
            quantity_delta=item.quantity,
            transaction_type="PURCHASE_RECEIVED",
            source_type="PURCHASE",
            source_id=purchase.id,
            reference=f"PURCHASE:{purchase.id}:PURCHASE_RECEIVED:{plant.id}",
            created_by=admin,
        )
        total += line_total

    purchase.total_cost = round(total, 2)
    db.commit()
    db.refresh(purchase)
    log_activity(
        db, admin, "purchase_created", f"Purchase #{purchase.id}: {payload.supplier or 'Unknown supplier'}"
    )
    return purchase


@router.delete("/purchases/{item_id}", dependencies=[Depends(require_permission("products", "DELETE"))], status_code=204)
def delete_purchase(
    item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = get_or_404(db, Purchase, item_id)
    # Intentionally does not decrement Plant.stock_quantity back out -- received
    # stock may already be sold or mixed with other stock by deletion time.
    db.delete(item)
    db.commit()
    log_activity(db, admin, "purchase_deleted", f"Purchase #{item.id}")


# ---------- Services ----------

@router.get("/services", dependencies=[Depends(require_permission("website", "VIEW"))], response_model=list[ServiceOut])
def list_services(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return db.query(Service).order_by(Service.display_order).all()


@router.post("/services", dependencies=[Depends(require_permission("website", "CREATE"))], response_model=ServiceOut, status_code=201)
def create_service(
    payload: ServiceIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = Service(
        name=payload.name.strip(),
        slug=unique_slug(db, Service, payload.name),
        description=payload.description.strip(),
        price=payload.price,
        price_unit=payload.price_unit.strip(),
        features=payload.features.strip(),
        image_url=payload.image_url.strip(),
        display_order=payload.display_order,
        is_active=payload.is_active,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/services/{item_id}", dependencies=[Depends(require_permission("website", "EDIT"))], response_model=ServiceOut)
def update_service(
    item_id: int,
    payload: ServiceIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    item = get_or_404(db, Service, item_id)
    if item.name != payload.name.strip():
        item.slug = unique_slug(db, Service, payload.name, exclude_id=item.id)
    item.name = payload.name.strip()
    item.description = payload.description.strip()
    item.price = payload.price
    item.price_unit = payload.price_unit.strip()
    item.features = payload.features.strip()
    item.image_url = payload.image_url.strip()
    item.display_order = payload.display_order
    item.is_active = payload.is_active
    db.commit()
    db.refresh(item)
    return item


@router.delete("/services/{item_id}", dependencies=[Depends(require_permission("website", "DELETE"))], status_code=204)
def delete_service(
    item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = get_or_404(db, Service, item_id)
    db.delete(item)
    db.commit()


# ---------- Pricing Plans ----------

@router.get("/pricing-plans", dependencies=[Depends(require_permission("website", "VIEW"))], response_model=list[PricingPlanOut])
def list_pricing_plans(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return db.query(PricingPlan).order_by(PricingPlan.display_order).all()


@router.post("/pricing-plans", dependencies=[Depends(require_permission("website", "CREATE"))], response_model=PricingPlanOut, status_code=201)
def create_pricing_plan(
    payload: PricingPlanIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = PricingPlan(
        name=payload.name.strip(),
        price=payload.price,
        billing_cycle=payload.billing_cycle.strip(),
        features=payload.features.strip(),
        is_featured=payload.is_featured,
        display_order=payload.display_order,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/pricing-plans/{item_id}", dependencies=[Depends(require_permission("website", "EDIT"))], response_model=PricingPlanOut)
def update_pricing_plan(
    item_id: int,
    payload: PricingPlanIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    item = get_or_404(db, PricingPlan, item_id)
    item.name = payload.name.strip()
    item.price = payload.price
    item.billing_cycle = payload.billing_cycle.strip()
    item.features = payload.features.strip()
    item.is_featured = payload.is_featured
    item.display_order = payload.display_order
    db.commit()
    db.refresh(item)
    return item


@router.delete("/pricing-plans/{item_id}", dependencies=[Depends(require_permission("website", "DELETE"))], status_code=204)
def delete_pricing_plan(
    item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = get_or_404(db, PricingPlan, item_id)
    db.delete(item)
    db.commit()


# ---------- FAQs ----------

@router.get("/faqs", dependencies=[Depends(require_permission("website", "VIEW"))], response_model=list[FAQOut])
def list_faqs(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return db.query(FAQ).order_by(FAQ.display_order).all()


@router.post("/faqs", dependencies=[Depends(require_permission("website", "CREATE"))], response_model=FAQOut, status_code=201)
def create_faq(
    payload: FAQIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = FAQ(
        question=payload.question.strip(),
        answer=payload.answer.strip(),
        display_order=payload.display_order,
        is_active=payload.is_active,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/faqs/{item_id}", dependencies=[Depends(require_permission("website", "EDIT"))], response_model=FAQOut)
def update_faq(
    item_id: int,
    payload: FAQIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    item = get_or_404(db, FAQ, item_id)
    item.question = payload.question.strip()
    item.answer = payload.answer.strip()
    item.display_order = payload.display_order
    item.is_active = payload.is_active
    db.commit()
    db.refresh(item)
    return item


@router.delete("/faqs/{item_id}", dependencies=[Depends(require_permission("website", "DELETE"))], status_code=204)
def delete_faq(item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    item = get_or_404(db, FAQ, item_id)
    db.delete(item)
    db.commit()


# ---------- Testimonials ----------

@router.get("/testimonials", dependencies=[Depends(require_permission("website", "VIEW"))], response_model=list[TestimonialOut])
def list_testimonials(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return db.query(Testimonial).order_by(Testimonial.created_at.desc()).all()


@router.post("/testimonials", dependencies=[Depends(require_permission("website", "CREATE"))], response_model=TestimonialOut, status_code=201)
def create_testimonial(
    payload: TestimonialIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = Testimonial(
        customer_name=payload.customer_name.strip(),
        rating=payload.rating,
        message=payload.message.strip(),
        image_url=payload.image_url.strip(),
        is_approved=payload.is_approved,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/testimonials/{item_id}", dependencies=[Depends(require_permission("website", "EDIT"))], response_model=TestimonialOut)
def update_testimonial(
    item_id: int,
    payload: TestimonialIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    item = get_or_404(db, Testimonial, item_id)
    item.customer_name = payload.customer_name.strip()
    item.rating = payload.rating
    item.message = payload.message.strip()
    item.image_url = payload.image_url.strip()
    item.is_approved = payload.is_approved
    db.commit()
    db.refresh(item)
    return item


@router.delete("/testimonials/{item_id}", dependencies=[Depends(require_permission("website", "DELETE"))], status_code=204)
def delete_testimonial(
    item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = get_or_404(db, Testimonial, item_id)
    db.delete(item)
    db.commit()


# ---------- Plant Reviews ----------
# Reuses the "products" module permission (same one Plants/Categories use)
# rather than introducing a new RBAC module just for this.

@router.get("/reviews", dependencies=[Depends(require_permission("products", "VIEW"))], response_model=list[ReviewAdminOut])
def list_reviews(
    status: Optional[str] = None,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(PlantReview).options(joinedload(PlantReview.plant), joinedload(PlantReview.customer))
    if status:
        query = query.filter(PlantReview.status == status)
    return query.order_by(PlantReview.created_at.desc()).all()


@router.patch("/reviews/{item_id}", dependencies=[Depends(require_permission("products", "EDIT"))], response_model=ReviewAdminOut)
def moderate_review(
    item_id: int,
    payload: ReviewModerateIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if payload.status not in REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    item = get_or_404(db, PlantReview, item_id)
    item.status = payload.status
    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return item


@router.delete("/reviews/{item_id}", dependencies=[Depends(require_permission("products", "DELETE"))], status_code=204)
def delete_review(item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    item = get_or_404(db, PlantReview, item_id)
    db.delete(item)
    db.commit()


# ---------- Gallery ----------

@router.get("/gallery", dependencies=[Depends(require_permission("website", "VIEW"))], response_model=list[GalleryImageOut])
def list_gallery(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return db.query(GalleryImage).order_by(GalleryImage.display_order).all()


@router.post("/gallery", dependencies=[Depends(require_permission("website", "CREATE"))], response_model=GalleryImageOut, status_code=201)
def create_gallery_image(
    payload: GalleryImageIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = GalleryImage(
        image_url=payload.image_url.strip(),
        caption=payload.caption.strip(),
        category=payload.category.strip(),
        display_order=payload.display_order,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/gallery/{item_id}", dependencies=[Depends(require_permission("website", "EDIT"))], response_model=GalleryImageOut)
def update_gallery_image(
    item_id: int,
    payload: GalleryImageIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    item = get_or_404(db, GalleryImage, item_id)
    item.image_url = payload.image_url.strip()
    item.caption = payload.caption.strip()
    item.category = payload.category.strip()
    item.display_order = payload.display_order
    db.commit()
    db.refresh(item)
    return item


@router.delete("/gallery/{item_id}", dependencies=[Depends(require_permission("website", "DELETE"))], status_code=204)
def delete_gallery_image(
    item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = get_or_404(db, GalleryImage, item_id)
    db.delete(item)
    db.commit()


# ---------- Blog ----------

@router.get("/blog", dependencies=[Depends(require_permission("website", "VIEW"))], response_model=list[BlogPostOut])
def list_blog_posts(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return db.query(BlogPost).order_by(BlogPost.published_at.desc()).all()


@router.post("/blog", dependencies=[Depends(require_permission("website", "CREATE"))], response_model=BlogPostOut, status_code=201)
def create_blog_post(
    payload: BlogPostIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = BlogPost(
        title=payload.title.strip(),
        slug=unique_slug(db, BlogPost, payload.title),
        excerpt=payload.excerpt.strip(),
        content=payload.content.strip(),
        image_url=payload.image_url.strip(),
        is_published=payload.is_published,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/blog/{item_id}", dependencies=[Depends(require_permission("website", "EDIT"))], response_model=BlogPostOut)
def update_blog_post(
    item_id: int,
    payload: BlogPostIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    item = get_or_404(db, BlogPost, item_id)
    if item.title != payload.title.strip():
        item.slug = unique_slug(db, BlogPost, payload.title, exclude_id=item.id)
    item.title = payload.title.strip()
    item.excerpt = payload.excerpt.strip()
    item.content = payload.content.strip()
    item.image_url = payload.image_url.strip()
    item.is_published = payload.is_published
    db.commit()
    db.refresh(item)
    return item


@router.delete("/blog/{item_id}", dependencies=[Depends(require_permission("website", "DELETE"))], status_code=204)
def delete_blog_post(
    item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = get_or_404(db, BlogPost, item_id)
    db.delete(item)
    db.commit()


# ---------- Inquiries ----------

@router.get("/inquiries", dependencies=[Depends(require_permission("customers", "VIEW"))], response_model=list[InquiryOut])
def list_inquiries(
    q: Optional[str] = None,
    status: Optional[str] = None,
    plant_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Inquiry).options(joinedload(Inquiry.plant))
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Inquiry.name.ilike(like),
                Inquiry.mobile.ilike(like),
                Inquiry.enquiry_number.ilike(like),
                Inquiry.plant_name_snapshot.ilike(like),
            )
        )
    if status:
        query = query.filter(Inquiry.status == status)
    if plant_id:
        query = query.filter(Inquiry.plant_id == plant_id)
    if date_from:
        query = query.filter(Inquiry.created_at >= date_from)
    if date_to:
        query = query.filter(Inquiry.created_at < date_to + timedelta(days=1))
    return query.order_by(Inquiry.created_at.desc()).all()


@router.put("/inquiries/{item_id}/status", dependencies=[Depends(require_permission("customers", "EDIT"))], response_model=InquiryOut)
def update_inquiry_status(
    item_id: int,
    payload: InquiryStatusIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if payload.status not in INQUIRY_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of: {', '.join(INQUIRY_STATUSES)}")
    item = get_or_404(db, Inquiry, item_id)
    old_status = item.status
    item.status = payload.status
    item.updated_at = datetime.utcnow()
    db.add(InquiryStatusHistory(inquiry_id=item.id, old_status=old_status, new_status=payload.status, note=payload.note.strip(), changed_by=admin))
    db.commit()
    db.refresh(item)
    return item


@router.get(
    "/inquiries/{item_id}/history",
    dependencies=[Depends(require_permission("customers", "VIEW"))],
    response_model=list[InquiryStatusHistoryOut],
)
def get_inquiry_history(item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    get_or_404(db, Inquiry, item_id)
    return (
        db.query(InquiryStatusHistory)
        .filter(InquiryStatusHistory.inquiry_id == item_id)
        .order_by(InquiryStatusHistory.created_at.asc())
        .all()
    )


@router.delete("/inquiries/{item_id}", dependencies=[Depends(require_permission("customers", "DELETE"))], status_code=204)
def delete_inquiry(
    item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    item = get_or_404(db, Inquiry, item_id)
    db.delete(item)
    db.commit()


# ---------- Orders ----------


def _get_order_or_404(db: Session, order_id: int) -> Order:
    order = (
        db.query(Order)
        .options(joinedload(Order.items), joinedload(Order.history), joinedload(Order.customer))
        .filter(Order.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def _validate_status_transition(current: str, new: str) -> None:
    if new == current:
        raise HTTPException(status_code=400, detail="Order is already in this status")
    if new == "Cancelled":
        raise HTTPException(
            status_code=400, detail="Use the Cancel Order action to cancel this order"
        )
    if current not in MAIN_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"Order is {current} and its status can no longer be changed"
        )
    if new not in MAIN_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if MAIN_STATUSES.index(new) < MAIN_STATUSES.index(current):
        raise HTTPException(
            status_code=400, detail=f"Cannot move status backward from {current} to {new}"
        )


@router.get("/orders", dependencies=[Depends(require_permission("orders", "VIEW"))], response_model=list[OrderSummaryAdminOut])
def list_orders(
    response: Response,
    search: Optional[str] = None,
    status: Optional[str] = None,
    page: Optional[int] = None,
    limit: Optional[int] = None,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Order)
        .options(joinedload(Order.items), joinedload(Order.customer))
        .join(Customer)
    )

    if search:
        term = search.strip()
        like = f"%{term}%"
        if term.isdigit() and len(term) <= 6:
            # Short all-digit input is almost certainly an order ID, not a
            # phone number fragment — matching it against mobile numbers
            # (which contain most digits by chance) caused unrelated orders
            # to show up. Treat it as an exact ID lookup instead.
            query = query.filter(Order.id == int(term))
        else:
            conditions = [
                Customer.name.ilike(like),
                Customer.email.ilike(like),
                Customer.mobile.ilike(like),
                Order.delivery_name.ilike(like),
                Order.delivery_mobile.ilike(like),
            ]
            query = query.filter(or_(*conditions))

    if status:
        query = query.filter(Order.status == status)

    query = query.order_by(Order.created_at.desc())
    total = query.count()

    if page is None and limit is None:
        items = query.all()
        page = 1
        limit = total or 1
    else:
        page = max(page or 1, 1)
        limit = min(max(limit or 20, 1), 100)
        items = query.offset((page - 1) * limit).limit(limit).all()

    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page)
    response.headers["X-Total-Pages"] = str(max(1, -(-total // limit)))
    return items


@router.get("/orders/{order_id}", dependencies=[Depends(require_permission("orders", "VIEW"))], response_model=OrderAdminOut)
def get_order(order_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _get_order_or_404(db, order_id)


@router.put("/orders/{order_id}/status", dependencies=[Depends(require_permission("orders", "EDIT"))], response_model=OrderAdminOut)
def update_order_status(
    order_id: int,
    payload: OrderAdminUpdateIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    order = _get_order_or_404(db, order_id)
    old_status = order.status
    status_changed = False

    if payload.status is not None and payload.status != order.status:
        # Feature 2: an order can't progress past its initial "Pending"
        # placement until the team has confirmed delivery feasibility and
        # cost -- mirrors the payment-side guard in verify_payment().
        if order.team_confirmation_status != "CONFIRMED":
            raise HTTPException(
                status_code=400,
                detail="This order is still awaiting team delivery confirmation. Confirm or reject delivery first.",
            )
        _validate_status_transition(order.status, payload.status)
        order.status = payload.status
        status_changed = True
        if order.status == "Delivered":
            order.delivered_at = datetime.utcnow()

    if payload.tracking_number is not None:
        order.tracking_number = payload.tracking_number
    if payload.delivery_partner is not None:
        order.delivery_partner = payload.delivery_partner
    if payload.expected_delivery_date is not None:
        order.expected_delivery_date = payload.expected_delivery_date
    if payload.notes is not None:
        order.notes = payload.notes
    if payload.payment_status is not None:
        if payload.payment_status not in PAYMENT_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid payment status")
        order.payment_status = payload.payment_status

    if status_changed:
        db.add(
            OrderStatusHistory(
                order_id=order.id,
                old_status=old_status,
                new_status=order.status,
                updated_by=admin,
                remarks=payload.remarks or f"Status updated to {order.status}",
            )
        )
    db.commit()
    sync_order_to_accounting(order.id)

    order = _get_order_or_404(db, order_id)
    if status_changed:
        log_activity(db, admin, "order_status_update", f"Order #{order.id}: {old_status} -> {order.status}")
        notify_order_status(order, old_status, order.status)
    return order


@router.post("/orders/{order_id}/cancel", dependencies=[Depends(require_permission("orders", "CANCEL"))], response_model=OrderAdminOut)
def admin_cancel_order(
    order_id: int,
    payload: OrderCancelIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    order = _get_order_or_404(db, order_id)
    if order.status not in CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"Orders can no longer be cancelled once they are {order.status}"
        )

    for item in order.items:
        if item.plant_id:
            restore_stock(
                db,
                plant_id=item.plant_id,
                variant_id=item.variant_id,
                quantity=item.quantity,
                source_type="ORDER_CANCELLATION",
                source_id=order.id,
                reference=f"ORDER:{order.id}:SALE_REVERSAL:{item.variant_id or item.plant_id}",
                created_by=admin,
            )

    old_status = order.status
    order.status = "Cancelled"
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            old_status=old_status,
            new_status="Cancelled",
            updated_by=admin,
            remarks=payload.remarks or "Cancelled by admin",
        )
    )
    db.commit()
    sync_order_to_accounting(order.id)

    order = _get_order_or_404(db, order_id)
    log_activity(db, admin, "order_cancel", f"Order #{order.id} cancelled")
    notify_order_cancelled(db, order, old_status, cancelled_by="admin", reason=payload.remarks)
    return order


# ---------- New Order Alert + Call Management ----------
# RBAC: reuses the existing "orders" module (VIEW/EDIT), same gate as the
# rest of this Orders section -- no new permission module needed.

@router.post(
    "/orders/{order_id}/acknowledge",
    dependencies=[Depends(require_permission("orders", "EDIT"))],
    response_model=OrderAdminOut,
)
def acknowledge_order(order_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Marks the new-order alert as seen/handled (section 7) -- the order
    itself stays fully visible in the Orders list/queue until its workflow
    actually completes; only the "still needs someone to look at it" signal
    is cleared."""
    order = _get_order_or_404(db, order_id)
    if not order.order_acknowledged:
        order.order_acknowledged = True
        order.acknowledged_by = admin
        order.acknowledged_at = datetime.utcnow()
        db.commit()
    return _get_order_or_404(db, order_id)


@router.post(
    "/orders/{order_id}/assign",
    dependencies=[Depends(require_permission("orders", "EDIT"))],
    response_model=OrderAdminOut,
)
def assign_order(
    order_id: int,
    payload: OrderAssignIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    order = _get_order_or_404(db, order_id)
    target = (payload.assigned_to or "").strip()
    if target and not db.query(AdminUser).filter(AdminUser.username == target).first():
        raise HTTPException(status_code=400, detail="No such admin user")
    order.assigned_to = target
    db.commit()
    log_activity(db, admin, "order_assigned", f"Order #{order.id} -> {target or 'Unassigned'}")
    return _get_order_or_404(db, order_id)


@router.put(
    "/orders/{order_id}/call-status",
    dependencies=[Depends(require_permission("orders", "EDIT"))],
    response_model=OrderAdminOut,
)
def update_call_status(
    order_id: int,
    payload: OrderCallStatusIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if payload.call_status not in CALL_STATUSES:
        raise HTTPException(status_code=400, detail=f"call_status must be one of: {', '.join(CALL_STATUSES)}")
    order = _get_order_or_404(db, order_id)
    order.call_status = payload.call_status
    # remarks is shared with the customer (OrderOut.history) -- keep it to
    # the same state word the customer can already see (call_status isn't
    # even in their schema, but there's no reason to add internal call
    # commentary like "tried 3 times, no pickup" into shared history).
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            old_status=order.status,
            new_status=order.status,
            updated_by=admin,
            remarks=f"Call status updated: {payload.call_status}",
        )
    )
    db.commit()
    log_activity(db, admin, "order_call_status", f"Order #{order.id}: {payload.call_status}")
    return _get_order_or_404(db, order_id)


# ---------- Delivery Review + Team Confirmation (Feature 2) ----------
# RBAC: gated on the same "orders" module's APPROVE action (section 24 --
# "only authorized team/admin users should be able to review delivery,
# set cost, approve/reject, confirm order"). No new permission module was
# needed since APPROVE already exists in the RBAC action set.

DELIVERY_BASE_FEE = 50.0
DELIVERY_RATE_PER_KM = 15.0


@router.put(
    "/orders/{order_id}/delivery-review",
    dependencies=[Depends(require_permission("orders", "APPROVE"))],
    response_model=OrderAdminOut,
)
def review_order_delivery(
    order_id: int,
    payload: OrderDeliveryReviewIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Saves the team's feasibility/cost review WITHOUT confirming the
    order yet (section 10-12) -- a separate, final step (POST .../confirm)
    actually enables payment. Lets the team mark NEEDS_REVIEW or jot notes
    over multiple passes before committing to a final decision."""
    order = _get_order_or_404(db, order_id)
    if order.team_confirmation_status == "CONFIRMED":
        raise HTTPException(status_code=400, detail="This order has already been confirmed.")
    if payload.delivery_feasibility not in DELIVERY_FEASIBILITY_STATUSES:
        raise HTTPException(status_code=400, detail=f"delivery_feasibility must be one of: {', '.join(DELIVERY_FEASIBILITY_STATUSES)}")
    if payload.cost_mode not in DELIVERY_COST_MODES:
        raise HTTPException(status_code=400, detail=f"cost_mode must be one of: {', '.join(DELIVERY_COST_MODES)}")

    order.delivery_feasibility = payload.delivery_feasibility
    order.delivery_distance_km = payload.distance_km
    order.delivery_cost_mode = payload.cost_mode
    order.delivery_review_notes = payload.notes.strip()

    if payload.cost_mode == "FREE":
        order.delivery_cost_calculated = 0
        order.shipping_fee = 0
    elif payload.cost_mode == "AUTO":
        if payload.distance_km is None:
            raise HTTPException(status_code=400, detail="distance_km is required for AUTO delivery cost")
        order.delivery_cost_calculated = round(DELIVERY_BASE_FEE + payload.distance_km * DELIVERY_RATE_PER_KM, 2)
        order.shipping_fee = payload.final_delivery_cost if payload.final_delivery_cost is not None else order.delivery_cost_calculated
    else:  # MANUAL
        order.delivery_cost_calculated = None
        if payload.final_delivery_cost is None:
            raise HTTPException(status_code=400, detail="final_delivery_cost is required for MANUAL delivery cost")
        order.shipping_fee = payload.final_delivery_cost

    if order.shipping_fee < 0:
        raise HTTPException(status_code=400, detail="Delivery cost cannot be negative")
    order.total_amount = order.subtotal + order.shipping_fee

    # remarks is shared with the customer (OrderOut.history) -- keep it to
    # the same numbers the customer already sees elsewhere in the order
    # (feasibility state, final delivery cost), never the team's free-text
    # internal notes (payload.notes, saved separately on the order but
    # deliberately not surfaced through history).
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            old_status=order.status,
            new_status=order.status,
            updated_by=admin,
            remarks=f"Delivery review updated: {order.delivery_feasibility}, delivery charge Rs.{order.shipping_fee}",
        )
    )
    db.commit()
    sync_order_to_accounting(order.id)
    log_activity(db, admin, "order_delivery_review", f"Order #{order.id}: {order.delivery_feasibility}, Rs.{order.shipping_fee}")
    return _get_order_or_404(db, order_id)


@router.post(
    "/orders/{order_id}/confirm",
    dependencies=[Depends(require_permission("orders", "APPROVE"))],
    response_model=OrderAdminOut,
)
def confirm_order_delivery(
    order_id: int,
    payload: OrderConfirmIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    order = _get_order_or_404(db, order_id)
    if order.team_confirmation_status == "CONFIRMED":
        raise HTTPException(status_code=400, detail="This order is already confirmed.")
    if order.delivery_feasibility != "APPROVED":
        raise HTTPException(status_code=400, detail="Delivery must be marked APPROVED before confirming the order.")
    if order.delivery_cost_mode != "FREE" and order.shipping_fee <= 0 and order.delivery_cost_calculated is None:
        raise HTTPException(status_code=400, detail="Set a delivery cost before confirming the order.")

    order.team_confirmation_status = "CONFIRMED"
    order.team_confirmed_by = admin
    order.team_confirmed_at = datetime.utcnow()
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            old_status=order.status,
            new_status=order.status,
            updated_by=admin,
            remarks=payload.remarks.strip() or "Order confirmed by team -- delivery approved, payment enabled",
        )
    )
    db.commit()
    sync_order_to_accounting(order.id)

    order = _get_order_or_404(db, order_id)
    log_activity(db, admin, "order_confirmed", f"Order #{order.id}")
    notify_delivery_confirmed(order)
    return order


@router.post(
    "/orders/{order_id}/reject-delivery",
    dependencies=[Depends(require_permission("orders", "APPROVE"))],
    response_model=OrderAdminOut,
)
def reject_order_delivery(
    order_id: int,
    payload: OrderRejectDeliveryIn,
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    order = _get_order_or_404(db, order_id)
    if order.team_confirmation_status == "CONFIRMED":
        raise HTTPException(status_code=400, detail="This order has already been confirmed and cannot be rejected here -- cancel it instead.")
    if payload.reason not in DELIVERY_REJECTION_REASONS:
        raise HTTPException(status_code=400, detail=f"reason must be one of: {', '.join(DELIVERY_REJECTION_REASONS)}")

    # DELIVERY_UNAVAILABLE is a dead end for this order -- the customer can
    # never complete it, so the stock reserved at checkout must go back to
    # inventory (same restoration logic as admin_cancel_order above), and
    # the order is marked Cancelled through the exact same path a normal
    # cancellation uses, so sync_order_to_accounting()'s existing
    # _sync_cancellation() voids the linked SalesOrder/Invoice automatically
    # -- no separate invoice-void logic needed here.
    for item in order.items:
        if item.plant_id:
            restore_stock(
                db,
                plant_id=item.plant_id,
                variant_id=item.variant_id,
                quantity=item.quantity,
                source_type="DELIVERY_REJECTED",
                source_id=order.id,
                reference=f"ORDER:{order.id}:SALE_REVERSAL:{item.variant_id or item.plant_id}",
                created_by=admin,
            )

    old_status = order.status
    order.team_confirmation_status = "DELIVERY_UNAVAILABLE"
    order.delivery_feasibility = "NOT_AVAILABLE"
    order.delivery_rejection_reason = payload.detail.strip() if payload.reason == "Other" and payload.detail.strip() else payload.reason
    order.status = "Cancelled"
    # remarks is shared with the customer (OrderOut.history) -- the actual
    # internal reason lives only in delivery_rejection_reason, which is
    # excluded from the customer-facing schema (section 16).
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            old_status=old_status,
            new_status="Cancelled",
            updated_by=admin,
            remarks="Delivery unavailable for this order -- order cancelled",
        )
    )
    db.commit()
    sync_order_to_accounting(order.id)

    order = _get_order_or_404(db, order_id)
    log_activity(db, admin, "order_delivery_rejected", f"Order #{order.id}: {order.delivery_rejection_reason}")
    notify_delivery_unavailable(order)
    return order


# ---------- Customers ----------

@router.get("/customers", dependencies=[Depends(require_permission("customers", "VIEW"))], response_model=list[CustomerAdminOut])
def list_customers(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    order_counts = dict(
        db.query(Order.customer_id, func.count(Order.id)).group_by(Order.customer_id).all()
    )
    customers = (
        db.query(Customer)
        .filter(Customer.id.in_(order_counts.keys()))
        .order_by(Customer.created_at.desc())
        .all()
        if order_counts
        else []
    )
    return [
        CustomerAdminOut(
            id=c.id,
            name=c.name,
            email=c.email,
            mobile=c.mobile,
            created_at=c.created_at,
            order_count=order_counts.get(c.id, 0),
        )
        for c in customers
    ]


@router.get("/customers/{item_id}", dependencies=[Depends(require_permission("customers", "VIEW"))], response_model=CustomerAdminDetailOut)
def get_customer(
    item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    customer = get_or_404(db, Customer, item_id)
    orders = (
        db.query(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.plant))
        .filter(Order.customer_id == item_id)
        .order_by(Order.created_at.desc())
        .all()
    )
    # Cancelled orders never generated real revenue -- excluding them here (not just
    # in the analytics endpoints) keeps this "total spent" consistent with the
    # VIP/segment thresholds that reuse the same spend figure.
    revenue_orders = [o for o in orders if o.status != "Cancelled"]
    total_spent = sum(o.total_amount for o in revenue_orders)
    last_order_at = revenue_orders[0].created_at if revenue_orders else None
    is_active = bool(last_order_at) and (datetime.utcnow() - last_order_at).days <= INACTIVE_DAYS
    return CustomerAdminDetailOut(
        id=customer.id,
        name=customer.name,
        email=customer.email,
        mobile=customer.mobile,
        created_at=customer.created_at,
        total_orders=len(orders),
        total_spent=total_spent,
        avg_order_value=round(total_spent / len(revenue_orders), 2) if revenue_orders else 0,
        last_order_date=last_order_at,
        status="active" if is_active else "inactive",
        orders=[CustomerOrderOut.model_validate(o) for o in orders],
    )


# ---------- Settings ----------

@router.get("/settings", dependencies=[Depends(require_permission("website", "VIEW"))])
def read_settings(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return get_settings(db)


@router.put("/settings", dependencies=[Depends(require_permission("website", "EDIT"))])
def update_settings(
    payload: SettingsIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    if "hero_images" in payload.values:
        lines = [l.strip() for l in (payload.values["hero_images"] or "").splitlines() if l.strip()]
        if not lines:
            raise HTTPException(status_code=400, detail="Add at least one slider image.")
        if len(lines) > 10:
            raise HTTPException(status_code=400, detail="At most 10 slider images are allowed.")
        for line in lines:
            if not (line.startswith("https://") or line.startswith("http://") or line.startswith("/")):
                raise HTTPException(status_code=400, detail=f"Slider image must be a web link (https://...): {line[:60]}")
        payload.values["hero_images"] = "\n".join(lines)
    if "hero_slide_seconds" in payload.values:
        try:
            secs = int(str(payload.values["hero_slide_seconds"]).strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Slide time must be a whole number of seconds.")
        if not 2 <= secs <= 30:
            raise HTTPException(status_code=400, detail="Slide time must be between 2 and 30 seconds.")
        payload.values["hero_slide_seconds"] = str(secs)
    for key, value in payload.values.items():
        setting = db.query(SiteSetting).filter(SiteSetting.key == key).first()
        if setting:
            setting.value = value
        else:
            db.add(SiteSetting(key=key, value=value))
    db.commit()
    return get_settings(db)
