"""Public, login-free invoice PDF link for WhatsApp.

The link carries an HMAC-signed token (invoice id + signature made with the
server's secret), so it can't be guessed or edited to point at another
invoice. Nothing is stored: the PDF is built from the invoice's data every
time the link is opened, the same code path as the admin "View PDF" button.
"""
import base64
import hashlib
import hmac
import os
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.accounting.models import Invoice
from app.accounting.pdf_builder import build_invoice_pdf_bytes
from app.database import get_db
from app.settings_helper import get_settings

router = APIRouter(tags=["public-invoice-pdf"])

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://shreeaaijihightechnursery.in").rstrip("/")


def _sign(invoice_id: int) -> str:
    key = os.environ.get("SESSION_SECRET_KEY", "").encode()
    return hmac.new(key, f"invoice-pdf:{invoice_id}".encode(), hashlib.sha256).hexdigest()[:32]


def invoice_pdf_token(invoice_id: int) -> str:
    return f"{base64.urlsafe_b64encode(str(invoice_id).encode()).decode().rstrip('=')}.{_sign(invoice_id)}"


def invoice_pdf_url(invoice_id: int) -> str:
    return f"{PUBLIC_BASE_URL}/api/public/invoice/{invoice_pdf_token(invoice_id)}.pdf"


def _invoice_id_from_token(token: str) -> int | None:
    try:
        raw, sig = token.split(".", 1)
        invoice_id = int(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode())
    except Exception:
        return None
    return invoice_id if hmac.compare_digest(sig, _sign(invoice_id)) else None


@router.get("/api/public/invoice/{token}.pdf")
def public_invoice_pdf(token: str, db: Session = Depends(get_db)):
    invoice_id = _invoice_id_from_token(token)
    invoice = (
        db.query(Invoice).options(joinedload(Invoice.contact), joinedload(Invoice.items)).filter(Invoice.id == invoice_id).first()
        if invoice_id else None
    )
    if not invoice or invoice.status == "Voided":
        raise HTTPException(status_code=404, detail="Invoice not found")
    return StreamingResponse(
        BytesIO(build_invoice_pdf_bytes(invoice, get_settings(db))),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{invoice.invoice_number}.pdf"', "Cache-Control": "private, no-store", "X-Robots-Tag": "noindex"},
    )
