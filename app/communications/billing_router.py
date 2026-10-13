"""Developer-only WhatsApp billing: top-ups you add + the REAL spend Meta
reports (pricing analytics), so the remaining balance is visible in the app
instead of in Meta Business Manager.

Meta has no API for the remaining prepaid balance, so
    balance = sum(top-ups) - spend since the first top-up day.
Spend is Meta's own billed cost, not an estimate."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import record_admin_audit
from app.communications.models import WhatsAppTopup
from app.database import get_db
from app.deps import get_current_developer

router = APIRouter(prefix="/api/admin/messaging-billing", tags=["messaging-billing"])

IST = timezone(timedelta(hours=5, minutes=30))
WABA_ID = os.environ.get("WHATSAPP_CLOUD_API_WABA_ID", "947747761265088")
LOW_BALANCE = 50.0
_cache: dict = {"at": 0.0, "key": None, "data": None}


class TopupIn(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    topup_date: datetime | None = None
    note: str = Field("", max_length=200)


def _ist_midnight(dt: datetime) -> datetime:
    return dt.astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)


def _fetch_spend(start: datetime, end: datetime) -> list[dict]:
    token = os.environ.get("WHATSAPP_CLOUD_API_TOKEN", "")
    if not token:
        raise RuntimeError("WHATSAPP_CLOUD_API_TOKEN is not set")
    version = os.environ.get("WHATSAPP_CLOUD_API_VERSION", "v20.0")
    dims = urllib.parse.quote(json.dumps(["PRICING_CATEGORY", "PRICING_TYPE"]))
    fields = f"pricing_analytics.start({int(start.timestamp())}).end({int(end.timestamp())}).granularity(DAILY).dimensions({dims})"
    req = urllib.request.Request(f"https://graph.facebook.com/{version}/{WABA_ID}?fields={fields}", headers={"Authorization": f"Bearer {token}"})
    try:
        body = json.loads(urllib.request.urlopen(req, timeout=20).read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise RuntimeError(f"Meta returned {e.code}: {msg[:160]}")
    points = []
    for block in (body.get("pricing_analytics") or {}).get("data", []):
        points.extend(block.get("data_points", []))
    return points


def _spend_since(start: datetime, refresh: bool) -> dict:
    now = datetime.now(IST)
    key = int(start.timestamp())
    if not refresh and _cache["data"] is not None and _cache["key"] == key and time.time() - _cache["at"] < 300:
        return _cache["data"]
    try:
        points = _fetch_spend(start, now)
    except Exception as exc:  # Meta down / token problem: show the last good numbers
        if _cache["data"] is not None and _cache["key"] == key:
            return {**_cache["data"], "error": f"Could not refresh from Meta ({exc}). Showing the last numbers."}
        return {"days": [], "by_category": [], "total": 0.0, "volume": 0, "fetched_at": None, "error": f"Could not reach Meta: {exc}"}
    days: dict[str, dict] = {}
    cats: dict[str, dict] = {}
    for p in points:
        d = datetime.fromtimestamp(p["start"], IST).strftime("%Y-%m-%d")
        row = days.setdefault(d, {"date": d, "utility": 0, "marketing": 0, "authentication": 0, "free": 0, "volume": 0, "cost": 0.0})
        cat, vol, cost = p.get("pricing_category", ""), int(p.get("volume", 0)), float(p.get("cost", 0) or 0)
        if p.get("pricing_type") == "FREE_CUSTOMER_SERVICE" or cat == "SERVICE":
            row["free"] += vol
        elif cat in ("UTILITY", "MARKETING", "AUTHENTICATION"):
            row[cat.lower()] += vol
        row["volume"] += vol
        row["cost"] = round(row["cost"] + cost, 4)
        c = cats.setdefault(cat or "OTHER", {"category": cat or "OTHER", "volume": 0, "cost": 0.0})
        c["volume"] += vol
        c["cost"] = round(c["cost"] + cost, 4)
    data = {
        "days": sorted(days.values(), key=lambda r: r["date"], reverse=True),
        "by_category": sorted(cats.values(), key=lambda r: -r["cost"]),
        "total": round(sum(r["cost"] for r in days.values()), 2),
        "volume": sum(r["volume"] for r in days.values()),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "error": "",
    }
    _cache.update(at=time.time(), key=key, data=data)
    return data


def _topup_out(t: WhatsAppTopup) -> dict:
    return {"id": t.id, "amount": t.amount, "topup_date": t.topup_date.isoformat() + "Z", "note": t.note or "", "added_by": t.added_by or ""}


@router.get("")
def billing(refresh: bool = False, admin: str = Depends(get_current_developer), db: Session = Depends(get_db)):
    topups = db.query(WhatsAppTopup).order_by(WhatsAppTopup.topup_date.desc(), WhatsAppTopup.id.desc()).all()
    total_in = round(sum(t.amount for t in topups), 2)
    spend = {"days": [], "by_category": [], "total": 0.0, "volume": 0, "fetched_at": None, "error": ""}
    if topups:
        first_utc = min(t.topup_date for t in topups).replace(tzinfo=timezone.utc)
        start = max(_ist_midnight(first_utc), _ist_midnight(datetime.now(IST) - timedelta(days=89)))
        spend = _spend_since(start, refresh)
    balance = round(total_in - spend["total"], 2)
    return {
        "currency": "INR",
        "total_added": total_in,
        "total_spent": spend["total"],
        "balance": balance,
        "low_balance": bool(topups) and balance < LOW_BALANCE,
        "low_balance_limit": LOW_BALANCE,
        "messages_billed_or_free": spend["volume"],
        "by_category": spend["by_category"],
        "days": spend["days"],
        "topups": [_topup_out(t) for t in topups],
        "fetched_at": spend["fetched_at"],
        "error": spend["error"],
        "note": "Spend is what Meta itself reports as billed. Meta's numbers can lag by a few hours.",
    }


@router.post("/topups", status_code=201)
def add_topup(payload: TopupIn, admin: str = Depends(get_current_developer), db: Session = Depends(get_db)):
    when = payload.topup_date or datetime.now(IST)
    when = when if when.tzinfo else when.replace(tzinfo=IST)
    row = WhatsAppTopup(amount=round(payload.amount, 2), topup_date=when.astimezone(timezone.utc).replace(tzinfo=None), note=payload.note.strip(), added_by=admin)
    db.add(row)
    db.commit()
    record_admin_audit(admin, "messaging_topup_added", {"amount": row.amount})
    _cache["data"] = None
    return _topup_out(row)


@router.delete("/topups/{topup_id}")
def delete_topup(topup_id: int, admin: str = Depends(get_current_developer), db: Session = Depends(get_db)):
    row = db.query(WhatsAppTopup).filter(WhatsAppTopup.id == topup_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Top-up not found")
    db.delete(row)
    db.commit()
    record_admin_audit(admin, "messaging_topup_deleted", {"amount": row.amount})
    _cache["data"] = None
    return {"ok": True}
