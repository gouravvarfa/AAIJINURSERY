import os
import smtplib
import socket
import urllib.parse
import urllib.request
from datetime import datetime
from email.mime.text import MIMEText

from app.communications.service import queue_event as queue_whatsapp_event
from app.monitoring.recorder import record_error
from app.settings_helper import get_settings

# Order-status -> centralized WhatsApp event name. Orders NEVER pick a
# template name themselves (that's resolved centrally by
# WhatsAppEventTemplateMap, see app/communications/service.py); this dict
# only decides which EVENT a status transition represents. Any status not
# listed here (Processing, Packed, Refund Initiated/Completed, Returned)
# falls back to a generic `ORDER_<STATUS>` event -- still centrally
# resolved, just without a specific named event of its own yet.
STATUS_TO_EVENT = {
    "Confirmed": "ORDER_ACCEPTED",
    "Shipped": "ORDER_DISPATCHED",
    "Out For Delivery": "OUT_FOR_DELIVERY",
    "Delivered": "ORDER_DELIVERED",
    "Cancelled": "ORDER_CANCELLED",
}


def _business_name() -> str:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return get_settings(db).get("business_name", "Aaiji Nursery")
    finally:
        db.close()


def _order_contact(order):
    """(mobile, customer_name) for whichever contact info the order has --
    same fallback the existing email/CallMeBot code already uses."""
    # What the customer typed on THIS order's checkout wins over the account
    # profile: that is the person and number the team is meant to reach for
    # this order (a different name/number than the account is normal).
    mobile = order.delivery_mobile or (order.customer.mobile if order.customer else "")
    name = order.delivery_name or (order.customer.name if order.customer else "") or "Customer"
    return mobile, name


def _queue_order_event(order, event_type: str, template_params: list) -> None:
    """The ONE place Orders talks to WhatsApp -- everything routes through
    the centralized WhatsAppService (queue_event), which resolves the
    template centrally and never lets Orders guess/hardcode one. A queueing
    failure here can never break order processing: queue_event() already
    swallows every exception itself."""
    mobile, name = _order_contact(order)
    if not mobile:
        return
    queue_whatsapp_event(
        event_type=event_type, mobile=mobile, customer_name=name,
        template_params=template_params,
        source_module="orders", source_id=order.id, customer_id=order.customer_id,
    )


class _IPv4SMTP(smtplib.SMTP):
    """Some hosts (e.g. Render) advertise IPv6 but can't actually route it,
    causing 'Network is unreachable' against Gmail's dual-stack SMTP. Force
    the socket to resolve via IPv4 while keeping the hostname for TLS SNI."""

    def _get_socket(self, host, port, timeout):
        ipv4_host = socket.gethostbyname(host)
        return socket.create_connection((ipv4_host, port), timeout, self.source_address)


def send_email(to_email: str, subject: str, body: str) -> None:
    if not to_email:
        return

    host = os.environ.get("SMTP_HOST", "")
    if not host:
        print(f"[email] SMTP not configured, skipping send to {to_email}: {subject}")
        return

    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = os.environ.get("SMTP_FROM", user or "no-reply@aaijinursery.com")

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_email

        with _IPv4SMTP(host, port, timeout=10) as server:
            server.starttls()
            if user:
                server.login(user, password)
            server.sendmail(sender, [to_email], msg.as_string())
    except Exception as exc:  # noqa: BLE001 - notifications must never break the request
        print(f"[email] Failed to send to {to_email}: {exc}")
        record_error("External APIs", "SMTP", "send_email", "external:smtp", "EXTERNAL", 502, None, exc)


def send_whatsapp_admin_alert(message: str) -> None:
    from app.communications.gate import is_messaging_enabled, record_blocked

    if not is_messaging_enabled():
        record_blocked()
        print("[whatsapp] Messaging is switched off, skipping admin alert")
        return
    phone = os.environ.get("CALLMEBOT_PHONE", "")
    apikey = os.environ.get("CALLMEBOT_APIKEY", "")
    if not phone or not apikey:
        print(f"[whatsapp] CallMeBot not configured, skipping alert: {message}")
        return

    try:
        query = urllib.parse.urlencode({"phone": phone, "text": message, "apikey": apikey})
        url = f"https://api.callmebot.com/whatsapp.php?{query}"
        with urllib.request.urlopen(url, timeout=10) as response:
            response.read()
    except Exception as exc:  # noqa: BLE001 - notifications must never break the request
        print(f"[whatsapp] Failed to send alert: {exc}")
        record_error("External APIs", "WhatsApp", "send_whatsapp_admin_alert", "external:whatsapp", "EXTERNAL", 502, None, exc)


