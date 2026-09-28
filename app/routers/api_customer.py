import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.accounting.sync import sync_order_to_accounting
from app.order_alerts.hub import hub as order_alert_hub
from app.auth import hash_password, verify_password
from app.database import get_db
from app.deps import get_current_customer
from app.inventory import InsufficientStockError, deduct_stock, restore_stock
from app.models import (
    CANCELLABLE_STATUSES,
    Address,
    CartItem,
    Customer,
    CustomerActivityLog,
    Order,
    OrderItem,
    OrderStatusHistory,
    Plant,
    PlantReview,
    PlantVariant,
    WishlistItem,
)
from app.notifications import (
    notify_order_awaiting_confirmation,
    notify_order_cancelled,
    notify_order_status,
    notify_payment_received,
    send_email,
)
from app.payments import create_razorpay_order, verify_payment_signature
from app.schemas import (
    AddressIn,
    AddressOut,
    CartAddIn,
    CartItemOut,
    CartUpdateIn,
    CheckoutIn,
    CustomerLoginIn,
    CustomerOut,
    CustomerRegisterIn,
    ForgotPasswordIn,
    OrderCancelIn,
    OrderOut,
    OrderSummaryOut,
    PaymentFailedIn,
    RazorpayVerifyIn,
    ResetPasswordIn,
    ReviewEligibilityOut,
    ReviewIn,
    ReviewOut,
    WishlistAddIn,
    WishlistItemOut,
    WishlistStatusOut,
)

router = APIRouter(prefix="/api/customer")

MOBILE_PATTERN = re.compile(r"^[6-9]\d{9}$")
PINCODE_PATTERN = re.compile(r"^\d{6}$")
ADDRESS_TYPES = {"Home", "Other"}
PAYMENT_METHODS = {"COD", "Razorpay"}


def _resolve_variant(db: Session, plant: Plant, variant_id: Optional[int]) -> Optional[PlantVariant]:
    has_variants = db.query(PlantVariant.id).filter(PlantVariant.plant_id == plant.id).first() is not None
    if not has_variants:
        if variant_id is not None:
            raise HTTPException(status_code=400, detail=f"{plant.name} does not have tray options")
        return None
    if variant_id is None:
        raise HTTPException(status_code=400, detail=f"Please select a tray size for {plant.name}")
    variant = (
        db.query(PlantVariant)
        .filter(PlantVariant.id == variant_id, PlantVariant.plant_id == plant.id)
        .first()
    )
    if not variant:
        raise HTTPException(status_code=400, detail="Invalid tray size selected")
    return variant


