"""Admin reply inbox. WhatsApp only allows free-form (non-template) text
within 24 hours of the customer's last message to us, so a reply is refused
here up front (with a clear reason) once that window has closed -- after
that the only way to reach the customer is an approved template.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.communications.inbox_models import WhatsAppInboxMessage
from app.communications.models import WhatsAppMessage
from app.database import get_db
from app.deps import get_current_admin
from app.permissions import require_permission

router = APIRouter(prefix="/api/admin/communications/inbox", tags=["communications-inbox"])

REPLY_WINDOW = timedelta(hours=24)


class ReplyIn(BaseModel):
    mobile: str = Field(min_length=6, max_length=20)
    text: str = Field(min_length=1, max_length=4000)


class ReadIn(BaseModel):
    mobile: str


def _msg_out(m: WhatsAppInboxMessage) -> dict:
    return {
        "id": m.id, "direction": m.direction, "message_type": m.message_type, "body": m.body,
        "status": m.status, "error_message": m.error_message, "created_by": m.created_by,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _window_open(db: Session, mobile: str) -> tuple[bool, datetime | None]:
    last_in = (
        db.query(func.max(WhatsAppInboxMessage.created_at))
        .filter(WhatsAppInboxMessage.mobile == mobile, WhatsAppInboxMessage.direction == "IN").scalar()
    )
    return bool(last_in and datetime.utcnow() - last_in < REPLY_WINDOW), last_in


@router.get("/conversations", dependencies=[Depends(require_permission("communications", "VIEW"))])
def list_conversations(q: str = Query("", max_length=60), db: Session = Depends(get_db)):
    latest_ids = db.query(func.max(WhatsAppInboxMessage.id)).group_by(WhatsAppInboxMessage.mobile).subquery()
    rows = (
        db.query(WhatsAppInboxMessage).filter(WhatsAppInboxMessage.id.in_(latest_ids))
        .order_by(WhatsAppInboxMessage.created_at.desc()).limit(200).all()
    )
    unread = dict(
        db.query(WhatsAppInboxMessage.mobile, func.count(WhatsAppInboxMessage.id))
        .filter(WhatsAppInboxMessage.direction == "IN", WhatsAppInboxMessage.is_read.is_(False))
        .group_by(WhatsAppInboxMessage.mobile).all()
    )
    items = []
    for last in rows:
        profile = (
            db.query(WhatsAppInboxMessage.profile_name)
            .filter(WhatsAppInboxMessage.mobile == last.mobile, WhatsAppInboxMessage.profile_name != "")
            .order_by(WhatsAppInboxMessage.id.desc()).first()
        )
        known = db.query(WhatsAppMessage.customer_name).filter(WhatsAppMessage.mobile == last.mobile, WhatsAppMessage.customer_name != "").first()
        name = (known[0] if known else "") or (profile[0] if profile else "")
        if q and q.lower() not in f"{name} {last.mobile} {last.body}".lower():
            continue
        items.append({
            "mobile": last.mobile, "name": name, "last_message": last.body, "last_direction": last.direction,
            "last_at": last.created_at.isoformat() if last.created_at else None, "unread": unread.get(last.mobile, 0),
        })
    return {"items": items, "total_unread": sum(unread.values())}


@router.get("/messages", dependencies=[Depends(require_permission("communications", "VIEW"))])
def thread(mobile: str = Query(..., min_length=6, max_length=20), db: Session = Depends(get_db)):
    rows = (
        db.query(WhatsAppInboxMessage).filter(WhatsAppInboxMessage.mobile == mobile)
        .order_by(WhatsAppInboxMessage.created_at.asc(), WhatsAppInboxMessage.id.asc()).limit(500).all()
    )
    open_, last_in = _window_open(db, mobile)
    return {
        "items": [_msg_out(m) for m in rows],
        "window_open": open_,
        "window_closes_at": (last_in + REPLY_WINDOW).isoformat() if open_ else None,
    }


@router.post("/read", dependencies=[Depends(require_permission("communications", "VIEW"))])
def mark_read(payload: ReadIn, db: Session = Depends(get_db)):
    db.query(WhatsAppInboxMessage).filter(
        WhatsAppInboxMessage.mobile == payload.mobile, WhatsAppInboxMessage.direction == "IN",
        WhatsAppInboxMessage.is_read.is_(False),
    ).update({"is_read": True})
    db.commit()
    return {"ok": True}


@router.post("/reply", dependencies=[Depends(require_permission("communications", "CREATE"))])
def reply(payload: ReplyIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    open_, _ = _window_open(db, payload.mobile)
    if not open_:
        raise HTTPException(409, "The 24-hour reply window is closed. The customer must message first, or send an approved template instead.")

    token = os.environ.get("WHATSAPP_CLOUD_API_TOKEN", "")
    phone_id = os.environ.get("WHATSAPP_CLOUD_API_PHONE_ID", "")
    version = os.environ.get("WHATSAPP_CLOUD_API_VERSION", "v20.0")
    if not (token and phone_id):
        raise HTTPException(503, "WhatsApp Cloud API is not configured.")

    body = {
        "messaging_product": "whatsapp", "to": payload.mobile.lstrip("+"), "type": "text",
        "text": {"body": payload.text, "preview_url": False},
    }
    req = urllib.request.Request(
        f"https://graph.facebook.com/{version}/{phone_id}/messages", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode()).get("error", {})
            detail = err.get("error_data", {}).get("details") or err.get("message") or "Meta rejected the message"
        except ValueError:
            detail = "Meta rejected the message"
        raise HTTPException(502, detail)
    except (urllib.error.URLError, TimeoutError):
        raise HTTPException(502, "Could not reach WhatsApp. Try again.")

    wamid = str((data.get("messages") or [{}])[0].get("id", ""))
    if not wamid:
        raise HTTPException(502, "WhatsApp did not confirm the message.")
    row = WhatsAppInboxMessage(
        wa_message_id=wamid, mobile=payload.mobile, direction="OUT", message_type="text", body=payload.text,
        status="SENT", is_read=True, created_by=admin if isinstance(admin, str) else getattr(admin, "username", ""),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _msg_out(row)
