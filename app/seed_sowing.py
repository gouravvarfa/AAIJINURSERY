"""Seed Consumption / Sowing Entry: seed packets used for sowing nursery trays.

Each sowing takes packets (partial packets allowed) out of one seed lot with a normal USAGE movement, so the lot's
remaining stock, the expiry rules and the stock history all stay in one place. Never touches plant stock."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_admin_audit
from app.database import get_db
from app.deps import get_current_admin
from app.models import Plant
from app.seed_entries import CREATE, VIEW
from app.seed_packet_models import SeedPacketBatch, SeedPacketMovement
from app.supply_inventory import batch_remaining, display_name, plant_names
from app.supply_models import SeedSowing

router = APIRouter(prefix="/api/admin/stock/seed-sowings", tags=["seed-sowing"])


class SowingIn(BaseModel):
    batch_id: int
    sowing_date: date
    packets_used: float = Field(gt=0, le=100000)
    trays_sown: int = Field(ge=1, le=1_000_000)
    nursery_batch_number: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=1000)
    allow_expired: bool = False
    expired_reason: str = Field(default="", max_length=500)
    request_id: str = Field(min_length=8, max_length=60)


def _row(s: SeedSowing, b: SeedPacketBatch, names: dict, after: Optional[float]) -> dict:
    return {"id": s.id, "record_no": f"SOW-{s.id}", "sowing_date": s.sowing_date.isoformat(), "batch_id": b.id, "lot_record_no": b.record_no, "item_name": display_name(b),
            "plant_name": names.get(b.plant_id, "") if b.plant_id else "", "company": b.company or "", "lot_number": b.batch_number or "", "packets_used": s.packets_used,
            "trays_sown": s.trays_sown, "nursery_batch_number": s.nursery_batch_number or "", "notes": s.notes or "", "remaining_after": after, "by": s.created_by,
            "at": s.created_at.isoformat() + "Z"}


def _after(db: Session, s: SeedSowing) -> Optional[float]:
    """Stock left in the lot right after this sowing."""
    if not s.usage_movement_id:
        return None
    total = 0.0
    for (q,) in db.query(SeedPacketMovement.quantity).filter(SeedPacketMovement.batch_id == s.batch_id, SeedPacketMovement.id <= s.usage_movement_id):
        total += q or 0
    return round(total, 3)


def _out(db: Session, s: SeedSowing) -> dict:
    b = db.query(SeedPacketBatch).filter(SeedPacketBatch.id == s.batch_id).first()
    return _row(s, b, plant_names(db, [b.plant_id]), _after(db, s))


@router.post("", dependencies=[CREATE], status_code=201)
def record_sowing(p: SowingIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    done = db.query(SeedSowing).filter(SeedSowing.request_id == p.request_id).first()
    if done:
        return {**_out(db, done), "already_saved": True}
    b = db.query(SeedPacketBatch).filter(SeedPacketBatch.id == p.batch_id).first()
    if not b or (b.item_kind or "seed_packet") != "seed_packet":
        raise HTTPException(status_code=404, detail="Seed lot not found")
    if p.sowing_date > date.today():
        raise HTTPException(status_code=400, detail="The sowing date cannot be in the future")
    used = round(float(p.packets_used), 3)
    left = batch_remaining(db, b.id)
    if used > left + 1e-9:
        raise HTTPException(status_code=400, detail=f"Only {left:g} {b.quantity_unit or 'packets'} are left in this lot")
    expired = b.expiry_date is not None and b.expiry_date < date.today()
    if expired and not p.allow_expired:
        raise HTTPException(status_code=400, detail=f"This lot expired on {b.expiry_date.isoformat()}. Expired seed is not normal stock. To sow it anyway, tick the exception box and give a reason.")
    if expired and len(p.expired_reason.strip()) < 5:
        raise HTTPException(status_code=400, detail="Write the reason for using expired seed (at least 5 letters)")
    s = SeedSowing(sowing_date=p.sowing_date, batch_id=b.id, packets_used=used, trays_sown=p.trays_sown, nursery_batch_number=p.nursery_batch_number.strip(), notes=p.notes.strip(),
                   request_id=p.request_id, created_by=admin)
    db.add(s)
    try:
        db.flush()
        reason = f"Sowing SOW-{s.id}: {p.trays_sown} trays" + (f", nursery batch {s.nursery_batch_number}" if s.nursery_batch_number else "") + (f". {p.expired_reason.strip()}" if expired else "")
        m = SeedPacketMovement(batch_id=b.id, movement_type="USAGE", quantity=-used, reason=reason, is_exception=expired, request_id=f"SOW:{p.request_id}", performed_by=admin,
                               detail=f"Used although expired on {b.expiry_date.isoformat()}" if expired else "")
        db.add(m)
        db.flush()
        if batch_remaining(db, b.id) < -1e-9:
            db.rollback()
            raise HTTPException(status_code=400, detail="Someone else just used this stock. Refresh and check how much is left.")
        s.usage_movement_id = m.id
        db.commit()
    except IntegrityError:
        db.rollback()
        done = db.query(SeedSowing).filter(SeedSowing.request_id == p.request_id).first()
        if done:
            return {**_out(db, done), "already_saved": True}
        raise
    record_admin_audit(admin, "seed_sowing_recorded", {"sowing": s.id, "batch": b.id, "packets": used, "trays": p.trays_sown, "expired_exception": expired})
    db.refresh(s)
    return {**_out(db, s), "already_saved": False}


@router.get("", dependencies=[VIEW])
def list_sowings(q: str = Query("", max_length=80), batch_id: Optional[int] = None, limit: int = Query(300, ge=1, le=1000), db: Session = Depends(get_db)):
    query = db.query(SeedSowing, SeedPacketBatch).join(SeedPacketBatch, SeedPacketBatch.id == SeedSowing.batch_id)
    if batch_id:
        query = query.filter(SeedSowing.batch_id == batch_id)
    if q.strip():
        like = f"%{q.strip()}%"
        plants = [i for (i,) in db.query(Plant.id).filter(Plant.name.ilike(like))]
        query = query.filter(SeedSowing.nursery_batch_number.ilike(like) | SeedSowing.notes.ilike(like) | SeedPacketBatch.batch_number.ilike(like) | SeedPacketBatch.item_name.ilike(like)
                             | SeedPacketBatch.variety.ilike(like) | SeedPacketBatch.company.ilike(like) | SeedPacketBatch.plant_id.in_(plants or [0]))
    rows = query.order_by(SeedSowing.sowing_date.desc(), SeedSowing.id.desc()).limit(limit).all()
    names = plant_names(db, [b.plant_id for _, b in rows])
    return [_row(s, b, names, _after(db, s)) for s, b in rows]
