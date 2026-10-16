"""Details printed on the invoice PDF (bank, terms, signature, ...).

Kept in its own table (NOT site_settings, which the public website can read). Nothing is filled in by
default: an empty value simply leaves that block off the invoice."""
import base64
import re
from datetime import datetime
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.accounting.audit import record_change
from app.accounting.models import InvoiceSetting
from app.accounting.permissions import SETTINGS_WRITE_ROLES, require_accounting_action
from app.database import get_db
from app.deps import get_current_admin

router = APIRouter(prefix="/invoice-settings", tags=["accounting-invoice-settings"])

FIELDS = [
    ("invoice_proprietor", "Proprietor name", "Shown under the business name, only if filled."),
    ("invoice_website", "Website", "Shown in the header and footer, only if filled."),
    ("invoice_gstin", "GSTIN", "Shown only if filled. 15 characters."),
    ("invoice_bank_name", "Bank name", ""),
    ("invoice_bank_account", "Account number", "Digits only."),
    ("invoice_bank_ifsc", "IFSC code", "Like HDFC0001234."),
    ("invoice_bank_holder", "Account holder name", ""),
    ("invoice_payment_note", "Payment note", "A short line printed on every invoice."),
    ("invoice_terms", "Terms and conditions", "One term per line. Hindi is supported."),
    ("invoice_extra_phones", "Other contact numbers", "One line each, for example: Booking office: 9754315710"),
]
LIMITS = {"invoice_terms": 1500, "invoice_extra_phones": 600, "invoice_payment_note": 300}
SIGNATURE_KEY = "invoice_signature"
MAX_SIGNATURE_BYTES = 300_000


class InvoiceSettingsIn(BaseModel):
    values: Dict[str, str] = Field(default_factory=dict)


def _clean(key: str, value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    if key == "invoice_gstin":
        v = v.upper().replace(" ", "")
        if not re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", v):
            raise HTTPException(status_code=400, detail="GSTIN is not valid (it has 15 characters, like 24AABCR1234F1Z5)")
    elif key == "invoice_bank_account":
        v = re.sub(r"\s+", "", v)
        if not re.fullmatch(r"\d{6,20}", v):
            raise HTTPException(status_code=400, detail="Account number must be 6 to 20 digits")
    elif key == "invoice_bank_ifsc":
        v = v.upper().replace(" ", "")
        if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", v):
            raise HTTPException(status_code=400, detail="IFSC code is not valid (like HDFC0001234)")
    elif key == "invoice_website":
        if not re.fullmatch(r"(https?://)?[\w.-]+\.[a-z]{2,}(/\S*)?", v, re.I):
            raise HTTPException(status_code=400, detail="Website is not valid")
    limit = LIMITS.get(key, 150)
    if len(v) > limit:
        raise HTTPException(status_code=400, detail=f"{dict((k, l) for k, l, _ in FIELDS)[key]} is too long (at most {limit} characters)")
    return v


def _clean_signature(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    m = re.fullmatch(r"data:image/(png|jpeg);base64,([A-Za-z0-9+/=\s]+)", v)
    if not m:
        raise HTTPException(status_code=400, detail="Signature must be a PNG or JPEG image")
    try:
        raw = base64.b64decode(m.group(2), validate=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Signature image is damaged")
    if len(raw) > MAX_SIGNATURE_BYTES:
        raise HTTPException(status_code=400, detail="Signature image is too big (keep it under 300 KB)")
    return v


@router.get("")
def read_invoice_settings(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    saved = {r.key: r.value or "" for r in db.query(InvoiceSetting).all()}
    return {"fields": [{"key": k, "label": label, "hint": hint, "value": saved.get(k, "")} for k, label, hint in FIELDS], "signature": saved.get(SIGNATURE_KEY, "")}


@router.put("")
def save_invoice_settings(
    payload: InvoiceSettingsIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("EDIT", SETTINGS_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    allowed = {k for k, _, _ in FIELDS} | {SIGNATURE_KEY}
    unknown = [k for k in payload.values if k not in allowed]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown setting: {unknown[0]}")
    cleaned = {k: (_clean_signature(v) if k == SIGNATURE_KEY else _clean(k, v)) for k, v in payload.values.items()}
    for key, value in cleaned.items():
        row = db.query(InvoiceSetting).filter(InvoiceSetting.key == key).first()
        old = row.value if row else ""
        if row is None:
            row = InvoiceSetting(key=key)
            db.add(row)
        if (old or "") != value:
            row.value, row.updated_by, row.updated_at = value, admin, datetime.utcnow()
            # the audit log keeps who changed what; the signature image itself is not copied into it
            record_change(db, "accounting_invoice_settings", 0, "update", changed_by=admin, changes={key: ("(image)" if key == SIGNATURE_KEY else old, "(image)" if key == SIGNATURE_KEY else value)})
    db.commit()
    return read_invoice_settings(admin, db)
