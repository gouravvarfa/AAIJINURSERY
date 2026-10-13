"""Centralized WhatsApp / messaging tables -- the ONE message log, ONE
template registry and ONE per-event settings table every module (Orders,
Accounting, Delivery, Website, Admin manual send, future bulk Campaigns)
shares. No module gets its own WhatsApp table.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, UniqueConstraint

from app.database import Base

MESSAGE_STATUSES = ["QUEUED", "PROCESSING", "SENT", "DELIVERED", "READ", "FAILED", "CANCELLED"]
TEMPLATE_STATUSES = ["ACTIVE", "PENDING", "REJECTED", "DISABLED"]  # NOT_CONFIGURED is synthetic (no row/mapping)


class WhatsAppMessage(Base):
    """One row per WhatsApp send attempt -- the single, centralized message
    history referenced from Order/Invoice/Payment/Delivery/Customer profile
    panels alike via (source_module, source_id), never duplicated per
    module. idempotency_key ("<event_type>:<source_id>") is what actually
    prevents the same business event from ever being sent twice."""

    __tablename__ = "whatsapp_messages"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_whatsapp_idempotency_key"),)

    id = Column(Integer, primary_key=True, index=True)
    idempotency_key = Column(String(160), nullable=False, index=True)
    event_type = Column(String(60), nullable=False, index=True)
    source_module = Column(String(30), nullable=False, index=True)  # orders/accounting/delivery/website/manual/campaign
    source_id = Column(String(60), nullable=False, index=True)
    recipient_type = Column(String(10), nullable=False, default="CUSTOMER", index=True)  # CUSTOMER|DRIVER
    customer_id = Column(Integer, nullable=True, index=True)  # set only when recipient_type=CUSTOMER
    recipient_id = Column(Integer, nullable=True, index=True)  # driver.id when recipient_type=DRIVER (customer_id kept for CUSTOMER, for backward compat with existing profile-panel queries)
    customer_name = Column(String(150), default="")
    mobile = Column(String(20), nullable=False)
    template_name = Column(String(80), nullable=False)
    template_params = Column(Text, default="[]")  # JSON list, resolved values (not raw {{placeholders}})
    message_type = Column(String(20), default="template")  # template|document
    document_name = Column(String(200), default="")
    media_id = Column(String(120), default="")  # Meta media ID once a document is uploaded
    status = Column(String(20), nullable=False, default="QUEUED", index=True)
    provider = Column(String(20), default="aisensy")
    provider_message_id = Column(String(120), default="")
    error_code = Column(String(60), default="")
    error_message = Column(Text, default="")
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    sent_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    created_by = Column(String(80), default="")  # admin username for manual sends, "" for automatic
    metadata_json = Column(Text, default="{}")


class WhatsAppTemplate(Base):
    """Registry of templates this system is allowed to send. A template must
    exist here AND be marked active before any event can use it -- this is
    what stops the system from ever sending arbitrary text as if it were an
    approved WhatsApp template (section 19's requirement)."""

    __tablename__ = "whatsapp_templates"
    __table_args__ = (UniqueConstraint("name", name="uq_whatsapp_template_name"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(80), nullable=False)  # internal key, e.g. "order_confirmed"
    aisensy_campaign_name = Column(String(120), default="")  # exact campaign name configured in AiSensy
    category = Column(String(40), default="")
    language = Column(String(10), default="en")
    preview = Column(Text, default="")
    variables = Column(Text, default="[]")  # JSON list of {{placeholder}} names in order
    is_active = Column(Boolean, default=False)  # legacy flag, superseded by `status` -- kept for old rows/migration
    status = Column(String(20), nullable=False, default="PENDING", index=True)  # ACTIVE|PENDING|REJECTED|DISABLED
    last_error = Column(Text, default="")  # most recent Meta/provider error seen for this template, if any
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WhatsAppEventTemplateMap(Base):
    """THE central event -> template resolution table (never hardcoded per
    module). Orders/Delivery/Accounting/Website only ever pass an
    `event_type` to `queue_event()` -- this table is the single place that
    decides which approved template name answers that event, and whether
    the mapping itself is currently enabled. Admin-editable."""

    __tablename__ = "whatsapp_event_template_map"
    __table_args__ = (UniqueConstraint("event_type", name="uq_whatsapp_event_map"),)

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(60), nullable=False)
    template_name = Column(String(80), nullable=False)
    enabled = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WhatsAppNotificationSetting(Base):
    """Per-event ON/OFF toggle (section 20) -- checked before any automatic
    (non-manual) message is queued."""

    __tablename__ = "whatsapp_notification_settings"
    __table_args__ = (UniqueConstraint("event_type", name="uq_whatsapp_setting_event"),)

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(60), nullable=False)
    label = Column(String(120), default="")
    enabled = Column(Boolean, default=True)


class SystemFlag(Base):
    """Small persisted on/off switches that must survive restarts and be read
    by every worker/request -- currently the global messaging kill switch.
    Kept out of SiteSetting on purpose: that table is served to the public
    website, this one is developer-only."""

    __tablename__ = "system_flags"

    key = Column(String(60), primary_key=True)
    value = Column(String(200), default="")
    updated_by = Column(String(80), default="")
    updated_at = Column(DateTime, default=datetime.utcnow)



class WhatsAppTopup(Base):
    """Money added to the WhatsApp (Meta) prepaid balance, entered by the
    developer. Meta does not expose the remaining balance through its API, so
    the balance shown in the app is: these top-ups minus the real spend Meta
    reports (pricing analytics)."""

    __tablename__ = "whatsapp_topups"

    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Float, nullable=False)
    topup_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    note = Column(String(200), default="")
    added_by = Column(String(80), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