# Statuses whose customer message also names the driver, and the approved
# templates that carry the driver details. If no driver is set on the order,
# or the template is not ACTIVE yet, the normal status template is sent.
DRIVER_TEMPLATES = {
    "Packed": "order_packed_driver",
    "Out For Delivery": "out_for_delivery_driver",
}


def _driver_mobile(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return f"+91{digits[-10:]}" if len(digits) >= 10 else (phone or "")


def _queue_order_with_driver(order, event_type: str, new_status: str) -> bool:
    """Sends the driver-detail version of a status message. Returns False when
    it does not apply (no driver, no phone, other status, template not active),
    so the caller falls back to the standard message -- never both."""
    template_name = DRIVER_TEMPLATES.get(new_status)
    driver = getattr(order, "driver", None)
    if not template_name or not driver or not (driver.phone or "").strip():
        return False
    mobile, name = _order_contact(order)
    if not mobile:
        return False
    from app.communications.models import WhatsAppTemplate
    from app.communications.service import queue_message
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        tpl = db.query(WhatsAppTemplate).filter(WhatsAppTemplate.name == template_name).first()
        if not tpl or tpl.status != "ACTIVE":
            return False
    finally:
        db.close()
    queue_message(
        event_type=event_type, mobile=mobile, customer_name=name, template_name=template_name,
        template_params=[name, f"ORD-{order.id}", driver.name, _driver_mobile(driver.phone), order.vehicle_label or "N/A"],
        source_module="orders", source_id=order.id, customer_id=order.customer_id,
    )
    return True


def notify_order_status(order, old_status: str | None, new_status: str) -> None:
    message = f"Your order #{order.id} has been {new_status}."
    customer_email = order.customer.email if order.customer else None
    send_email(customer_email, f"Order #{order.id} update - {new_status}", message)
    send_whatsapp_admin_alert(f"Order #{order.id}: {old_status or 'New'} -> {new_status}")

    # Centralized customer-facing WhatsApp -- STATUS_TO_EVENT gives the
    # known statuses their proper named event; anything else falls back to
    # a generic ORDER_<STATUS> event. The actual template is resolved
    # centrally (never here) -- an event with no active/approved template
    # simply gets logged as such, it never raises.
    event_type = STATUS_TO_EVENT.get(new_status, f"ORDER_{new_status.upper().replace(' ', '_')}")
    if not _queue_order_with_driver(order, event_type, new_status):
        _queue_order_event(order, event_type, [_order_contact(order)[1], f"ORD-{order.id}", f"Rs.{order.total_amount}"])

    # Separate, additive event -- never replaces the standard ORDER_DELIVERED
    # notification above. Its own event_type gives it its own idempotency key
    # (GOOGLE_REVIEW_REQUEST:{order_id}), so repeated/duplicate Delivered
    # transitions can't double-send it, independent of the delivery message.
    # Skipped entirely (no queue attempt at all) if no review URL is
    # configured -- this can never affect the order/delivery flow either way.
    if new_status == "Delivered":
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            review_url = get_settings(db).get("google_review_url", "")
        finally:
            db.close()
        if review_url:
            _queue_order_event(order, "GOOGLE_REVIEW_REQUEST", [_order_contact(order)[1], review_url])


# Feature 2 (delivery feasibility + team confirmation) -- dedicated
# messages matching the exact customer-facing copy the business wants at
# each step, distinct from the generic status-change message above.

def notify_order_awaiting_confirmation(order) -> None:
    message = (
        "Your order request has been received.\n\n"
        "Our team will contact you within 1 hour to confirm delivery "
        "availability and charges.\n\n"
        f"Order #{order.id}\nTotal (before delivery charges): Rs.{order.subtotal}"
    )
    customer_email = order.customer.email if order.customer else None
    send_email(customer_email, f"Order #{order.id} Request Received", message)
    send_whatsapp_admin_alert(f"New order request #{order.id} awaiting delivery confirmation.")
    # No customer WhatsApp here on purpose: at this point the order is only a
    # request. The "order confirmed" message (ORDER_CREATED -> order_confirmed
    # template) is sent when the team confirms it -- see
    # notify_delivery_confirmed() below.


def notify_delivery_confirmed(order) -> None:
    message = (
        f"Good news! Our team has confirmed we can deliver order #{order.id}.\n\n"
        f"Products: Rs.{order.subtotal}\nDelivery: Rs.{order.shipping_fee}\nTotal: Rs.{order.total_amount}\n\n"
        + ("You can now complete your payment." if order.payment_method == "Razorpay" else "Your order will now be processed.")
    )
    customer_email = order.customer.email if order.customer else None
    send_email(customer_email, f"Order #{order.id} Confirmed", message)
    # The team has now confirmed the order, so this is when the customer gets
    # the "order confirmed" WhatsApp -- with the final total (delivery
    # included). Same idempotency key as before (ORDER_CREATED:{order_id}), so
    # an order that already received it earlier is never messaged twice.
    # The approved template prints "Rs." itself, so only the number is passed.
    # (The separate "delivery confirmed" message is no longer sent here: it
    # said the same thing as this one a second later.)
    _queue_order_event(order, "ORDER_CREATED", [_order_contact(order)[1], f"ORD-{order.id}", f"{order.total_amount:.2f}"])


def notify_delivery_unavailable(order) -> None:
    message = (
        f"We're sorry, our team is currently unable to deliver order #{order.id} to this location.\n\n"
        "Our team will contact you if an alternative arrangement is possible."
    )
    customer_email = order.customer.email if order.customer else None
    send_email(customer_email, f"Order #{order.id} - Delivery Unavailable", message)
    _queue_order_event(order, "DELIVERY_UNAVAILABLE", [_order_contact(order)[1], f"ORD-{order.id}"])


def _format_order_items(order) -> str:
    lines = [
        f"  - {item.plant_name} x{item.quantity} - Rs.{item.line_total}" for item in order.items
    ]
    return "\n".join(lines) if lines else "  (no items)"


def notify_payment_received(order) -> None:
    """Dedicated PAYMENT_RECEIVED WhatsApp event (section 10/11) -- distinct
    from the generic order-status-change message, since a payment can be
    verified without the status label itself saying anything about money."""
    _queue_order_event(order, "PAYMENT_RECEIVED", [_order_contact(order)[1], f"Rs.{order.total_amount:.2f}", f"ORD-{order.id}"])


def notify_order_cancelled(db, order, old_status: str | None, cancelled_by: str, reason: str) -> None:
    """Send a detailed cancellation email to both the customer and the business's
    admin contact email (from Site Settings -> Contact -> Email). cancelled_by is
    either 'customer' or 'admin'."""
    items_text = _format_order_items(order)
    cancelled_at = (order.updated_at or datetime.utcnow()).strftime("%d %b %Y, %I:%M %p")
    reason_text = reason.strip() if reason and reason.strip() else "Not specified"
    who_label = "Customer" if cancelled_by == "customer" else "Admin"

    customer_email = order.customer.email if order.customer else None
    customer_body = (
        "Your order has been successfully cancelled.\n\n"
        f"Order Number: #{order.id}\n"
        f"Status: Cancelled\n"
        f"Cancelled At: {cancelled_at}\n"
        f"Reason: {reason_text}\n\n"
        f"Items:\n{items_text}\n\n"
        f"Order Total: Rs.{order.total_amount}\n\n"
        "If you have any questions, please contact us."
    )
    send_email(customer_email, f"Your Order #{order.id} Has Been Cancelled", customer_body)

    admin_email = get_settings(db).get("email", "")
    customer_name = order.customer.name if order.customer else "Unknown"
    customer_phone = (order.customer.mobile if order.customer else "") or order.delivery_mobile
    admin_body = (
        f"Order #{order.id} has been cancelled.\n\n"
        f"Customer: {customer_name}\n"
        f"Email: {customer_email or '-'}\n"
        f"Phone: {customer_phone or '-'}\n"
        f"Cancelled At: {cancelled_at}\n"
        f"Cancelled By: {who_label}\n"
        f"Reason: {reason_text}\n"
        f"Order Total: Rs.{order.total_amount}\n\n"
        f"Items:\n{items_text}"
    )
    send_email(admin_email, f"Order Cancelled - #{order.id}", admin_body)

    send_whatsapp_admin_alert(f"Order #{order.id} CANCELLED by {cancelled_by}. Reason: {reason_text}")
    _queue_order_event(order, "ORDER_CANCELLED", [customer_name, f"ORD-{order.id}"])


# ---------------------------------------------------------------------------
# Extra WhatsApp messages (all go through queue_event, so they use the central
# event -> template map, the messaging ON/OFF switch, idempotency and retry).
# ---------------------------------------------------------------------------
from datetime import timedelta, timezone  # noqa: E402

_IST = timezone(timedelta(hours=5, minutes=30))


def _one_line(text: str, limit: int = 900) -> str:
    """WhatsApp template variables can't hold newlines/tabs or long runs of spaces."""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "..."


def format_date(value) -> str:
    return value.strftime("%d %b %Y").lstrip("0") if value else ""


def notify_admin_new_order(order) -> None:
    """One alert to the configured admin number for every NEW website order.
    The number comes from the ADMIN_ORDER_ALERT_MOBILE environment variable, so
    it is not hardcoded anywhere; without it nothing is sent. Idempotent per
    order (event key ADMIN_NEW_ORDER:<order id>), so a retried request cannot
    alert twice."""
    mobile = os.environ.get("ADMIN_ORDER_ALERT_MOBILE", "").strip()
    if not mobile:
        return
    items = ", ".join(
        f"{i.plant_name} x{i.quantity}" + (f" (tray of {i.tray_size})" if i.tray_size else "") for i in order.items
    )
    placed = (order.created_at or datetime.utcnow()).replace(tzinfo=timezone.utc).astimezone(_IST)
    queue_whatsapp_event(
        event_type="ADMIN_NEW_ORDER", mobile=mobile, customer_name="Admin",
        template_params=[
            f"ORD-{order.id}", _order_contact(order)[1], _one_line(items), f"Rs.{order.total_amount:.2f}",
            placed.strftime("%d %b %Y, %I:%M %p").lstrip("0"), "Pending - awaiting confirmation",
        ],
        source_module="orders", source_id=order.id, recipient_type="ADMIN",
    )


def notify_order_preparing(order) -> None:
    """Customer: the nursery is preparing the order (sent once per order)."""
    _queue_order_event_with_id(order, "ORDER_PREPARING", f"{order.id}", [_order_contact(order)[1], f"ORD-{order.id}"])


def notify_order_delivery_date(order) -> None:
    """Customer: the delivery date the team has set (re-sent only if the date changes)."""
    if not order.expected_delivery_date:
        return
    day = format_date(order.expected_delivery_date)
    _queue_order_event_with_id(
        order, "ORDER_DELIVERY_DATE", f"{order.id}:{order.expected_delivery_date:%Y-%m-%d}",
        [_order_contact(order)[1], f"ORD-{order.id}", day],
    )


def _queue_order_event_with_id(order, event_type: str, source_id: str, template_params: list) -> None:
    mobile, name = _order_contact(order)
    if not mobile:
        return
    queue_whatsapp_event(
        event_type=event_type, mobile=mobile, customer_name=name, template_params=template_params,
        source_module="orders", source_id=source_id, customer_id=order.customer_id,
    )


def notify_sales_order_preparing(sales_order) -> None:
    contact = sales_order.contact
    if not contact or not contact.phone:
        return
    queue_whatsapp_event(
        event_type="ORDER_PREPARING", mobile=contact.phone, customer_name=contact.name,
        template_params=[contact.name, sales_order.order_number],
        source_module="accounting", source_id=f"SO-{sales_order.id}",
        customer_id=contact.customer_id,
    )


def notify_sales_order_delivery_date(sales_order) -> None:
    contact = sales_order.contact
    if not contact or not contact.phone or not sales_order.delivery_date:
        return
    queue_whatsapp_event(
        event_type="ORDER_DELIVERY_DATE", mobile=contact.phone, customer_name=contact.name,
        template_params=[contact.name, sales_order.order_number, format_date(sales_order.delivery_date)],
        source_module="accounting", source_id=f"SO-{sales_order.id}:{sales_order.delivery_date:%Y-%m-%d}",
        customer_id=contact.customer_id,
    )


def notify_enquiry_received(name: str, mobile: str, inquiry_id) -> None:
    if not (mobile or "").strip():
        return
    queue_whatsapp_event(
        event_type="ENQUIRY_RECEIVED", mobile=mobile.strip(), customer_name=name or "Customer",
        template_params=[name or "Customer"], source_module="website", source_id=f"INQ-{inquiry_id}",
    )


def notify_welcome_customer(customer) -> None:
    if not (customer.mobile or "").strip():
        return
    queue_whatsapp_event(
        event_type="WELCOME_CUSTOMER", mobile=customer.mobile.strip(), customer_name=customer.name,
        template_params=[customer.name, _business_name()], source_module="website",
        source_id=f"CUST-{customer.id}", customer_id=customer.id,
    )
