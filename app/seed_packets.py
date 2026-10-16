"""Seed Packet Entry: packets bought from seed companies, tracked batch by batch.

* Quantities come only from the movement log (receipt / usage / adjustment / write-off).
* Never touches plant stock, orders, invoices or delivery. Packets are NOT deducted when a plant
  order is placed.
* A purchase with an amount is booked as an accounting Expense ("Seed Packets") in the same save,
  so nothing has to be entered again in Accounting.
* Expired packets cannot be used as normal stock; an authorised admin can still use them, with a
  reason, and that is recorded as an exception.
"""
from datetime import date, datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounting.audit import record_change
from app.accounting.models import Contact, Expense, PaymentOut
from app.audit import record_admin_audit
from app.communications.models import SystemFlag
from app.database import get_db
from app.deps import get_current_admin
from app.models import Plant
from app.seed_entries import CREATE, EDIT, VIEW
from app.seed_packet_models import SeedPacketAlertLog, SeedPacketBatch, SeedPacketMovement

router = APIRouter(prefix="/api/admin/stock/seed-packets", tags=["seed-packets"])
MAX_PACKETS = 1_000_000
MAX_MONEY = 1_000_000_000
UNITS = ("g", "kg", "mg", "seeds", "pcs")
METHODS = ("Cash", "Bank", "UPI", "Card", "Online", "Other")
FLAG_KEY = "seed_packet_warning_days"
DEFAULT_DAYS = [90, 30, 15, 7]
EXPENSE_CATEGORY = "Seed Packets"


# ------------------------------------------------------------------ helpers
def warning_days(db: Session) -> list[int]:
    row = db.query(SystemFlag).filter(SystemFlag.key == FLAG_KEY).first()
    try:
        days = sorted({int(x) for x in (row.value if row else "").split(",") if x.strip()}, reverse=True)
    except ValueError:
        days = []
    return [d for d in days if 0 < d <= 3650] or DEFAULT_DAYS


def _bucket(days_left: int, periods: list[int]) -> Optional[int]:
    """The tightest warning period the batch has already entered (e.g. 20 days left -> 30)."""
    hit = [p for p in periods if days_left <= p]
    return min(hit) if hit else None


def _totals(db: Session, batch_ids: list[int]) -> dict:
    out = {i: {"received": 0, "used": 0, "adjusted": 0, "written_off": 0, "remaining": 0} for i in batch_ids}
    if not batch_ids:
        return out
    for bid, mtype, qty in db.query(SeedPacketMovement.batch_id, SeedPacketMovement.movement_type, func.sum(SeedPacketMovement.quantity)).filter(
        SeedPacketMovement.batch_id.in_(batch_ids)).group_by(SeedPacketMovement.batch_id, SeedPacketMovement.movement_type):
        t, q = out[bid], int(qty or 0)
        if mtype == "RECEIPT":
            t["received"] += q
        elif mtype == "USAGE":
            t["used"] += -q
        elif mtype == "EXPIRED_WRITEOFF":
            t["written_off"] += -q
        else:
            t["adjusted"] += q
        t["remaining"] += q
    return out


def _remaining(db: Session, batch_id: int) -> int:
    return int(db.query(func.coalesce(func.sum(SeedPacketMovement.quantity), 0)).filter(SeedPacketMovement.batch_id == batch_id).scalar() or 0)


def _status(batch: SeedPacketBatch, remaining: int, today: date, periods: list[int]) -> tuple[str, int, Optional[int]]:
    days = (batch.expiry_date - today).days
    if remaining <= 0:
        return "Empty", days, None
    if days < 0:
        return "Expired", days, None
    b = _bucket(days, periods)
    return ("Expiring soon" if b else "OK"), days, b


