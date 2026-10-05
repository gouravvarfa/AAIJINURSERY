"""Two-way WhatsApp conversation log (customer replies + our free-form
replies). Kept separate from `whatsapp_messages`, which stays the log of
outbound TEMPLATE sends only -- delivery/read status webhooks still update
that table directly, nothing in it changes shape.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint

from app.database import Base


class WhatsAppInboxMessage(Base):
    __tablename__ = "whatsapp_inbox_messages"
    __table_args__ = (UniqueConstraint("wa_message_id", name="uq_whatsapp_inbox_wa_message_id"),)

    id = Column(Integer, primary_key=True, index=True)
    wa_message_id = Column(String(160), nullable=False, index=True)  # Meta's wamid -- also what makes webhook retries idempotent
    mobile = Column(String(20), nullable=False, index=True)  # "+<wa_id>", same shape as whatsapp_messages.mobile
    profile_name = Column(String(150), default="")  # WhatsApp display name the customer gave Meta (inbound only)
    direction = Column(String(3), nullable=False, default="IN", index=True)  # IN|OUT
    message_type = Column(String(20), default="text")  # text|image|document|audio|video|sticker|location|button|...
    body = Column(Text, default="")
    media_id = Column(String(120), default="")
    status = Column(String(20), default="RECEIVED")  # IN: RECEIVED | OUT: SENT|DELIVERED|READ|FAILED
    error_message = Column(Text, default="")
    is_read = Column(Boolean, default=False, index=True)  # admin has opened the thread (inbound only)
    created_by = Column(String(80), default="")  # admin username for OUT
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
