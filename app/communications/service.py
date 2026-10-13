"""THE centralized messaging service (section 4). Every module -- Orders,
Accounting, Delivery, Website, Admin manual send -- calls `queue_message()`
here. Nothing outside this file ever imports app.communications.provider
directly.

Mirrors the safety pattern already proven in app/accounting/sync.py:
opens its OWN SessionLocal(), and the whole body is wrapped so a WhatsApp
failure can never propagate into the caller's own transaction (section 30).
"""
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.communications.gate import MESSAGING_OFF_CODE, MESSAGING_OFF_MESSAGE, is_messaging_enabled, record_blocked
from app.communications.models import WhatsAppEventTemplateMap, WhatsAppMessage, WhatsAppNotificationSetting, WhatsAppTemplate
from app.communications.phone import normalize_mobile
from app.communications.provider import get_provider, get_provider_name
from app.communications.worker import enqueue_message
from app.database import SessionLocal
from app.monitoring.recorder import record_error

logger = logging.getLogger("communications.service")


@dataclass
class QueueResult:
    ok: bool
    message: Optional[WhatsAppMessage] = None
    reason: str = ""  # populated when ok=False and nothing was queued (not an error, just a no-op)


def is_event_enabled(db, event_type: str) -> bool:
    row = db.query(WhatsAppNotificationSetting).filter(WhatsAppNotificationSetting.event_type == event_type).first()
    return row.enabled if row else True  # unconfigured events default ON


def _template_for(db, template_name: str) -> Optional[WhatsAppTemplate]:
    return db.query(WhatsAppTemplate).filter(WhatsAppTemplate.name == template_name).first()


def resolve_event_template(db, event_type: str) -> tuple[Optional[str], str]:
    """THE central event -> template resolution (never hardcoded per
    module). Returns (template_name, reason) -- template_name is None when
    there's no enabled mapping for this event, in which case `reason`
    explains why (never guessed/derived from the event name itself)."""
    row = db.query(WhatsAppEventTemplateMap).filter(WhatsAppEventTemplateMap.event_type == event_type).first()
    if not row:
        return None, f"No template mapping configured for event '{event_type}'"
    if not row.enabled:
        return None, f"Template mapping for event '{event_type}' is disabled"
    return row.template_name, ""


def _fit_params(template, params: list) -> list:
    """Meta rejects a template send whose parameter count differs from the
    approved body ("number of localizable_params (3) does not match the
    expected number of params (2)"). Callers share one generic parameter list
    per event family (name, order number, amount); templates that declare
    fewer variables get only their leading ones, in order."""
    try:
        declared = json.loads(template.variables) if template and template.variables else None
    except (ValueError, TypeError):
        declared = None
    if declared and len(params) > len(declared):
        return list(params[: len(declared)])
    return params