def _out(db: Session, batch: SeedPacketBatch, totals: dict, plant_names: dict, today: date, periods: list[int]) -> dict:
    t = totals.get(batch.id) or {"received": 0, "used": 0, "adjusted": 0, "written_off": 0, "remaining": 0}
    status, days, bucket = _status(batch, t["remaining"], today, periods)
    return {
        "id": batch.id, "record_no": batch.record_no, "plant_id": batch.plant_id, "plant_name": plant_names.get(batch.plant_id, f"#{batch.plant_id}"),
        "variety": batch.variety or "", "company": batch.company or "", "supplier": batch.supplier or "", "batch_number": batch.batch_number,
        "packet_size": batch.packet_size, "packet_unit": batch.packet_unit or "", "purchase_date": batch.purchase_date.isoformat(),
        "manufacturing_date": batch.manufacturing_date.isoformat() if batch.manufacturing_date else None, "expiry_date": batch.expiry_date.isoformat(),
        "storage_location": batch.storage_location or "", "notes": batch.notes or "", "attachment_url": batch.attachment_url or "",
        "received": t["received"], "used": t["used"], "adjusted": t["adjusted"], "written_off": t["written_off"], "remaining": t["remaining"],
        "status": status, "days_left": days, "warning_period": bucket, "created_by": batch.created_by,
    }


def _plant_names(db: Session, ids) -> dict:
    return {i: n for i, n in db.query(Plant.id, Plant.name).filter(Plant.id.in_(set(ids) or {0}))}


def _supplier_contact(db: Session, name: str, admin: str) -> Optional[Contact]:
    name = (name or "").strip()
    if not name:
        return None
    c = db.query(Contact).filter(func.lower(Contact.name) == name.lower(), Contact.contact_type.in_(("supplier", "both"))).first()
    if c:
        return c
    c = Contact(contact_type="supplier", name=name[:150], source="offline", created_by=admin)
    db.add(c)
    db.flush()
    record_change(db, "accounting_contacts", c.id, "create", changed_by=admin)
    return c


def _book_expense(db: Session, batch: SeedPacketBatch, move: SeedPacketMovement, plant_name: str, packets: int, purchase_date: date,
                  paid_now: bool, method: str, admin: str) -> Optional[Expense]:
    """The purchase becomes an accounting Expense by itself (and, if paid now, a payment)."""
    total = move.total_amount or 0
    if total <= 0:
        return None
    contact = _supplier_contact(db, move.supplier, admin)
    desc = f"Seed packets: {plant_name}{' ' + batch.variety if batch.variety else ''}, {batch.company or 'seed company'}, batch {batch.batch_number} x{packets}"[:200]
    exp = Expense(
        category=EXPENSE_CATEGORY, contact_id=contact.id if contact else None, description=desc, expense_date=datetime.combine(purchase_date, datetime.min.time()),
        amount=round(total, 2), tax_amount=0, total_amount=round(total, 2), amount_paid=0, balance_due=round(total, 2), status="Unpaid",
        reference=move.invoice_number or "", notes=f"Auto-created from Seed Packet Entry {batch.record_no}", source="offline", source_id=f"seedpkt:{move.id}", created_by=admin,
    )
    db.add(exp)
    db.flush()
    record_change(db, "accounting_expenses", exp.id, "create", changed_by=admin)
    if paid_now:
        db.add(PaymentOut(expense_id=exp.id, contact_id=exp.contact_id, amount=exp.total_amount, method=method if method in METHODS else "Cash",
                          payment_date=exp.expense_date, reference=move.invoice_number or "", notes="Paid when the packets were entered", source="offline", recorded_by=admin))
        exp.amount_paid, exp.balance_due, exp.status = exp.total_amount, 0, "Paid"
        record_change(db, "accounting_expenses", exp.id, "update", changed_by=admin, changes={"status": ("Unpaid", "Paid")})
    move.expense_id = exp.id
    return exp


# ------------------------------------------------------------------ create / receive
class PacketIn(BaseModel):
    plant_id: int
    variety: str = Field(default="", max_length=150)
    company: str = Field(min_length=1, max_length=150)
    supplier: str = Field(default="", max_length=150)
    batch_number: str = Field(min_length=1, max_length=80)
    packets: int = Field(gt=0, le=MAX_PACKETS)
    packet_size: Optional[float] = Field(default=None, gt=0, le=1_000_000)
    packet_unit: str = "g"
    purchase_date: date
    manufacturing_date: Optional[date] = None
    expiry_date: date
    unit_price: Optional[float] = Field(default=None, ge=0, le=MAX_MONEY)
    total_amount: Optional[float] = Field(default=None, ge=0, le=MAX_MONEY)
    invoice_number: str = Field(default="", max_length=80)
    storage_location: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=1000)
    attachment_url: str = Field(default="", max_length=300)
    paid_now: bool = False
    paid_method: str = "Cash"
    merge_into_existing: bool = False  # same batch number again: add to that batch instead of making a new one
    request_id: str = Field(min_length=8, max_length=60)


