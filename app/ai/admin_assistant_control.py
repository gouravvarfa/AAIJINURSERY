"""Developer-only control for the Admin Assistant ON/OFF switch."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.admin_assistant_gate import admin_chatbot_status, set_admin_chatbot_enabled
from app.audit import record_admin_audit
from app.database import get_db
from app.deps import get_current_developer

router = APIRouter(prefix="/api/admin/admin-chatbot-control", tags=["admin-assistant"])


class AdminChatbotControlIn(BaseModel):
    enabled: bool


@router.get("")
def get_status(admin: str = Depends(get_current_developer), db: Session = Depends(get_db)):
    return admin_chatbot_status(db)


@router.put("")
def set_status(payload: AdminChatbotControlIn, admin: str = Depends(get_current_developer), db: Session = Depends(get_db)):
    set_admin_chatbot_enabled(db, payload.enabled, admin)
    record_admin_audit(admin, "admin_chatbot_switched_on" if payload.enabled else "admin_chatbot_switched_off", {"enabled": payload.enabled})
    return admin_chatbot_status(db)