def queue_message(
    *,
    event_type: str,
    mobile: str,
    customer_name: str,
    template_name: str,
    template_params: list,
    source_module: str,
    source_id,
    customer_id: Optional[int] = None,
    recipient_type: str = "CUSTOMER",
    recipient_id: Optional[int] = None,
    metadata: Optional[dict] = None,
    created_by: str = "",
) -> QueueResult:
    """The one function every module calls. Never raises -- any failure
    (bad number, disabled event, unconfigured template, DB error) is
    swallowed and reported back as a non-fatal QueueResult/log entry, so a
    caller can fire this from inside an already-successful business
    transaction with zero risk to that transaction (section 30/42)."""
    if not is_messaging_enabled():
        # Global kill switch: nothing is queued, so nothing can be sent
        # later by surprise once messaging is switched back on.
        logger.info("Messaging is OFF, not queueing event=%s source=%s/%s", event_type, source_module, source_id)
        record_blocked()
        return QueueResult(False, reason=MESSAGING_OFF_CODE)

    db = SessionLocal()
    try:
        if not is_event_enabled(db, event_type):
            logger.info("WhatsApp event disabled, skipping event=%s source=%s/%s", event_type, source_module, source_id)
            return QueueResult(False, reason="EVENT_DISABLED")

        normalized = normalize_mobile(mobile)
        if not normalized:
            logger.info("Invalid mobile, skipping WhatsApp event=%s source=%s/%s", event_type, source_module, source_id)
            record_error(
                "Communications", "WhatsApp", "queue_message", "internal:whatsapp", "INTERNAL", 400, None, None,
                error_code="INVALID_MOBILE", message=f"Invalid mobile for {event_type}/{source_module}/{source_id}",
            )
            return QueueResult(False, reason="INVALID_MOBILE")

        idempotency_key = f"{event_type}:{source_id}"
        existing = db.query(WhatsAppMessage).filter(WhatsAppMessage.idempotency_key == idempotency_key).first()
        if existing and existing.status not in ("FAILED", "CANCELLED"):
            # Already queued/sent/delivered for this exact business event --
            # never send it twice (section 8/42), no matter how many times
            # this function gets called for the same event (page refresh,
            # request retry, worker restart, etc.).
            return QueueResult(True, message=existing, reason="ALREADY_QUEUED")

        template = _template_for(db, template_name)
        template_status = template.status if template else "NOT_CONFIGURED"
        template_params = _fit_params(template, template_params)
        if template is None or template_status != "ACTIVE":
            # Safety gate (never bypassed): a template must exist AND be
            # explicitly marked ACTIVE by an admin who has confirmed it's
            # really approved on Meta's side. PENDING/REJECTED/DISABLED/
            # NOT_CONFIGURED all block the send the same way -- the WhatsApp
            # request is never even attempted, so it can never be falsely
            # reported as sent.
            logger.info("WhatsApp template not active, skipping template=%s status=%s event=%s", template_name, template_status, event_type)
            msg = existing or WhatsAppMessage(idempotency_key=idempotency_key)
            msg.event_type = event_type
            msg.source_module = source_module
            msg.source_id = str(source_id)
            msg.recipient_type = recipient_type
            msg.recipient_id = recipient_id
            msg.customer_id = customer_id
            msg.customer_name = customer_name
            msg.mobile = normalized
            msg.template_name = template_name
            msg.template_params = json.dumps(template_params)
            msg.message_type = "template"
            msg.status = "FAILED"
            msg.error_code = template_status
            msg.error_message = f"WhatsApp template '{template_name}' is not active (status: {template_status})."
            msg.failed_at = datetime.utcnow()
            msg.provider = get_provider_name()
            msg.metadata_json = json.dumps(metadata or {})
            msg.created_by = created_by
            if not existing:
                db.add(msg)
            db.commit()
            db.refresh(msg)
            return QueueResult(False, message=msg, reason=f"TEMPLATE_{template_status}")

        msg = existing or WhatsAppMessage(idempotency_key=idempotency_key, created_at=datetime.utcnow())
        msg.event_type = event_type
        msg.source_module = source_module
        msg.source_id = str(source_id)
        msg.recipient_type = recipient_type
        msg.recipient_id = recipient_id
        msg.customer_id = customer_id
        msg.customer_name = customer_name
        msg.mobile = normalized
        msg.template_name = template_name
        msg.template_params = json.dumps(template_params)
        msg.message_type = "template"
        msg.status = "QUEUED"
        msg.provider = get_provider_name()
        msg.error_code = ""
        msg.error_message = ""
        msg.metadata_json = json.dumps(metadata or {})
        msg.created_by = created_by
        if not existing:
            db.add(msg)
        db.commit()
        db.refresh(msg)

        logger.info("WhatsApp message queued job_id=%s event=%s source=%s/%s", msg.id, event_type, source_module, source_id)
        enqueue_message(msg.id)
        return QueueResult(True, message=msg)
    except Exception as exc:  # noqa: BLE001 - must never break the caller's transaction
        db.rollback()
        logger.exception("queue_message failed event=%s source=%s/%s", event_type, source_module, source_id)
        record_error("Communications", "WhatsApp", "queue_message", "internal:whatsapp", "INTERNAL", 500, None, exc)
        return QueueResult(False, reason="INTERNAL_ERROR")
    finally:
        db.close()