@router.post("", status_code=201, dependencies=[CREATE])
def create_packet(p: PacketIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    done = db.query(SeedPacketBatch).filter(SeedPacketBatch.request_id == p.request_id).first() or (
        db.query(SeedPacketMovement).filter(SeedPacketMovement.request_id == p.request_id).first())
    if done:
        bid = done.id if isinstance(done, SeedPacketBatch) else done.batch_id
        batch = db.query(SeedPacketBatch).filter(SeedPacketBatch.id == bid).first()
        periods = warning_days(db)
        return {**_out(db, batch, _totals(db, [bid]), _plant_names(db, [batch.plant_id]), date.today(), periods), "already_saved": True}
    plant = db.query(Plant).filter(Plant.id == p.plant_id).first()
    if not plant:
        raise HTTPException(status_code=400, detail="Choose a plant from the list")
    if p.packet_unit not in UNITS:
        raise HTTPException(status_code=400, detail="Unknown packet unit")
    if not 2000 <= p.expiry_date.year <= 2100:
        raise HTTPException(status_code=400, detail="Expiry date is not a valid date")
    if p.expiry_date < p.purchase_date:
        raise HTTPException(status_code=400, detail="Expiry date is before the purchase date. Check the date on the packet.")
    if p.manufacturing_date and p.manufacturing_date > p.expiry_date:
        raise HTTPException(status_code=400, detail="Manufacturing date is after the expiry date")
    if p.purchase_date > date.today() + timedelta(days=1):
        raise HTTPException(status_code=400, detail="Purchase date is in the future")
    total = p.total_amount
    unit = p.unit_price
    if total is None and unit is not None:
        total = round(unit * p.packets, 2)
    if unit is None and total is not None:
        unit = round(total / p.packets, 4)
    batch_no = p.batch_number.strip()

    same = [b for b in db.query(SeedPacketBatch).filter(SeedPacketBatch.plant_id == p.plant_id, func.lower(SeedPacketBatch.batch_number) == batch_no.lower())
            if (b.company or "").strip().lower() == p.company.strip().lower() and (b.variety or "").strip().lower() == p.variety.strip().lower()]
    batch = None
    if same:
        existing = same[0]
        if existing.expiry_date != p.expiry_date:
            raise HTTPException(status_code=409, detail=f"Batch {batch_no} of this packet already exists with expiry {existing.expiry_date.isoformat()}. A batch number has one expiry date. Check the packet, or use a different batch number.")
        if not p.merge_into_existing:
            rem = _remaining(db, existing.id)
            raise HTTPException(status_code=409, detail=f"BATCH_EXISTS: Batch {batch_no} of this packet is already recorded ({existing.record_no}, {rem} packets left). Add these packets to that batch?")
        batch = existing
    created_new = batch is None
    if created_new:
        batch = SeedPacketBatch(plant_id=p.plant_id, variety=p.variety.strip(), company=p.company.strip(), supplier=p.supplier.strip(), batch_number=batch_no, packet_size=p.packet_size,
                                packet_unit=p.packet_unit, purchase_date=p.purchase_date, manufacturing_date=p.manufacturing_date, expiry_date=p.expiry_date,
                                storage_location=p.storage_location.strip(), notes=p.notes.strip(), attachment_url=p.attachment_url.strip(), request_id=p.request_id, created_by=admin)
        db.add(batch)
        db.flush()
        batch.record_no = f"SP-{batch.id}"
    move = SeedPacketMovement(batch_id=batch.id, movement_type="RECEIPT", quantity=p.packets, reason="Packets received" + ("" if created_new else " (added to existing batch)"),
                              unit_price=unit, total_amount=total, invoice_number=p.invoice_number.strip(), supplier=p.supplier.strip(), request_id=None if created_new else p.request_id, performed_by=admin)
    db.add(move)
    try:
        db.flush()
        _book_expense(db, batch, move, plant.name, p.packets, p.purchase_date, p.paid_now, p.paid_method, admin)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This entry was just saved. Refresh the list.")
    record_admin_audit(admin, "seed_packet_received", {"batch": batch.id, "packets": p.packets})
    periods = warning_days(db)
    out = _out(db, batch, _totals(db, [batch.id]), {plant.id: plant.name}, date.today(), periods)
    out["already_saved"] = False
    out["merged"] = not created_new
    out["expense_id"] = move.expense_id
    return out


# ------------------------------------------------------------------ inventory / detail / history
@router.get("", dependencies=[VIEW])
def inventory(
    q: str = Query("", max_length=80),
    plant_id: Optional[int] = None,
    company: str = Query("", max_length=150),
    supplier: str = Query("", max_length=150),
    batch: str = Query("", max_length=80),
    expiry: Literal["all", "ok", "soon", "expired", "empty"] = "all",
    show_empty: bool = False,
    db: Session = Depends(get_db),
):
    query = db.query(SeedPacketBatch)
    if plant_id:
        query = query.filter(SeedPacketBatch.plant_id == plant_id)
    if company.strip():
        query = query.filter(SeedPacketBatch.company.ilike(f"%{company.strip()}%"))
    if supplier.strip():
        query = query.filter(SeedPacketBatch.supplier.ilike(f"%{supplier.strip()}%"))
    if batch.strip():
        query = query.filter(SeedPacketBatch.batch_number.ilike(f"%{batch.strip()}%"))
    if q.strip():
        like = f"%{q.strip()}%"
        names = [i for (i,) in db.query(Plant.id).filter(Plant.name.ilike(like))]
        query = query.filter(SeedPacketBatch.variety.ilike(like) | SeedPacketBatch.company.ilike(like) | SeedPacketBatch.batch_number.ilike(like) | SeedPacketBatch.supplier.ilike(like)
                             | SeedPacketBatch.record_no.ilike(like) | SeedPacketBatch.plant_id.in_(names or [0]))
    items = query.order_by(SeedPacketBatch.expiry_date.asc(), SeedPacketBatch.id.desc()).limit(1000).all()
    totals = _totals(db, [b.id for b in items])
    names = _plant_names(db, [b.plant_id for b in items])
    periods, today = warning_days(db), date.today()
    rows = [_out(db, b, totals, names, today, periods) for b in items]
    if expiry == "ok":
        rows = [r for r in rows if r["status"] == "OK"]
    elif expiry == "soon":
        rows = [r for r in rows if r["status"] == "Expiring soon"]
    elif expiry == "expired":
        rows = [r for r in rows if r["status"] == "Expired"]
    elif expiry == "empty":
        rows = [r for r in rows if r["status"] == "Empty"]
    elif not show_empty:
        rows = [r for r in rows if r["status"] != "Empty"]
    live = [r for r in rows if r["status"] != "Empty"]
    return {
        "items": rows, "warning_days": periods,
        "totals": {"batches": len(live), "remaining": sum(r["remaining"] for r in live), "expiring_soon": sum(1 for r in live if r["status"] == "Expiring soon"), "expired": sum(1 for r in live if r["status"] == "Expired")},
    }


@router.get("/alerts", dependencies=[VIEW])
def alerts(db: Session = Depends(get_db)):
    """Batches that still hold packets and are expiring or expired, worked out from today's date.
    Each batch/period is logged the first time it is seen, so it is only announced once (`is_new`)."""
    periods, today = warning_days(db), date.today()
    batches = db.query(SeedPacketBatch).filter(SeedPacketBatch.expiry_date <= today + timedelta(days=max(periods))).order_by(SeedPacketBatch.expiry_date).all()
    totals = _totals(db, [b.id for b in batches])
    names = _plant_names(db, [b.plant_id for b in batches])
    out = []
    for b in batches:
        row = _out(db, b, totals, names, today, periods)
        if row["status"] not in ("Expiring soon", "Expired"):
            continue
        key = "expired" if row["status"] == "Expired" else f"d{row['warning_period']}"
        is_new = False
        if not db.query(SeedPacketAlertLog.id).filter(SeedPacketAlertLog.batch_id == b.id, SeedPacketAlertLog.alert_key == key).first():
            try:
                db.add(SeedPacketAlertLog(batch_id=b.id, alert_key=key))
                db.commit()
                is_new = True
            except IntegrityError:
                db.rollback()
        row.update({"alert_key": key, "is_new": is_new, "level": "expired" if key == "expired" else ("critical" if (row["warning_period"] or 99) <= min(periods) or row["days_left"] <= 7 else "warning")})
        out.append(row)
    out.sort(key=lambda r: (r["status"] != "Expired", r["days_left"]))
    return {"items": out, "expired": sum(1 for r in out if r["status"] == "Expired"), "expiring": sum(1 for r in out if r["status"] != "Expired"), "warning_days": periods}


@router.get("/history", dependencies=[VIEW])
def history(batch_id: Optional[int] = None, q: str = Query("", max_length=80), limit: int = Query(300, ge=1, le=1000), db: Session = Depends(get_db)):
    query = db.query(SeedPacketMovement, SeedPacketBatch).join(SeedPacketBatch, SeedPacketBatch.id == SeedPacketMovement.batch_id)
    if batch_id:
        query = query.filter(SeedPacketMovement.batch_id == batch_id)
    if q.strip():
        like = f"%{q.strip()}%"
        names = [i for (i,) in db.query(Plant.id).filter(Plant.name.ilike(like))]
        query = query.filter(SeedPacketBatch.batch_number.ilike(like) | SeedPacketBatch.company.ilike(like) | SeedPacketBatch.variety.ilike(like) | SeedPacketMovement.reason.ilike(like)
                             | SeedPacketMovement.performed_by.ilike(like) | SeedPacketBatch.plant_id.in_(names or [0]))
    rows = query.order_by(SeedPacketMovement.id.desc()).limit(limit).all()
    names = _plant_names(db, [b.plant_id for _, b in rows])
    return [{"id": m.id, "at": m.created_at.isoformat() + "Z", "type": m.movement_type, "quantity": m.quantity, "reason": m.reason or "", "detail": m.detail or "", "is_exception": m.is_exception,
             "by": m.performed_by, "batch_id": b.id, "record_no": b.record_no, "plant_name": names.get(b.plant_id, ""), "variety": b.variety or "", "company": b.company or "",
             "batch_number": b.batch_number, "total_amount": m.total_amount, "invoice_number": m.invoice_number or "", "expense_id": m.expense_id} for m, b in rows]


class SettingsIn(BaseModel):
    warning_days: list[int] = Field(min_length=1, max_length=8)


@router.get("/settings", dependencies=[VIEW])
def get_settings_endpoint(db: Session = Depends(get_db)):
    return {"warning_days": warning_days(db)}


@router.put("/settings", dependencies=[EDIT])
def put_settings(payload: SettingsIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    days = sorted({d for d in payload.warning_days if 0 < d <= 3650}, reverse=True)
    if not days:
        raise HTTPException(status_code=400, detail="Give at least one warning period in days, like 90, 30, 15, 7")
    row = db.query(SystemFlag).filter(SystemFlag.key == FLAG_KEY).first()
    if not row:
        row = SystemFlag(key=FLAG_KEY)
        db.add(row)
    row.value, row.updated_by, row.updated_at = ",".join(str(d) for d in days), admin, datetime.utcnow()
    db.commit()
    record_admin_audit(admin, "seed_packet_warning_days", {"days": days})
    return {"warning_days": days}


@router.get("/{batch_id}", dependencies=[VIEW])
def detail(batch_id: int, db: Session = Depends(get_db)):
    b = db.query(SeedPacketBatch).filter(SeedPacketBatch.id == batch_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Packet batch not found")
    out = _out(db, b, _totals(db, [b.id]), _plant_names(db, [b.plant_id]), date.today(), warning_days(db))
    return out


# ------------------------------------------------------------------ use / adjust / correct / write off
def _batch(db: Session, batch_id: int) -> SeedPacketBatch:
    b = db.query(SeedPacketBatch).filter(SeedPacketBatch.id == batch_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Packet batch not found")
    return b


def _result(db: Session, b: SeedPacketBatch, already: bool = False) -> dict:
    return {**_out(db, b, _totals(db, [b.id]), _plant_names(db, [b.plant_id]), date.today(), warning_days(db)), "already_saved": already}


def _seen(db: Session, request_id: str) -> Optional[SeedPacketMovement]:
    return db.query(SeedPacketMovement).filter(SeedPacketMovement.request_id == request_id).first()


def _add_move(db: Session, **kw) -> Optional[SeedPacketMovement]:
    """Saves one movement. Returns None for a repeated request_id. If, once saved, the batch would hold
    fewer than 0 packets (two people took the last packets at the same moment), nothing is kept and a
    400 is raised: the count can never go negative."""
    m = SeedPacketMovement(**kw)
    db.add(m)
    try:
        db.flush()
        left = _remaining(db, kw["batch_id"])
        if left < 0:
            db.rollback()
            raise HTTPException(status_code=400, detail="Someone else just used these packets. Refresh and check how many are left.")
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return m


class UseIn(BaseModel):
    quantity: int = Field(gt=0, le=MAX_PACKETS)
    reason: str = Field(default="Used for sowing", max_length=500)
    allow_expired: bool = False
    request_id: str = Field(min_length=8, max_length=60)


@router.post("/{batch_id}/use", dependencies=[EDIT])
def use_packets(batch_id: int, p: UseIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    b = _batch(db, batch_id)
    if _seen(db, p.request_id):
        return _result(db, b, True)
    remaining = _remaining(db, b.id)
    if p.quantity > remaining:
        raise HTTPException(status_code=400, detail=f"Only {remaining} packets are left in this batch")
    expired = b.expiry_date < date.today()
    if expired and not p.allow_expired:
        raise HTTPException(status_code=400, detail=f"This batch expired on {b.expiry_date.isoformat()}. Expired packets are not normal stock. To use them anyway, tick the exception box and give a reason.")
    if expired and len((p.reason or "").strip()) < 5:
        raise HTTPException(status_code=400, detail="Write the reason for using expired packets (at least 5 letters)")
    m = _add_move(db, batch_id=b.id, movement_type="USAGE", quantity=-p.quantity, reason=(p.reason or "").strip(), is_exception=expired, request_id=p.request_id, performed_by=admin,
                  detail=f"Used although expired on {b.expiry_date.isoformat()}" if expired else "")
    if m is None:
        return _result(db, b, True)
    record_admin_audit(admin, "seed_packet_used", {"batch": b.id, "packets": p.quantity, "expired_exception": expired})
    return _result(db, b)


class AdjustIn(BaseModel):
    new_remaining: int = Field(ge=0, le=MAX_PACKETS)  # the real count after counting the packets
    reason: str = Field(min_length=3, max_length=500)
    request_id: str = Field(min_length=8, max_length=60)


@router.post("/{batch_id}/adjust", dependencies=[EDIT])
def adjust_packets(batch_id: int, p: AdjustIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    b = _batch(db, batch_id)
    if _seen(db, p.request_id):
        return _result(db, b, True)
    remaining = _remaining(db, b.id)
    delta = p.new_remaining - remaining
    if delta == 0:
        raise HTTPException(status_code=400, detail="The count is already the same")
    m = _add_move(db, batch_id=b.id, movement_type="ADJUSTMENT", quantity=delta, reason=p.reason.strip(), detail=f"count {remaining} -> {p.new_remaining}", request_id=p.request_id, performed_by=admin)
    if m is None:
        return _result(db, b, True)
    record_admin_audit(admin, "seed_packet_adjusted", {"batch": b.id, "delta": delta})
    return _result(db, b)


class CorrectIn(BaseModel):
    expiry_date: Optional[date] = None
    manufacturing_date: Optional[date] = None
    batch_number: Optional[str] = Field(default=None, min_length=1, max_length=80)
    storage_location: Optional[str] = Field(default=None, max_length=120)
    reason: str = Field(min_length=3, max_length=500)
    request_id: str = Field(min_length=8, max_length=60)


@router.post("/{batch_id}/correct", dependencies=[EDIT])
def correct_batch(batch_id: int, p: CorrectIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Fixing a typing mistake on the batch details. The old value is written into the history; nothing is overwritten silently."""
    b = _batch(db, batch_id)
    if _seen(db, p.request_id):
        return _result(db, b, True)
    changes = []
    if p.expiry_date is not None and p.expiry_date != b.expiry_date:
        if not 2000 <= p.expiry_date.year <= 2100:
            raise HTTPException(status_code=400, detail="Expiry date is not a valid date")
        changes.append(f"expiry {b.expiry_date.isoformat()} -> {p.expiry_date.isoformat()}")
        b.expiry_date = p.expiry_date
    if p.manufacturing_date is not None and p.manufacturing_date != b.manufacturing_date:
        changes.append(f"manufactured {b.manufacturing_date.isoformat() if b.manufacturing_date else '-'} -> {p.manufacturing_date.isoformat()}")
        b.manufacturing_date = p.manufacturing_date
    if p.batch_number is not None and p.batch_number.strip() != b.batch_number:
        changes.append(f"batch number {b.batch_number} -> {p.batch_number.strip()}")
        b.batch_number = p.batch_number.strip()
    if p.storage_location is not None and p.storage_location.strip() != (b.storage_location or ""):
        changes.append(f"storage {b.storage_location or '-'} -> {p.storage_location.strip()}")
        b.storage_location = p.storage_location.strip()
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing was changed")
    if p.batch_number is not None:
        clash = [o for o in db.query(SeedPacketBatch).filter(SeedPacketBatch.id != b.id, SeedPacketBatch.plant_id == b.plant_id, func.lower(SeedPacketBatch.batch_number) == b.batch_number.lower())
                 if (o.company or "").strip().lower() == (b.company or "").strip().lower() and (o.variety or "").strip().lower() == (b.variety or "").strip().lower()]
        if clash:
            db.rollback()
            raise HTTPException(status_code=409, detail=f"Batch {b.batch_number} of this packet already exists ({clash[0].record_no}). Two batches cannot share a batch number.")
    if b.manufacturing_date and b.manufacturing_date > b.expiry_date:
        db.rollback()
        raise HTTPException(status_code=400, detail="Manufacturing date is after the expiry date")
    m = SeedPacketMovement(batch_id=b.id, movement_type="CORRECTION", quantity=0, reason=p.reason.strip(), detail="; ".join(changes), request_id=p.request_id, performed_by=admin)
    db.add(m)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _result(db, b, True)
    record_admin_audit(admin, "seed_packet_corrected", {"batch": b.id, "changes": changes})
    return _result(db, b)


class WriteOffIn(BaseModel):
    reason: str = Field(default="Expired: discarded", min_length=3, max_length=500)
    request_id: str = Field(min_length=8, max_length=60)


@router.post("/{batch_id}/write-off", dependencies=[EDIT])
def write_off(batch_id: int, p: WriteOffIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Removes the packets that are left from stock (expired / discarded). Recorded, never deleted."""
    b = _batch(db, batch_id)
    if _seen(db, p.request_id):
        return _result(db, b, True)
    remaining = _remaining(db, b.id)
    if remaining <= 0:
        raise HTTPException(status_code=400, detail="No packets are left in this batch")
    m = _add_move(db, batch_id=b.id, movement_type="EXPIRED_WRITEOFF", quantity=-remaining, reason=p.reason.strip(),
                  detail=f"expiry {b.expiry_date.isoformat()}", request_id=p.request_id, performed_by=admin)
    if m is None:
        return _result(db, b, True)
    record_admin_audit(admin, "seed_packet_written_off", {"batch": b.id, "packets": remaining})
    return _result(db, b)
