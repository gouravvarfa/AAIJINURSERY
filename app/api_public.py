import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.audit import LOGIN_LOCKED_OUT, record_admin_audit
from app.auth import verify_password
from app.database import get_db
from app.deps import get_current_admin
from app.permissions import get_permissions_map
from app.models import (
    FAQ,
    AdminSession,
    AdminUser,
    BlogPost,
    Category,
    Customer,
    CustomerActivityLog,
    GalleryImage,
    INQUIRY_STATUSES,
    Inquiry,
    InquiryStatusHistory,
    LoginAttempt,
    Order,
    OrderItem,
    Plant,
    PlantReview,
    PricingPlan,
    Service,
    Testimonial,
)
from app.routers.api_admin import log_activity
from app.schemas import (
    BlogPostOut,
    CategoryOut,
    EnquiryCreateIn,
    FAQOut,
    GalleryImageOut,
    InquiryIn,
    InquiryOut,
    PlantOut,
    PlantReviewsOut,
    PricingPlanOut,
    ServiceOut,
    TestimonialOut,
    UnifiedLoginIn,
)
from app.settings_helper import get_settings

router = APIRouter(prefix="/api")

# Admin login lockout (Developer Dashboard RBAC). Not yet configurable via
# SiteSetting -- deferred to a later polish pass, same reuse pattern as
# system_health_retention_days.
MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@router.get("/settings")
def read_settings(db: Session = Depends(get_db)):
    return get_settings(db)


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return db.query(Category).order_by(Category.display_order).all()


PLANT_SORT_OPTIONS = {
    "price_asc": Plant.price.asc(),
    "price_desc": Plant.price.desc(),
    "name": Plant.name.asc(),
    "newest": Plant.created_at.desc(),
}


