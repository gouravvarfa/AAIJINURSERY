"""Developer-controlled ON/OFF switch for the Admin Assistant chatbot.

Same mechanism as the global messaging switch (app/communications/gate.py):
one row in the existing `system_flags` table, so it survives restarts, is
read fresh from the database on every request and every tool call (no cache),
and is only writable through a developer-only endpoint.

Differs from the messaging switch in one deliberate way: the default is OFF.
A brand-new chatbot should not be reachable by admins until a developer has
explicitly switched it on. It also fails closed -- if the flag can't be read,
the chatbot is treated as disabled.
"""
import logging
from datetime import datetime

from app.communications.models import SystemFlag
from app.database import SessionLocal

logger = logging.getLogger(__name__)

ADMIN_CHATBOT_KEY = "admin_chatbot_enabled"
ADMIN_CHATBOT_OFF_CODE = "ADMIN_CHATBOT_OFF"
ADMIN_CHATBOT_OFF_MESSAGE = "The Admin Assistant is currently switched off by the developer."


def is_admin_chatbot_enabled(db=None) -> bool:
    own = db is None
    session = SessionLocal() if own else db
    try:
        row = session.query(SystemFlag).filter(SystemFlag.key == ADMIN_CHATBOT_KEY).first()
        return row is not None and row.value == "1"
    except Exception:
        logger.exception("Could not read the Admin Assistant switch; treating it as OFF")
        return False
    finally:
        if own:
            session.close()


def set_admin_chatbot_enabled(db, enabled: bool, changed_by: str) -> None:
    row = db.query(SystemFlag).filter(SystemFlag.key == ADMIN_CHATBOT_KEY).first()
    if row is None:
        row = SystemFlag(key=ADMIN_CHATBOT_KEY)
        db.add(row)
    row.value = "1" if enabled else "0"
    row.updated_by = changed_by
    row.updated_at = datetime.utcnow()
    db.commit()


def admin_chatbot_status(db) -> dict:
    row = db.query(SystemFlag).filter(SystemFlag.key == ADMIN_CHATBOT_KEY).first()
    return {
        "enabled": row is not None and row.value == "1",
        "changed_by": (row.updated_by if row else "") or None,
        "changed_at": row.updated_at.isoformat() + "Z" if row and row.updated_at else None,
    }
