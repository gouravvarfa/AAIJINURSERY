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
    mobile = (order.customer.mobile if order.customer else "") or order.delivery_mobile
    name = (order.customer.name if order.customer else "") or order.delivery_name or "Customer"
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
    _queue_order_event(order, "ORDER_CREATED", [_order_contact(order)[1], f"ORD-{order.id}", f"Rs.{order.subtotal}"])


def notify_delivery_confirmed(order) -> None:
    message = (
        f"Good news! Our team has confirmed we can deliver order #{order.id}.\n\n"
        f"Products: Rs.{order.subtotal}\nDelivery: Rs.{order.shipping_fee}\nTotal: Rs.{order.total_amount}\n\n"
        + ("You can now complete your payment." if order.payment_method == "Razorpay" else "Your order will now be processed.")
    )
    customer_email = order.customer.email if order.customer else None
    send_email(customer_email, f"Order #{order.id} Confirmed", message)
    _queue_order_event(order, "DELIVERY_FEASIBILITY_CONFIRMED", [_order_contact(order)[1], f"ORD-{order.id}"])


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
    _queue_order_event(order, "PAYMENT_RECEIVED", [_order_contact(order)[1], f"Rs.{order.total_amount}", f"ORD-{order.id}"])


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
