"""Idempotent defaults -- creates the notification-toggle rows, the
event->template resolution map, and a starter template registry so the
Admin UI has something to show/configure, without ever auto-approving a
template (a template only reaches ACTIVE when an admin confirms Meta has
actually approved it)."""
import json

from app.communications.models import WhatsAppEventTemplateMap, WhatsAppNotificationSetting, WhatsAppTemplate

DEFAULT_EVENT_SETTINGS = [
    ("ORDER_CREATED", "Order Created"),
    ("ORDER_ACCEPTED", "Order Accepted"),
    ("ORDER_PROCESSING", "Order Processing"),
    ("ORDER_PACKED", "Order Packed"),
    ("ORDER_DISPATCHED", "Order Dispatched"),
    ("OUT_FOR_DELIVERY", "Out for Delivery"),
    ("ORDER_DELIVERED", "Order Delivered"),
    ("ORDER_CANCELLED", "Order Cancelled"),
    ("PAYMENT_RECEIVED", "Payment Received"),
    ("INVOICE_CREATED", "Invoice Created"),
    ("DELIVERY_ASSIGNED", "Delivery Assigned"),
    ("DELIVERY_READY", "Delivery Ready"),
    ("DELIVERY_OUT_FOR_DELIVERY", "Out for Delivery (Delivery module)"),
    ("DELIVERY_ARRIVED", "Driver Arrived"),
    ("DELIVERY_DELIVERED", "Delivery Completed"),
    ("DELIVERY_PARTIALLY_DELIVERED", "Delivery Partially Completed"),
    ("DELIVERY_FAILED", "Delivery Failed"),
    ("DELIVERY_CANCELLED", "Delivery Cancelled"),
    ("ENQUIRY_RECEIVED", "Enquiry Received"),
    ("WELCOME_CUSTOMER", "Welcome New Customer"),
    ("DELIVERY_FEASIBILITY_CONFIRMED", "Delivery Feasibility Confirmed"),
    ("DELIVERY_UNAVAILABLE", "Delivery Unavailable"),
    ("SALES_ORDER_CREATED", "Sales Order Created"),
    ("DELIVERY_ASSIGNED_TO_DRIVER", "Delivery Assigned to Driver"),
    ("TRIP_ASSIGNED_TO_DRIVER", "Trip Assigned to Driver"),
    ("GOOGLE_REVIEW_REQUEST", "Google Review Request"),
]

# THE central event -> template map (never hardcoded per module). Every
# automatic event goes through this exactly once, resolved by
# app.communications.service.queue_event().
DEFAULT_EVENT_TEMPLATE_MAP = [
    ("ORDER_CREATED", "order_confirmed"),
    ("ORDER_ACCEPTED", "order_accepted"),
    ("DELIVERY_FEASIBILITY_CONFIRMED", "delivery_confirmed"),
    ("ORDER_DISPATCHED", "order_dispatched"),
    ("OUT_FOR_DELIVERY", "out_for_delivery"),
    ("ORDER_DELIVERED", "order_delivered"),
    ("ORDER_CANCELLED", "order_cancelled"),
    ("ORDER_PROCESSING", "order_processing"),
    ("ORDER_PACKED", "order_packed"),
    ("DELIVERY_UNAVAILABLE", "delivery_unavailable"),
    ("PAYMENT_RECEIVED", "payment_received"),
    ("INVOICE_CREATED", "invoice_created"),
    ("DELIVERY_ASSIGNED", "delivery_assigned"),
    ("DELIVERY_READY", "delivery_ready"),
    ("DELIVERY_OUT_FOR_DELIVERY", "delivery_out_for_delivery"),
    ("DELIVERY_ARRIVED", "delivery_arrived"),
    ("DELIVERY_DELIVERED", "delivery_delivered"),
    ("DELIVERY_PARTIALLY_DELIVERED", "delivery_partially_delivered"),
    ("DELIVERY_FAILED", "delivery_failed"),
    ("DELIVERY_CANCELLED", "delivery_cancelled"),
    ("ENQUIRY_RECEIVED", "enquiry_received"),
    ("WELCOME_CUSTOMER", "welcome_customer"),
    ("SALES_ORDER_CREATED", "sales_order_created"),
    ("DELIVERY_ASSIGNED_TO_DRIVER", "delivery_assigned_to_driver"),
    ("TRIP_ASSIGNED_TO_DRIVER", "trip_assigned_to_driver"),
    ("GOOGLE_REVIEW_REQUEST", "google_review_request"),
]

