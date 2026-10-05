"""Meta WhatsApp Cloud API webhook (PUBLIC -- Meta carries no admin login,
so this router is mounted without the communications permission gate and
protects itself instead):

  GET  -> one-time subscription handshake, checked against
          WHATSAPP_WEBHOOK_VERIFY_TOKEN
  POST -> every event body must carry a valid X-Hub-Signature-256 HMAC made
          with WHATSAPP_APP_SECRET, otherwise it is rejected (403) -- without
          that anyone on the internet could inject fake customer replies.

Handles two things: customer replies (stored in whatsapp_inbox_messages) and
delivery/read/failed statuses (written onto the existing whatsapp_messages
row and onto our own inbox replies).
"""
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import PlainTextResponse

from app.communications.inbox_models import WhatsAppInboxMessage
from app.communications.models import WhatsAppMessage
from app.database import SessionLocal

logger = logging.getLogger("communications.webhook")
router = APIRouter(prefix="/api/webhooks/whatsapp", tags=["whatsapp-webhook"])

_STATUS_RANK = {"QUEUED": 0, "PROCESSING": 1, "SENT": 2, "DELIVERED": 3, "READ": 4}
_META_STATUS = {"sent": "SENT", "delivered": "DELIVERED", "read": "READ", "failed": "FAILED"}


def _signature_ok(raw_body: bytes, header: str) -> bool:
    secret = os.environ.get("WHATSAPP_APP_SECRET", "")
    if not secret or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


def _ts(raw) -> datetime:
    try:
        return datetime.utcfromtimestamp(int(raw))
    except (TypeError, ValueError):
        return datetime.utcnow()


def _inbound_body(msg: dict) -> tuple[str, str]:
    """-> (body text, media id) for any inbound message type."""
    kind = msg.get("type", "")
    if kind == "text":
        return (msg.get("text") or {}).get("body", ""), ""
    if kind == "button":
        return (msg.get("button") or {}).get("text", ""), ""
    if kind == "interactive":
        inter = msg.get("interactive") or {}
        picked = inter.get("button_reply") or inter.get("list_reply") or {}
        return picked.get("title", ""), ""
    if kind == "location":
        loc = msg.get("location") or {}
        return f"Location: {loc.get('latitude')}, {loc.get('longitude')} {loc.get('name', '')}".strip(), ""
    media = msg.get(kind) if isinstance(msg.get(kind), dict) else {}
    caption = media.get("caption") or media.get("filename") or ""
    return (f"[{kind}] {caption}".strip() if kind else caption), media.get("id", "")


def _store_inbound(db, value: dict) -> None:
    names = {c.get("wa_id"): (c.get("profile") or {}).get("name", "") for c in value.get("contacts", [])}
    for msg in value.get("messages", []):
        wamid = msg.get("id", "")
        if not wamid or db.query(WhatsAppInboxMessage).filter(WhatsAppInboxMessage.wa_message_id == wamid).first():
            continue  # Meta retries on any non-200 -- never store the same reply twice
        sender = msg.get("from", "")
        body, media_id = _inbound_body(msg)
        db.add(WhatsAppInboxMessage(
            wa_message_id=wamid, mobile=f"+{sender}", profile_name=names.get(sender, ""),
            direction="IN", message_type=msg.get("type", "text"), body=body, media_id=media_id,
            status="RECEIVED", is_read=False, created_at=_ts(msg.get("timestamp")),
        ))


def _apply_status(db, st: dict) -> None:
    new_status = _META_STATUS.get(st.get("status", ""))
    wamid = st.get("id", "")
    if not new_status or not wamid:
        return
    when = _ts(st.get("timestamp"))
    err = (st.get("errors") or [{}])[0]
    err_code, err_text = str(err.get("code", "")), err.get("error_data", {}).get("details") or err.get("title", "")

    row = db.query(WhatsAppMessage).filter(WhatsAppMessage.provider_message_id == wamid).first()
    if row:
        current = _STATUS_RANK.get(row.status, -1)
        if new_status == "FAILED":
            if current < _STATUS_RANK["DELIVERED"]:  # a late "failed" must never overwrite a real delivery
                row.status, row.failed_at, row.error_code, row.error_message = "FAILED", when, err_code, err_text
        elif _STATUS_RANK[new_status] > current:  # statuses can arrive out of order -- only move forward
            row.status = new_status
            if new_status == "SENT":
                row.sent_at = row.sent_at or when
            elif new_status == "DELIVERED":
                row.delivered_at = when
            elif new_status == "READ":
                row.read_at = when
                row.delivered_at = row.delivered_at or when

    reply = db.query(WhatsAppInboxMessage).filter(WhatsAppInboxMessage.wa_message_id == wamid).first()
    if reply and reply.direction == "OUT":
        current = _STATUS_RANK.get(reply.status, -1)
        if new_status == "FAILED":
            if current < _STATUS_RANK["DELIVERED"]:
                reply.status, reply.error_message = "FAILED", err_text or err_code
        elif _STATUS_RANK[new_status] > current:
            reply.status = new_status


@router.get("")
def verify(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
):
    expected = os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "")
    if mode == "subscribe" and expected and hmac.compare_digest(token, expected):
        return PlainTextResponse(challenge)
    return Response(status_code=403)


@router.post("")
async def receive(request: Request):
    raw = await request.body()
    if not _signature_ok(raw, request.headers.get("X-Hub-Signature-256", "")):
        return Response(status_code=403)

    db = SessionLocal()
    try:
        payload = json.loads(raw.decode() or "{}")
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value") or {}
                _store_inbound(db, value)
                for st in value.get("statuses", []):
                    _apply_status(db, st)
        db.commit()
    except Exception:  # noqa: BLE001 - a bad event must never make Meta retry-storm us
        db.rollback()
        logger.exception("whatsapp webhook processing failed")
    finally:
        db.close()
    return Response(status_code=200)
