"""Developer-only control for the global messaging ON/OFF switch."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit import record_admin_audit
from app.communications.gate import messaging_status, set_messaging_enabled
from app.database import get_db
from app.deps import get_current_developer

router = APIRouter(prefix="/api/admin/messaging-control", tags=["messaging-control"])


class MessagingControlIn(BaseModel):
    enabled: bool


@router.get("")
def get_status(admin: str = Depends(get_current_developer), db: Session = Depends(get_db)):
    return messaging_status(db)


@router.put("")
def set_status(payload: MessagingControlIn, admin: str = Depends(get_current_developer), db: Session = Depends(get_db)):
    set_messaging_enabled(db, payload.enabled, admin)
    record_admin_audit(admin, "messaging_switched_on" if payload.enabled else "messaging_switched_off", {"enabled": payload.enabled})
    return messaging_status(db)