def queue_event(
    *,
    event_type: str,
    mobile: str,
    customer_name: str,
    template_params: list,
    source_module: str,
    source_id,
    customer_id: Optional[int] = None,
    recipient_type: str = "CUSTOMER",
    recipient_id: Optional[int] = None,
    metadata: Optional[dict] = None,
) -> QueueResult:
    """THE entry point for every AUTOMATIC event (Orders/Delivery/
    Accounting/Website) -- callers pass an event_type and NEVER a template
    name; the template is resolved centrally via
    WhatsAppEventTemplateMap (resolve_event_template). This is what makes
    it impossible for an individual module to hardcode/guess a template
    name. `queue_message()` (with an explicit template_name) remains the
    lower-level primitive used by manual sends and the resolver below."""
    db = SessionLocal()
    try:
        template_name, reason = resolve_event_template(db, event_type)
    finally:
        db.close()

    if not template_name:
        logger.info("No template mapping for event=%s source=%s/%s: %s", event_type, source_module, source_id, reason)
        db = SessionLocal()
        try:
            idempotency_key = f"{event_type}:{source_id}"
            existing = db.query(WhatsAppMessage).filter(WhatsAppMessage.idempotency_key == idempotency_key).first()
            if existing and existing.status not in ("FAILED", "CANCELLED"):
                return QueueResult(True, message=existing, reason="ALREADY_QUEUED")
            normalized = normalize_mobile(mobile) or mobile
            msg = existing or WhatsAppMessage(idempotency_key=idempotency_key)
            msg.event_type = event_type
            msg.source_module = source_module
            msg.source_id = str(source_id)
            msg.recipient_type = recipient_type
            msg.recipient_id = recipient_id
            msg.customer_id = customer_id
            msg.customer_name = customer_name
            msg.mobile = normalized
            msg.template_name = ""
            msg.template_params = json.dumps(template_params)
            msg.message_type = "template"
            msg.status = "FAILED"
            msg.error_code = "EVENT_NOT_MAPPED"
            msg.error_message = reason
            msg.failed_at = datetime.utcnow()
            msg.metadata_json = json.dumps(metadata or {})
            if not existing:
                db.add(msg)
            db.commit()
            return QueueResult(False, reason="EVENT_NOT_MAPPED")
        finally:
            db.close()

    return queue_message(
        event_type=event_type, mobile=mobile, customer_name=customer_name,
        template_name=template_name, template_params=template_params,
        source_module=source_module, source_id=source_id,
        customer_id=customer_id, recipient_type=recipient_type, recipient_id=recipient_id,
        metadata=metadata,
    )


def queue_driver_event(
    *,
    event_type: str,
    driver,
    template_params: list,
    source_module: str,
    source_id,
    metadata: Optional[dict] = None,
) -> QueueResult:
    """Driver-facing counterpart of queue_event() (section 25/26's
    "resolve driver.whatsapp_number, validate active + configured" routing
    rules). Never fails the caller's business operation: an inactive driver
    or missing phone number just means the message never gets queued at
    all, logged as SKIPPED -- nothing upstream (trip/delivery) is affected."""
    if not driver or driver.status != "Active":
        logger.info("Driver not active, skipping driver WhatsApp event=%s source=%s/%s", event_type, source_module, source_id)
        return QueueResult(False, reason="DRIVER_NOT_ACTIVE")
    if not driver.phone:
        logger.info("Driver has no WhatsApp number, skipping event=%s source=%s/%s driver_id=%s", event_type, source_module, source_id, driver.id)
        return QueueResult(False, reason="DRIVER_WHATSAPP_NUMBER_NOT_CONFIGURED")
    return queue_event(
        event_type=event_type, mobile=driver.phone, customer_name=driver.name,
        template_params=template_params, source_module=source_module, source_id=source_id,
        recipient_type="DRIVER", recipient_id=driver.id, metadata=metadata,
    )


def queue_document_event(
    *,
    event_type: str,
    mobile: str,
    customer_name: str,
    source_module: str,
    source_id,
    pdf_bytes: bytes,
    filename: str,
    caption: str = "",
    customer_id: Optional[int] = None,
) -> QueueResult:
    """Sends a PDF (Invoice/Bill) as a WhatsApp document -- a SEPARATE
    queued message from the template text message (its own idempotency key,
    suffixed ':DOC', so calling this twice for the same invoice never sends
    the PDF twice, independent of whether the text message already went).
    Reuses the exact same queue/worker/retry/fault-isolation machinery as
    every other message -- the only difference is message_type='document'
    and the PDF bytes are stashed (base64) for the worker to upload."""
    import base64

    if not is_messaging_enabled():
        logger.info("Messaging is OFF, not queueing document event=%s source=%s/%s", event_type, source_module, source_id)
        record_blocked()
        return QueueResult(False, reason=MESSAGING_OFF_CODE)

    db = SessionLocal()
    try:
        if not is_event_enabled(db, event_type):
            return QueueResult(False, reason="EVENT_DISABLED")

        normalized = normalize_mobile(mobile)
        if not normalized:
            return QueueResult(False, reason="INVALID_MOBILE")

        idempotency_key = f"{event_type}:{source_id}:DOC"
        existing = db.query(WhatsAppMessage).filter(WhatsAppMessage.idempotency_key == idempotency_key).first()
        if existing and existing.status not in ("FAILED", "CANCELLED"):
            return QueueResult(True, message=existing, reason="ALREADY_QUEUED")

        msg = existing or WhatsAppMessage(idempotency_key=idempotency_key, created_at=datetime.utcnow())
        msg.event_type = event_type
        msg.source_module = source_module
        msg.source_id = str(source_id)
        msg.recipient_type = "CUSTOMER"
        msg.customer_id = customer_id
        msg.customer_name = customer_name
        msg.mobile = normalized
        msg.template_name = ""
        msg.template_params = "[]"
        msg.message_type = "document"
        msg.document_name = filename
        msg.status = "QUEUED"
        msg.provider = get_provider_name()
        msg.error_code = ""
        msg.error_message = ""
        msg.metadata_json = json.dumps({"document_base64": base64.b64encode(pdf_bytes).decode(), "caption": caption})
        if not existing:
            db.add(msg)
        db.commit()
        db.refresh(msg)
        logger.info("WhatsApp document queued job_id=%s event=%s source=%s/%s filename=%s", msg.id, event_type, source_module, source_id, filename)
        enqueue_message(msg.id)
        return QueueResult(True, message=msg)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("queue_document_event failed event=%s source=%s/%s", event_type, source_module, source_id)
        record_error("Communications", "WhatsApp", "queue_document_event", "internal:whatsapp", "INTERNAL", 500, None, exc)
        return QueueResult(False, reason="INTERNAL_ERROR")
    finally:
        db.close()