def get_or_404_order(db: Session, order_id: int, customer_id: int) -> Order:
    order = (
        db.query(Order)
        .options(joinedload(Order.items), joinedload(Order.history), joinedload(Order.customer))
        .filter(Order.id == order_id, Order.customer_id == customer_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


# ---------- Auth ----------


@router.post("/register", response_model=CustomerOut, status_code=201)
def register(payload: CustomerRegisterIn, request: Request, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if db.query(Customer).filter(Customer.email == email).first():
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    customer = Customer(
        name=payload.name.strip(),
        email=email,
        mobile=payload.mobile.strip(),
        hashed_password=hash_password(payload.password),
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    request.session.pop("admin_username", None)
    request.session["customer_id"] = customer.id
    db.add(CustomerActivityLog(customer_id=customer.id, action="register"))
    db.commit()
    return customer


@router.post("/login", response_model=CustomerOut)
def login(payload: CustomerLoginIn, request: Request, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    customer = db.query(Customer).filter(Customer.email == email).first()
    if not customer or not verify_password(payload.password, customer.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    request.session.pop("admin_username", None)
    request.session["customer_id"] = customer.id
    return customer


@router.post("/logout")
def logout(request: Request):
    request.session.pop("customer_id", None)
    return {"ok": True}


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordIn, request: Request, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    customer = db.query(Customer).filter(Customer.email == email).first()
    if customer:
        token = secrets.token_urlsafe(32)
        customer.reset_token = token
        customer.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        db.commit()

        link = f"{request.base_url}reset-password?token={token}"
        print(f"[password-reset] {customer.email}: {link}")
        send_email(customer.email, "Reset your password", f"Click to reset your password: {link}")

    return {"ok": True}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordIn, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.reset_token == payload.token).first()
    if not customer or not customer.reset_token_expires or customer.reset_token_expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    customer.hashed_password = hash_password(payload.password)
    customer.reset_token = None
    customer.reset_token_expires = None
    db.commit()
    return {"ok": True}


@router.get("/me", response_model=CustomerOut)
def me(customer_id: int = Depends(get_current_customer), db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return customer


# ---------- Cart ----------


@router.get("/cart", response_model=list[CartItemOut])
def get_cart(customer_id: int = Depends(get_current_customer), db: Session = Depends(get_db)):
    return (
        db.query(CartItem)
        .options(joinedload(CartItem.plant))
        .filter(CartItem.customer_id == customer_id)
        .order_by(CartItem.created_at)
        .all()
    )


@router.post("/cart", response_model=CartItemOut, status_code=201)
def add_to_cart(
    payload: CartAddIn,
    customer_id: int = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    plant = db.query(Plant).filter(Plant.id == payload.plant_id, Plant.is_active.is_(True)).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")
    if payload.quantity < 1:
        raise HTTPException(status_code=400, detail="Quantity must be at least 1")
    variant = _resolve_variant(db, plant, payload.variant_id)
    variant_id = variant.id if variant else None

    item = (
        db.query(CartItem)
        .filter(
            CartItem.customer_id == customer_id,
            CartItem.plant_id == payload.plant_id,
            CartItem.variant_id == variant_id,
        )
        .first()
    )
    if item:
        item.quantity += payload.quantity
    else:
        item = CartItem(
            customer_id=customer_id,
            plant_id=payload.plant_id,
            variant_id=variant_id,
            quantity=payload.quantity,
        )
        db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/cart/{item_id}", response_model=CartItemOut)
def update_cart_item(
    item_id: int,
    payload: CartUpdateIn,
    customer_id: int = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    item = (
        db.query(CartItem)
        .filter(CartItem.id == item_id, CartItem.customer_id == customer_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")

    if payload.quantity <= 0:
        db.delete(item)
        db.commit()
        raise HTTPException(status_code=204, detail="Removed")

    item.quantity = payload.quantity
    db.commit()
    db.refresh(item)
    return item


@router.delete("/cart/{item_id}", status_code=204)
def remove_cart_item(
    item_id: int, customer_id: int = Depends(get_current_customer), db: Session = Depends(get_db)
):
    item = (
        db.query(CartItem)
        .filter(CartItem.id == item_id, CartItem.customer_id == customer_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")
    db.delete(item)
    db.commit()


@router.delete("/cart", status_code=204)
def clear_cart(customer_id: int = Depends(get_current_customer), db: Session = Depends(get_db)):
    db.query(CartItem).filter(CartItem.customer_id == customer_id).delete()
    db.commit()


# ---------- Wishlist ----------


@router.get("/wishlist", response_model=list[WishlistItemOut])
def get_wishlist(customer_id: int = Depends(get_current_customer), db: Session = Depends(get_db)):
    return (
        db.query(WishlistItem)
        .options(joinedload(WishlistItem.plant))
        .filter(WishlistItem.customer_id == customer_id)
        .order_by(WishlistItem.created_at.desc())
        .all()
    )


@router.get("/wishlist/status/{plant_id}", response_model=WishlistStatusOut)
def get_wishlist_status(
    plant_id: int, customer_id: int = Depends(get_current_customer), db: Session = Depends(get_db)
):
    exists = (
        db.query(WishlistItem)
        .filter(WishlistItem.customer_id == customer_id, WishlistItem.plant_id == plant_id)
        .first()
        is not None
    )
    return WishlistStatusOut(in_wishlist=exists)


@router.post("/wishlist", response_model=WishlistItemOut, status_code=201)
def add_to_wishlist(
    payload: WishlistAddIn,
    customer_id: int = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    plant = db.query(Plant).filter(Plant.id == payload.plant_id, Plant.is_active.is_(True)).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    item = (
        db.query(WishlistItem)
        .options(joinedload(WishlistItem.plant))
        .filter(WishlistItem.customer_id == customer_id, WishlistItem.plant_id == payload.plant_id)
        .first()
    )
    if item:
        return item

    item = WishlistItem(customer_id=customer_id, plant_id=payload.plant_id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/wishlist/{plant_id}", status_code=204)
def remove_from_wishlist(
    plant_id: int, customer_id: int = Depends(get_current_customer), db: Session = Depends(get_db)
):
    item = (
        db.query(WishlistItem)
        .filter(WishlistItem.customer_id == customer_id, WishlistItem.plant_id == plant_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found in wishlist")
    db.delete(item)
    db.commit()


# ---------- Addresses ----------


def _validate_address_payload(payload: AddressIn) -> None:
    if not MOBILE_PATTERN.match(payload.mobile.strip()):
        raise HTTPException(status_code=400, detail="Please enter a valid 10-digit mobile number")
    if not PINCODE_PATTERN.match(payload.pincode.strip()):
        raise HTTPException(status_code=400, detail="Please enter a valid 6-digit pincode")
    if payload.address_type not in ADDRESS_TYPES:
        raise HTTPException(status_code=400, detail="Address type must be Home or Other")
    if not payload.full_name.strip() or not payload.line1.strip() or not payload.city.strip() or not payload.state.strip():
        raise HTTPException(status_code=400, detail="Please fill in all required address fields")


def get_or_404_address(db: Session, address_id: int, customer_id: int) -> Address:
    address = (
        db.query(Address)
        .filter(Address.id == address_id, Address.customer_id == customer_id)
        .first()
    )
    if not address:
        raise HTTPException(status_code=404, detail="Address not found")
    return address


@router.get("/addresses", response_model=list[AddressOut])
def list_addresses(customer_id: int = Depends(get_current_customer), db: Session = Depends(get_db)):
    return (
        db.query(Address)
        .filter(Address.customer_id == customer_id)
        .order_by(Address.is_default.desc(), Address.created_at.desc())
        .all()
    )


@router.post("/addresses", response_model=AddressOut, status_code=201)
def create_address(
    payload: AddressIn,
    customer_id: int = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    _validate_address_payload(payload)

    has_existing = db.query(Address).filter(Address.customer_id == customer_id).first() is not None
    make_default = payload.is_default or not has_existing

    if make_default:
        db.query(Address).filter(Address.customer_id == customer_id).update({"is_default": False})

    address = Address(
        customer_id=customer_id,
        full_name=payload.full_name.strip(),
        mobile=payload.mobile.strip(),
        line1=payload.line1.strip(),
        line2=payload.line2.strip(),
        city=payload.city.strip(),
        state=payload.state.strip(),
        pincode=payload.pincode.strip(),
        address_type=payload.address_type,
        is_default=make_default,
    )
    db.add(address)
    db.commit()
    db.refresh(address)
    return address


@router.put("/addresses/{address_id}", response_model=AddressOut)
def update_address(
    address_id: int,
    payload: AddressIn,
    customer_id: int = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    _validate_address_payload(payload)
    address = get_or_404_address(db, address_id, customer_id)

    if payload.is_default and not address.is_default:
        db.query(Address).filter(Address.customer_id == customer_id).update({"is_default": False})

    address.full_name = payload.full_name.strip()
    address.mobile = payload.mobile.strip()
    address.line1 = payload.line1.strip()
    address.line2 = payload.line2.strip()
    address.city = payload.city.strip()
    address.state = payload.state.strip()
    address.pincode = payload.pincode.strip()
    address.address_type = payload.address_type
    if payload.is_default:
        address.is_default = True
    db.commit()
    db.refresh(address)
    return address


@router.put("/addresses/{address_id}/default", response_model=AddressOut)
def set_default_address(
    address_id: int,
    customer_id: int = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    address = get_or_404_address(db, address_id, customer_id)
    db.query(Address).filter(Address.customer_id == customer_id).update({"is_default": False})
    address.is_default = True
    db.commit()
    db.refresh(address)
    return address


@router.delete("/addresses/{address_id}", status_code=204)
def delete_address(
    address_id: int,
    customer_id: int = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    address = get_or_404_address(db, address_id, customer_id)
    was_default = address.is_default
    db.delete(address)
    db.commit()

    if was_default:
        next_address = (
            db.query(Address)
            .filter(Address.customer_id == customer_id)
            .order_by(Address.created_at.desc())
            .first()
        )
        if next_address:
            next_address.is_default = True
            db.commit()


# ---------- Checkout & Orders ----------


@router.post("/checkout", response_model=OrderOut, status_code=201)
def checkout(
    payload: CheckoutIn,
    customer_id: int = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    if payload.payment_method not in PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail="Invalid payment method")

    if payload.idempotency_key:
        # A network retry (client never saw the first response, e.g. after
        # `openRazorpayCheckout`'s script tag fails to load) must not create
        # a second order/charge -- return the order that was already placed.
        existing = (
            db.query(Order)
            .filter(Order.customer_id == customer_id, Order.idempotency_key == payload.idempotency_key)
            .first()
        )
        if existing:
            return get_or_404_order(db, existing.id, customer_id)

    buy_now = payload.buy_now_plant_id is not None
    clear_cart = not buy_now

    if buy_now:
        if payload.buy_now_quantity < 1:
            raise HTTPException(status_code=400, detail="Quantity must be at least 1")
        plant = (
            db.query(Plant)
            .filter(Plant.id == payload.buy_now_plant_id, Plant.is_active.is_(True))
            .first()
        )
        if not plant:
            raise HTTPException(status_code=404, detail="Plant not found")
        variant = _resolve_variant(db, plant, payload.buy_now_variant_id)
        available = variant.stock_quantity if variant else plant.stock_quantity
        if available < payload.buy_now_quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {plant.name}")
        order_lines = [(plant, variant, payload.buy_now_quantity)]
    else:
        cart_items = (
            db.query(CartItem)
            .options(joinedload(CartItem.plant), joinedload(CartItem.variant))
            .filter(CartItem.customer_id == customer_id)
            .all()
        )
        if not cart_items:
            raise HTTPException(status_code=400, detail="Your cart is empty")

        for cart_item in cart_items:
            plant = cart_item.plant
            if not plant or not plant.is_active:
                raise HTTPException(status_code=400, detail=f"{plant.name if plant else 'A plant'} is no longer available")
            if cart_item.variant_id and not cart_item.variant:
                raise HTTPException(status_code=400, detail=f"A tray option for {plant.name} is no longer available")
            available = cart_item.variant.stock_quantity if cart_item.variant else plant.stock_quantity
            if available < cart_item.quantity:
                raise HTTPException(status_code=400, detail=f"Insufficient stock for {plant.name}")

        order_lines = [(cart_item.plant, cart_item.variant, cart_item.quantity) for cart_item in cart_items]

    subtotal = sum(
        (variant.price if variant else plant.effective_price) * quantity
        for plant, variant, quantity in order_lines
    )

    order = Order(
        customer_id=customer_id,
        status="Pending",
        payment_status="Pending",
        payment_method=payload.payment_method,
        subtotal=subtotal,
        shipping_fee=0,
        total_amount=subtotal,
        delivery_name=payload.delivery_name.strip(),
        delivery_mobile=payload.delivery_mobile.strip(),
        delivery_line1=payload.delivery_line1.strip(),
        delivery_line2=payload.delivery_line2.strip(),
        delivery_city=payload.delivery_city.strip(),
        delivery_state=payload.delivery_state.strip(),
        delivery_pincode=payload.delivery_pincode.strip(),
        idempotency_key=payload.idempotency_key,
    )
    db.add(order)
    db.flush()

    for plant, variant, quantity in order_lines:
        unit_price = variant.price if variant else plant.effective_price
        db.add(
            OrderItem(
                order_id=order.id,
                plant_id=plant.id,
                plant_name=plant.name,
                plant_image_url=plant.image_url,
                variant_id=variant.id if variant else None,
                tray_size=variant.tray_size if variant else None,
                unit_price=unit_price,
                quantity=quantity,
                line_total=unit_price * quantity,
            )
        )
        try:
            deduct_stock(
                db,
                plant_id=plant.id,
                variant_id=variant.id if variant else None,
                quantity=quantity,
                source_type="ONLINE_ORDER",
                source_id=order.id,
                reference=f"ORDER:{order.id}:SALE:{variant.id if variant else plant.id}",
                created_by="customer",
            )
        except InsufficientStockError:
            # Lost a genuine race against another checkout for the same
            # item between the availability check above and this atomic
            # deduction -- nothing has been committed yet, so raising here
            # rolls the whole order (and any earlier lines' deductions in
            # this same loop) back together when the session closes.
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {plant.name}")

    # Feature 2 (delivery feasibility + team confirmation): the Razorpay
    # order is deliberately NOT created here anymore, for either payment
    # method -- no payment gateway is contacted and no payment can be made
    # until the nursery team has reviewed delivery feasibility/cost and
    # explicitly confirmed the order (see POST /orders/{id}/create-payment
    # and the team_confirmation_status guard in verify_payment() below).
    # team_confirmation_status defaults to "PENDING" on the Order model.

    db.add(
        OrderStatusHistory(
            order_id=order.id,
            old_status=None,
            new_status="Pending",
            updated_by="customer",
            remarks="Order request submitted -- awaiting team delivery confirmation",
        )
    )
    if clear_cart:
        db.query(CartItem).filter(CartItem.customer_id == customer_id).delete()
    db.commit()
    sync_order_to_accounting(order.id)

    order = get_or_404_order(db, order.id, customer_id)
    notify_order_awaiting_confirmation(order)
    # New Order Alert (real-time admin dashboard): fires exactly once per
    # genuinely new order -- the idempotency_key short-circuit above
    # returns early for a retried submit before this line is ever reached.
    order_alert_hub.emit_new_order(order)
    return order


@router.post("/orders/{order_id}/create-payment", response_model=OrderOut)
def create_payment(
    order_id: int,
    customer_id: int = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """Feature 2: the Razorpay order is only ever created here, once the
    team has confirmed the order -- never at checkout time. This is the
    single place a payment gateway call can happen for a normal order, and
    it's backend-gated (section 23), not just a hidden/disabled button."""
    order = get_or_404_order(db, order_id, customer_id)

    if order.payment_method != "Razorpay":
        raise HTTPException(status_code=400, detail="This order does not use online payment")
    if order.team_confirmation_status != "CONFIRMED":
        raise HTTPException(status_code=403, detail="This order is still awaiting team delivery confirmation.")
    if order.payment_status == "Paid":
        return order  # already paid; idempotent for double-submits
    if order.razorpay_order_id:
        return order  # a Razorpay order already exists for this order -- reuse it

    try:
        razorpay_order = create_razorpay_order(order.total_amount, receipt=f"order_{order.id}")
    except HTTPException:
        db.rollback()
        raise
    order.razorpay_order_id = razorpay_order["id"]
    db.commit()

    return get_or_404_order(db, order_id, customer_id)


@router.post("/orders/{order_id}/verify-payment", response_model=OrderOut)
def verify_payment(
    order_id: int,
    payload: RazorpayVerifyIn,
    customer_id: int = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    order = get_or_404_order(db, order_id, customer_id)

    if order.payment_method != "Razorpay":
        raise HTTPException(status_code=400, detail="This order does not use online payment")

    if order.payment_status == "Paid":
        return order  # already verified; idempotent for double-submits

    # Feature 2's critical backend enforcement (section 23): even if a
    # client bypasses the UI and calls this directly, payment cannot be
    # verified/accepted for an order the team hasn't confirmed.
    if order.team_confirmation_status != "CONFIRMED":
        raise HTTPException(status_code=403, detail="This order is still awaiting team delivery confirmation.")

    if not order.razorpay_order_id or order.razorpay_order_id != payload.razorpay_order_id:
        raise HTTPException(status_code=400, detail="Payment does not match this order")

    verified = verify_payment_signature(
        payload.razorpay_order_id, payload.razorpay_payment_id, payload.razorpay_signature
    )
    if not verified:
        order.payment_status = "Failed"
        db.commit()
        raise HTTPException(status_code=400, detail="Payment verification failed")

    old_status = order.status
    order.payment_status = "Paid"
    order.razorpay_payment_id = payload.razorpay_payment_id
    order.razorpay_signature = payload.razorpay_signature
    if order.status == "Pending":
        order.status = "Confirmed"
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            old_status=old_status,
            new_status=order.status,
            updated_by="system",
            remarks="Payment verified via Razorpay",
        )
    )
    db.commit()
    sync_order_to_accounting(order.id)

    order = get_or_404_order(db, order_id, customer_id)
    notify_order_status(order, old_status, order.status)
    notify_payment_received(order)
    return order


@router.post("/orders/{order_id}/payment-failed", response_model=OrderOut)
def mark_payment_failed(
    order_id: int,
    payload: PaymentFailedIn,
    customer_id: int = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    order = get_or_404_order(db, order_id, customer_id)
    if order.payment_method == "Razorpay" and order.payment_status != "Paid":
        order.payment_status = "Failed"
        db.commit()
        sync_order_to_accounting(order.id)
        order = get_or_404_order(db, order_id, customer_id)
        print(f"[payment] Order #{order.id} payment not completed: {payload.reason or 'unspecified'}")
    return order


@router.get("/orders", response_model=list[OrderSummaryOut])
def list_orders(customer_id: int = Depends(get_current_customer), db: Session = Depends(get_db)):
    return (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(Order.customer_id == customer_id)
        .order_by(Order.created_at.desc())
        .all()
    )


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int, customer_id: int = Depends(get_current_customer), db: Session = Depends(get_db)
):
    return get_or_404_order(db, order_id, customer_id)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: int,
    payload: OrderCancelIn,
    customer_id: int = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    order = get_or_404_order(db, order_id, customer_id)
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
                created_by="customer",
            )

    old_status = order.status
    order.status = "Cancelled"
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            old_status=old_status,
            new_status="Cancelled",
            updated_by="customer",
            remarks=payload.remarks or "Cancelled by customer",
        )
    )
    db.commit()
    sync_order_to_accounting(order.id)

    order = get_or_404_order(db, order_id, customer_id)
    notify_order_cancelled(db, order, old_status, cancelled_by="customer", reason=payload.remarks)
    return order


# ---------- Reviews ----------
# A review is only allowed once a Delivered order containing that exact
# plant exists for this customer -- re-derived from the database on every
# request below, never taken on trust from the client. See PlantReview's
# docstring in models.py for the full rationale.


def _qualifying_delivered_order(db: Session, customer_id: int, plant_id: int) -> Optional[Order]:
    return (
        db.query(Order)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .filter(Order.customer_id == customer_id, Order.status == "Delivered", OrderItem.plant_id == plant_id)
        .order_by(Order.id.desc())
        .first()
    )


@router.get("/plants/{plant_id}/review-eligibility", response_model=ReviewEligibilityOut)
def review_eligibility(plant_id: int, customer_id: int = Depends(get_current_customer), db: Session = Depends(get_db)):
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    existing = (
        db.query(PlantReview)
        .filter(PlantReview.plant_id == plant_id, PlantReview.customer_id == customer_id)
        .first()
    )
    if existing:
        return ReviewEligibilityOut(eligible=False, reason="already_reviewed", existing_review=existing)

    if _qualifying_delivered_order(db, customer_id, plant_id):
        return ReviewEligibilityOut(eligible=True, reason="eligible")

    ever_purchased = (
        db.query(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.customer_id == customer_id, OrderItem.plant_id == plant_id)
        .first()
    )
    reason = "not_delivered" if ever_purchased else "not_purchased"
    return ReviewEligibilityOut(eligible=False, reason=reason)


@router.post("/reviews", response_model=ReviewOut, status_code=201)
def create_review(payload: ReviewIn, customer_id: int = Depends(get_current_customer), db: Session = Depends(get_db)):
    plant = db.query(Plant).filter(Plant.id == payload.plant_id).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    if not (1 <= payload.rating <= 5):
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    comment = (payload.comment or "").strip()
    if len(comment) > 2000:
        raise HTTPException(status_code=400, detail="Comment is too long (max 2000 characters)")

    existing = (
        db.query(PlantReview)
        .filter(PlantReview.plant_id == plant.id, PlantReview.customer_id == customer_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="You have already reviewed this plant")

    qualifying_order = _qualifying_delivered_order(db, customer_id, plant.id)
    if not qualifying_order:
        raise HTTPException(status_code=403, detail="You can only review plants from delivered orders")

    review = PlantReview(
        plant_id=plant.id,
        customer_id=customer_id,
        order_id=qualifying_order.id,
        rating=payload.rating,
        comment=comment,
        status="PENDING",
    )
    db.add(review)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="You have already reviewed this plant")
    db.refresh(review)
    return review


@router.get("/reviews/my", response_model=list[ReviewOut])
def my_reviews(customer_id: int = Depends(get_current_customer), db: Session = Depends(get_db)):
    return (
        db.query(PlantReview)
        .filter(PlantReview.customer_id == customer_id)
        .order_by(PlantReview.created_at.desc())
        .all()
    )