@router.get("/plants", response_model=list[PlantOut])
def list_plants(
    response: Response,
    search: Optional[str] = None,
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    in_stock: Optional[bool] = None,
    featured: Optional[bool] = None,
    sort_by: Optional[str] = None,
    page: Optional[int] = None,
    limit: Optional[int] = None,
    db: Session = Depends(get_db),
):
    query = (
        db.query(Plant)
        .options(joinedload(Plant.category), selectinload(Plant.variants), selectinload(Plant.reviews))
        .filter(Plant.is_active.is_(True))
    )

    if category:
        slugs = [slug.strip() for slug in category.split(",") if slug.strip()]
        if slugs:
            query = query.join(Category).filter(Category.slug.in_(slugs))

    if search:
        like = f"%{search.strip()}%"
        query = query.filter(or_(Plant.name.ilike(like), Plant.description.ilike(like)))

    if min_price is not None:
        query = query.filter(Plant.price >= min_price)
    if max_price is not None:
        query = query.filter(Plant.price <= max_price)

    if in_stock is not None:
        query = query.filter(Plant.stock_quantity > 0 if in_stock else Plant.stock_quantity <= 0)

    if featured:
        query = query.filter(Plant.is_featured.is_(True))

    query = query.order_by(PLANT_SORT_OPTIONS.get(sort_by, Plant.id.asc()))

    total = query.count()

    if page is None and limit is None:
        items = query.all()
        page = 1
        limit = total or 1
    else:
        page = max(page or 1, 1)
        limit = min(max(limit or 12, 1), 100)
        items = query.offset((page - 1) * limit).limit(limit).all()

    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page)
    response.headers["X-Total-Pages"] = str(max(1, -(-total // limit)))

    return items


@router.get("/plants/{slug}", response_model=PlantOut)
def get_plant(slug: str, db: Session = Depends(get_db)):
    plant = (
        db.query(Plant)
        .options(joinedload(Plant.category), selectinload(Plant.variants), selectinload(Plant.reviews))
        .filter(Plant.slug == slug)
        .first()
    )
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")
    return plant


@router.get("/plants/{slug}/reviews", response_model=PlantReviewsOut)
def get_plant_reviews(slug: str, db: Session = Depends(get_db)):
    plant = db.query(Plant).filter(Plant.slug == slug).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    reviews = (
        db.query(PlantReview)
        .options(joinedload(PlantReview.customer))
        .filter(PlantReview.plant_id == plant.id, PlantReview.status == "PUBLISHED")
        .order_by(PlantReview.created_at.desc())
        .all()
    )
    distribution = {n: 0 for n in range(5, 0, -1)}
    for r in reviews:
        distribution[r.rating] = distribution.get(r.rating, 0) + 1
    average = round(sum(r.rating for r in reviews) / len(reviews), 2) if reviews else None

    return PlantReviewsOut(
        average_rating=average,
        review_count=len(reviews),
        rating_distribution=distribution,
        reviews=reviews,
    )


@router.get("/plants/{slug}/related", response_model=list[PlantOut])
def get_related_plants(slug: str, db: Session = Depends(get_db)):
    plant = db.query(Plant).filter(Plant.slug == slug).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")
    return (
        db.query(Plant)
        .filter(Plant.category_id == plant.category_id, Plant.id != plant.id)
        .limit(4)
        .all()
    )


@router.get("/plants/{slug}/recommendations", response_model=list[PlantOut])
def get_plant_recommendations(slug: str, db: Session = Depends(get_db)):
    """"Customers who bought this also bought" -- real co-purchase analysis
    over order history, falling back to same-category plants when there
    isn't enough co-purchase data yet (e.g. a brand-new plant). Deliberately
    separate from the existing /related endpoint (same-category only) so
    that endpoint's existing behavior is untouched."""
    plant = db.query(Plant).filter(Plant.slug == slug).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    orders_with_plant = db.query(OrderItem.order_id).filter(OrderItem.plant_id == plant.id).subquery()
    co_purchased = (
        db.query(OrderItem.plant_id, func.count(OrderItem.id).label("co_count"))
        .filter(OrderItem.order_id.in_(orders_with_plant), OrderItem.plant_id != plant.id)
        .group_by(OrderItem.plant_id)
        .order_by(func.count(OrderItem.id).desc())
        .limit(4)
        .all()
    )
    plant_ids = [pid for pid, _ in co_purchased]

    if len(plant_ids) < 4:
        exclude_ids = plant_ids + [plant.id]
        fallback = (
            db.query(Plant.id)
            .filter(
                Plant.category_id == plant.category_id,
                Plant.id.notin_(exclude_ids),
                Plant.is_active == True,  # noqa: E712
            )
            .limit(4 - len(plant_ids))
            .all()
        )
        plant_ids += [pid for (pid,) in fallback]

    if not plant_ids:
        return []

    plants = db.query(Plant).filter(Plant.id.in_(plant_ids), Plant.is_active == True).all()  # noqa: E712
    order_map = {pid: i for i, pid in enumerate(plant_ids)}
    plants.sort(key=lambda p: order_map.get(p.id, 999))
    return plants


@router.get("/services", response_model=list[ServiceOut])
def list_services(db: Session = Depends(get_db)):
    return (
        db.query(Service).filter(Service.is_active.is_(True)).order_by(Service.display_order).all()
    )


@router.get("/pricing-plans", response_model=list[PricingPlanOut])
def list_pricing_plans(db: Session = Depends(get_db)):
    return db.query(PricingPlan).order_by(PricingPlan.display_order).all()


@router.get("/faqs", response_model=list[FAQOut])
def list_faqs(db: Session = Depends(get_db)):
    return db.query(FAQ).filter(FAQ.is_active.is_(True)).order_by(FAQ.display_order).all()


@router.get("/testimonials", response_model=list[TestimonialOut])
def list_testimonials(db: Session = Depends(get_db)):
    return (
        db.query(Testimonial)
        .filter(Testimonial.is_approved.is_(True))
        .order_by(Testimonial.created_at.desc())
        .all()
    )


@router.get("/gallery", response_model=list[GalleryImageOut])
def list_gallery(db: Session = Depends(get_db)):
    return db.query(GalleryImage).order_by(GalleryImage.display_order).all()


@router.get("/blog", response_model=list[BlogPostOut])
def list_blog_posts(db: Session = Depends(get_db)):
    return (
        db.query(BlogPost)
        .filter(BlogPost.is_published.is_(True))
        .order_by(BlogPost.published_at.desc())
        .all()
    )


@router.get("/blog/{slug}", response_model=BlogPostOut)
def get_blog_post(slug: str, db: Session = Depends(get_db)):
    post = db.query(BlogPost).filter(BlogPost.slug == slug).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.post("/inquiries", response_model=InquiryOut, status_code=201)
def create_inquiry(payload: InquiryIn, db: Session = Depends(get_db)):
    plant_id = payload.plant_id
    if plant_id is not None and not db.query(Plant).filter(Plant.id == plant_id).first():
        plant_id = None

    inquiry = Inquiry(
        name=payload.name.strip(),
        mobile=payload.mobile.strip(),
        requirement=payload.requirement.strip(),
        plant_id=plant_id,
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)
    return inquiry


@router.post("/enquiries", response_model=InquiryOut, status_code=201)
def create_enquiry(payload: EnquiryCreateIn, request: Request, db: Session = Depends(get_db)):
    """Feature 1's dedicated "Enquire Now" flow, for a Plant explicitly
    marked ENQUIRY_AVAILABLE by the nursery -- separate endpoint/schema
    from the generic /inquiries contact form (section 21: never let this
    trigger delivery costing, checkout, or payment; it only ever creates an
    Inquiry row for the team to act on)."""
    plant = db.query(Plant).filter(Plant.id == payload.plant_id).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Product not found")

    # Optional: attach the logged-in customer if there is one, without
    # requiring login -- a guest can still enquire (matches the existing
    # generic /inquiries endpoint's openness).
    customer_id = request.session.get("customer_id")

    enquiry_number = f"ENQ-{datetime.utcnow():%Y%m%d}-{secrets.token_hex(2)}"
    inquiry = Inquiry(
        name=payload.name.strip(),
        mobile=payload.mobile.strip(),
        email=payload.email.strip(),
        requirement=payload.message.strip(),
        quantity=payload.quantity,
        plant_id=plant.id,
        plant_name_snapshot=plant.name,
        customer_id=customer_id,
        enquiry_number=enquiry_number,
        status="new",
    )
    db.add(inquiry)
    db.flush()
    db.add(InquiryStatusHistory(inquiry_id=inquiry.id, old_status="", new_status="new", note="Enquiry submitted by customer"))
    db.commit()
    db.refresh(inquiry)
    return inquiry


# ---------- Unified auth ----------


@router.post("/auth/login")
def unified_login(payload: UnifiedLoginIn, request: Request, db: Session = Depends(get_db)):
    identifier = payload.identifier.strip()
    ip_address = _client_ip(request)
    user_agent = request.headers.get("user-agent", "")[:300]

    def _record_attempt(success: bool, reason: str = ""):
        db.add(
            LoginAttempt(
                identifier=identifier, ip_address=ip_address, user_agent=user_agent, success=success, reason=reason
            )
        )

    admin = db.query(AdminUser).filter(AdminUser.username == identifier).first()
    if admin:
        if admin.locked_until and admin.locked_until > datetime.utcnow():
            _record_attempt(False, "locked")
            db.commit()
            raise HTTPException(
                status_code=403, detail="Account temporarily locked due to repeated failed logins. Try again later."
            )
        if not admin.is_active:
            _record_attempt(False, "inactive")
            db.commit()
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if not verify_password(payload.password, admin.hashed_password):
            admin.failed_login_attempts += 1
            reason = "bad_password"
            if admin.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
                admin.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
                reason = "locked"
                record_admin_audit(
                    admin.username, LOGIN_LOCKED_OUT, {"failed_attempts": admin.failed_login_attempts}
                )
            _record_attempt(False, reason)
            db.commit()
            raise HTTPException(status_code=401, detail="Invalid email or password")

        admin.failed_login_attempts = 0
        admin.locked_until = None
        request.session["admin_username"] = admin.username
        request.session.pop("customer_id", None)

        session_token = secrets.token_hex(32)
        db.add(
            AdminSession(
                session_token=session_token,
                admin_user_id=admin.id,
                username=admin.username,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        request.session["admin_session_id"] = session_token

        _record_attempt(True)
        log_activity(db, admin.username, "login")
        db.commit()
        return {"type": admin.role, "username": admin.username, "permissions": get_permissions_map(db, admin)}

    customer_candidates = (
        db.query(Customer)
        .filter(or_(Customer.email == identifier.lower(), Customer.name == identifier))
        .all()
    )
    customer = next(
        (c for c in customer_candidates if verify_password(payload.password, c.hashed_password)), None
    )
    if customer:
        request.session["customer_id"] = customer.id
        request.session.pop("admin_username", None)
        _record_attempt(True)
        db.add(CustomerActivityLog(customer_id=customer.id, action="login"))
        db.commit()
        return {"type": "customer", "id": customer.id, "name": customer.name, "email": customer.email}

    _record_attempt(False, "invalid_credentials")
    db.commit()
    raise HTTPException(status_code=401, detail="Invalid email or password")


@router.post("/auth/logout")
def unified_logout(request: Request, db: Session = Depends(get_db)):
    admin_username = request.session.get("admin_username")
    session_token = request.session.get("admin_session_id")
    if admin_username and session_token:
        admin_session = db.query(AdminSession).filter(AdminSession.session_token == session_token).first()
        if admin_session and admin_session.revoked_at is None:
            admin_session.revoked_at = datetime.utcnow()
            admin_session.revoked_by = admin_username
            admin_session.revoke_reason = "logout"
            db.commit()

    request.session.pop("admin_username", None)
    request.session.pop("customer_id", None)
    request.session.pop("admin_session_id", None)
    return {"ok": True}


@router.get("/auth/me")
def unified_me(request: Request, db: Session = Depends(get_db)):
    try:
        admin_username = get_current_admin(request, db)
    except HTTPException:
        admin_username = None

    if admin_username:
        admin = db.query(AdminUser).filter(AdminUser.username == admin_username).first()
        if admin:
            return {"type": admin.role, "username": admin.username, "permissions": get_permissions_map(db, admin)}

    customer_id = request.session.get("customer_id")
    if customer_id:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if customer:
            return {"type": "customer", "id": customer.id, "name": customer.name, "email": customer.email}

    raise HTTPException(status_code=401, detail="Not authenticated")