def queue_manual_message(
    *, mobile: str, customer_name: str, template_name: str, template_params: list,
    customer_id: Optional[int] = None, created_by: str = "",
) -> QueueResult:
    """Admin 'Send Message' (section 15) -- each click is intentionally a
    new event, so it gets its own unique source_id rather than colliding
    with automatic-event idempotency keys."""
    source_id = f"MANUAL-{uuid.uuid4().hex[:12]}"
    return queue_message(
        event_type="MANUAL_MESSAGE", mobile=mobile, customer_name=customer_name,
        template_name=template_name, template_params=template_params,
        source_module="manual", source_id=source_id, customer_id=customer_id,
        created_by=created_by,
    )


def retry_message(message_id: int) -> QueueResult:
    """Explicit, admin-triggered retry of a FAILED message (section 21's
    'Retry' row action / section 31's controlled-retry requirement)."""
    db = SessionLocal()
    try:
        msg = db.query(WhatsAppMessage).filter(WhatsAppMessage.id == message_id).first()
        if not msg:
            return QueueResult(False, reason="NOT_FOUND")
        if msg.status not in ("FAILED",):
            return QueueResult(False, reason="NOT_RETRYABLE")
        msg.status = "QUEUED"
        msg.error_code = ""
        msg.error_message = ""
        db.commit()
        db.refresh(msg)
        enqueue_message(msg.id)
        return QueueResult(True, message=msg)
    finally:
        db.close()


@dataclass
class TestResult:
    ok: bool
    error_code: str = ""
    error_message: str = ""


def send_test_message(mobile: str, template_name: str, template_params: list) -> TestResult:
    """'Send Test WhatsApp' (section 28) -- a real, synchronous, immediate-
    feedback send (not queued), still logged to the same central message
    table for auditability, but bypassing idempotency (a test is
    intentionally repeatable)."""
    if not is_messaging_enabled():
        record_blocked()
        return TestResult(False, error_code=MESSAGING_OFF_CODE, error_message=MESSAGING_OFF_MESSAGE)

    normalized = normalize_mobile(mobile)
    if not normalized:
        return TestResult(False, error_code="INVALID_MOBILE", error_message="Enter a valid 10-digit Indian mobile number")

    db = SessionLocal()
    try:
        template = _template_for(db, template_name)
        status = template.status if template else "NOT_CONFIGURED"
        if template is None or status != "ACTIVE":
            return TestResult(False, error_code=status, error_message=f"WhatsApp template '{template_name}' is not active (status: {status}).")

        try:
            variable_names = json.loads(template.variables) if template.variables else None
        except (ValueError, TypeError):
            variable_names = None

        provider = get_provider()
        result = provider.send_template_message(normalized, template_name, template_params, variable_names=variable_names, language_code=template.language or None)

        msg = WhatsAppMessage(
            idempotency_key=f"TEST_MESSAGE:{uuid.uuid4().hex}",
            event_type="TEST_MESSAGE", source_module="test", source_id="test",
            customer_name="Test", mobile=normalized, template_name=template_name,
            template_params=json.dumps(template_params), message_type="template",
            status="SENT" if result.ok else "FAILED",
            provider=get_provider_name(), provider_message_id=result.provider_message_id,
            error_code=result.error_code, error_message=result.error_message,
            sent_at=datetime.utcnow() if result.ok else None,
            failed_at=None if result.ok else datetime.utcnow(),
        )
        db.add(msg)
        db.commit()
        return TestResult(result.ok, error_code=result.error_code, error_message=result.error_message)
    finally:
        db.close()


def test_connection() -> TestResult:
    """'Test AiSensy Connection' (section 29)."""
    result = get_provider().test_connection()
    return TestResult(result.ok, error_code=result.error_code, error_message=result.error_message)
