"""Global messaging kill switch.

One persisted flag decides whether *any* outgoing WhatsApp message may leave
the system -- automatic events, manual sends, test sends, inbox replies,
documents -- regardless of which module triggered it. It lives in the
database (table system_flags), so it survives refreshes and restarts, and is
read fresh on every send (no cache), so flipping it takes effect on the very
next message. Default (no row yet) is ON, i.e. existing behaviour.

Fails closed: if the flag can't be read, nothing is sent.
"""
import logging
from datetime import datetime

from app.communications.models import SystemFlag
from app.database import SessionLocal

logger = logging.getLogger(__name__)

MESSAGING_KEY = "messaging_enabled"
BLOCKED_KEY = "messaging_blocked_count"
MESSAGING_OFF_CODE = "MESSAGING_OFF"
MESSAGING_OFF_MESSAGE = "Messaging is switched off by the developer. No messages are being sent."


def is_messaging_enabled(db=None) -> bool:
    own = db is None
    session = SessionLocal() if own else db
    try:
        row = session.query(SystemFlag).filter(SystemFlag.key == MESSAGING_KEY).first()
        return row is None or row.value != "0"
    except Exception:
        logger.exception("Could not read the messaging switch; blocking sends to be safe")
        return False
    finally:
        if own:
            session.close()


def record_blocked() -> None:
    """Counts a message that was stopped by the switch (shown on the dashboard)."""
    db = SessionLocal()
    try:
        row = db.query(SystemFlag).filter(SystemFlag.key == BLOCKED_KEY).first()
        if row is None:
            row = SystemFlag(key=BLOCKED_KEY, value="0")
            db.add(row)
        row.value = str(int(row.value or 0) + 1)
        row.updated_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not record a blocked message")
    finally:
        db.close()


def set_messaging_enabled(db, enabled: bool, changed_by: str) -> None:
    row = db.query(SystemFlag).filter(SystemFlag.key == MESSAGING_KEY).first()
    if row is None:
        row = SystemFlag(key=MESSAGING_KEY)
        db.add(row)
    row.value = "1" if enabled else "0"
    row.updated_by = changed_by
    row.updated_at = datetime.utcnow()
    if not enabled:
        # A fresh OFF period starts a fresh count of what it stopped.
        counter = db.query(SystemFlag).filter(SystemFlag.key == BLOCKED_KEY).first()
        if counter is None:
            db.add(SystemFlag(key=BLOCKED_KEY, value="0"))
        else:
            counter.value = "0"
            counter.updated_at = datetime.utcnow()
    db.commit()


def messaging_status(db) -> dict:
    row = db.query(SystemFlag).filter(SystemFlag.key == MESSAGING_KEY).first()
    counter = db.query(SystemFlag).filter(SystemFlag.key == BLOCKED_KEY).first()
    enabled = row is None or row.value != "0"
    return {
        "enabled": enabled,
        "changed_by": (row.updated_by if row else "") or None,
        "changed_at": row.updated_at.isoformat() + "Z" if row and row.updated_at else None,
        "blocked_while_off": int(counter.value or 0) if counter and not enabled else 0,
    }