# The 7 core templates use the exact copy specified in the WhatsApp
# Business Cloud API template-system master prompt (positional {{1}}/{{2}}/
# {{3}} translated to this project's named-placeholder preview convention
# -- Meta only cares about parameter ORDER, names are for our own UI only).
DEFAULT_TEMPLATES = [
    {
        "name": "order_confirmed", "category": "orders",
        "preview": "Hello {{customer_name}}, your order #{{order_number}} has been confirmed successfully.\nOrder amount: Rs.{{amount}}.\nThank you for shopping with us.",
        "variables": ["customer_name", "order_number", "amount"],
    },
    {
        "name": "order_accepted", "category": "orders",
        "preview": "Hello {{customer_name}}, your order #{{order_number}} has been accepted and is now being processed.",
        "variables": ["customer_name", "order_number"],
    },
    {
        "name": "order_cancelled", "category": "orders",
        "preview": "Hello {{customer_name}}, your order #{{order_number}} has been cancelled.\nIf you have any questions, please contact our support team.",
        "variables": ["customer_name", "order_number"],
    },
    {
        "name": "order_processing", "category": "orders",
        "preview": "Hello {{customer_name}}, your order {{order_number}} is now being processed.",
        "variables": ["customer_name", "order_number"],
    },
    {
        "name": "order_packed", "category": "orders",
        "preview": "Hello {{customer_name}}, your order {{order_number}} has been packed and is ready to ship.",
        "variables": ["customer_name", "order_number"],
    },
    {
        "name": "order_dispatched", "category": "orders",
        "preview": "Hello {{customer_name}}, your order #{{order_number}} has been dispatched.\nYou will receive further updates shortly.",
        "variables": ["customer_name", "order_number"],
    },
    {
        "name": "out_for_delivery", "category": "orders",
        "preview": "Hello {{customer_name}}, your order #{{order_number}} is out for delivery.\nPlease keep your phone available for the delivery partner.",
        "variables": ["customer_name", "order_number"],
    },
    {
        "name": "order_delivered", "category": "orders",
        "preview": "Hello {{customer_name}}, your order #{{order_number}} has been delivered successfully.\nThank you for shopping with us.",
        "variables": ["customer_name", "order_number"],
    },
    {
        "name": "payment_received", "category": "accounting",
        "preview": "Hello {{customer_name}}, we have received your payment of {{amount}}. Invoice: {{invoice_number}}. Thank you.",
        "variables": ["customer_name", "amount", "invoice_number"],
    },
    {
        "name": "invoice_created", "category": "accounting",
        "preview": "Hello {{customer_name}}, your invoice {{invoice_number}} has been generated. Amount: {{amount}}. Due Date: {{due_date}}.",
        "variables": ["customer_name", "invoice_number", "amount", "due_date"],
    },
    {
        "name": "welcome_customer", "category": "website",
        "preview": "Hello {{customer_name}}, welcome to {{business_name}}! We're glad to have you with us.",
        "variables": ["customer_name", "business_name"],
    },
    {
        "name": "enquiry_received", "category": "website",
        "preview": "Hello {{customer_name}}, we have received your enquiry. Our team will get back to you shortly.",
        "variables": ["customer_name"],
    },
    {
        "name": "delivery_confirmed", "category": "orders",
        "preview": "Hello {{customer_name}}, delivery for order #{{order_number}} has been confirmed.\nWe will keep you updated on the delivery status.",
        "variables": ["customer_name", "order_number"],
    },
    {
        "name": "delivery_unavailable", "category": "orders",
        "preview": "Hello {{customer_name}}, we're sorry, our team is currently unable to deliver order {{order_number}} to this location.",
        "variables": ["customer_name", "order_number"],
    },
    {
        "name": "delivery_assigned", "category": "delivery",
        "preview": "Hello {{customer_name}}, a delivery {{delivery_number}} has been scheduled for you.",
        "variables": ["customer_name", "delivery_number"],
    },
    {
        "name": "delivery_ready", "category": "delivery",
        "preview": "Hello {{customer_name}}, your delivery {{delivery_number}} is packed and ready to go out.",
        "variables": ["customer_name", "delivery_number"],
    },
    {
        "name": "delivery_out_for_delivery", "category": "delivery",
        "preview": "Hello {{customer_name}}, your delivery {{delivery_number}} is out for delivery with {{driver_name}}. Expected delivery today.",
        "variables": ["customer_name", "delivery_number", "driver_name"],
    },
    {
        "name": "delivery_arrived", "category": "delivery",
        "preview": "Hello {{customer_name}}, our driver {{driver_name}} has arrived for delivery {{delivery_number}}.",
        "variables": ["customer_name", "delivery_number", "driver_name"],
    },
    {
        "name": "delivery_delivered", "category": "delivery",
        "preview": "Hello {{customer_name}}, your delivery {{delivery_number}} has been completed successfully. Thank you!",
        "variables": ["customer_name", "delivery_number"],
    },
    {
        "name": "delivery_partially_delivered", "category": "delivery",
        "preview": "Hello {{customer_name}}, delivery {{delivery_number}} was partially completed. Our team will follow up on the remaining items.",
        "variables": ["customer_name", "delivery_number"],
    },
    {
        "name": "delivery_failed", "category": "delivery",
        "preview": "Hello {{customer_name}}, we were unable to complete delivery {{delivery_number}} today. Our team will contact you to reschedule.",
        "variables": ["customer_name", "delivery_number"],
    },
    {
        "name": "delivery_cancelled", "category": "delivery",
        "preview": "Hello {{customer_name}}, delivery {{delivery_number}} has been cancelled.",
        "variables": ["customer_name", "delivery_number"],
    },
    {
        "name": "sales_order_created", "category": "orders",
        "preview": "Hello {{customer_name}}, your sales order #{{order_number}} has been created.\nOrder amount: Rs.{{amount}}.",
        "variables": ["customer_name", "order_number", "amount"],
    },
    {
        "name": "delivery_assigned_to_driver", "category": "driver",
        "preview": "Hello {{driver_name}}, you have been assigned a delivery.\nOrder: #{{delivery_number}}\nCustomer: {{customer_name}}\nAddress: {{address}}\nScheduled Date: {{scheduled_date}}\nPlease complete the delivery as scheduled.",
        "variables": ["driver_name", "delivery_number", "customer_name", "address", "scheduled_date"],
    },
    {
        "name": "trip_assigned_to_driver", "category": "driver",
        "preview": "Hello {{driver_name}}, Trip #{{trip_number}} has been assigned to you.\nTotal Deliveries: {{delivery_count}}\nDate: {{trip_date}}\nPlease open your Delivery Dashboard for the complete route.",
        "variables": ["driver_name", "trip_number", "delivery_count", "trip_date"],
    },
    {
        "name": "google_review_request", "category": "orders",
        "preview": "Hello {{customer_name}}, thank you for shopping with AAIJI Nursery!\nWe hope you are happy with your plants and your overall experience.\nPlease share your honest experience with us on Google: {{review_url}}",
        "variables": ["customer_name", "review_url"],
    },
]


def seed_communications_defaults(session_factory) -> None:
    db = session_factory()
    try:
        existing_settings = {row.event_type for row in db.query(WhatsAppNotificationSetting).all()}
        for event_type, label in DEFAULT_EVENT_SETTINGS:
            if event_type not in existing_settings:
                db.add(WhatsAppNotificationSetting(event_type=event_type, label=label, enabled=True))

        existing_templates = {row.name for row in db.query(WhatsAppTemplate).all()}
        for t in DEFAULT_TEMPLATES:
            if t["name"] not in existing_templates:
                db.add(WhatsAppTemplate(
                    name=t["name"], aisensy_campaign_name=t["name"], category=t["category"],
                    language="en_US", preview=t["preview"], variables=json.dumps(t["variables"]),
                    is_active=False, status="PENDING",
                ))

        existing_map = {row.event_type for row in db.query(WhatsAppEventTemplateMap).all()}
        for event_type, template_name in DEFAULT_EVENT_TEMPLATE_MAP:
            if event_type not in existing_map:
                db.add(WhatsAppEventTemplateMap(event_type=event_type, template_name=template_name, enabled=True))

        db.commit()
    finally:
        db.close()
