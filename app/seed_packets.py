"""Supply stock (seed packets, medicines, fertilizers, other supplies), tracked batch by batch.

* Quantities come only from the movement log (receipt / usage / adjustment / write-off), in the batch's own unit
  (packets, bottles, bags ... whole numbers; kg, g, litre, ml ... decimals).
* Never touches plant stock, orders, invoices or delivery. Nothing is deducted when a plant order is placed.
* A purchase from a supplier with an amount becomes a supplier BILL (Unpaid, with the lot lines) and each line is received
  into its batch; the Bill is paid later in Accounting, Payments Out. (Older entries booked an Expense; those stay as they are.)
* Expired stock cannot be used as normal stock; an authorised admin can still use it, with a reason, recorded as an exception.
"""
from datetime import date, datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounting.models import Contact
from app.audit import record_admin_audit
from app.communications.models import SystemFlag
from app.database import get_db
from app.deps import get_current_admin
from app.models import Plant, Purchase
from app.seed_entries import CREATE, EDIT, VIEW
from app.seed_packet_models import SeedPacketAlertLog, SeedPacketBatch, SeedPacketMovement
from app.supply_inventory import (
    ALL_UNITS,
    DEFAULT_UNIT,
    EXPIRY_REQUIRED,
    FLAG_KEY,
    KIND_LABEL,
    KINDS,
    LOT_REQUIRED,
    MAX_MONEY,
    MAX_QTY,
    WHOLE_UNITS,
    batch_out,
    batch_remaining,
    batch_totals,
    clean_quantity,
    create_supply_bill,
    display_name,
    find_batch,
    norm,
    normalise_line,
    plant_names,
    receive_line,
    supplier_contact,
    warning_days,
)
from app.supply_models import PurchaseLine

router = APIRouter(prefix="/api/admin/stock/seed-packets", tags=["seed-packets"])


def _result_for(db: Session, batch: SeedPacketBatch, **extra) -> dict:
    out = batch_out(batch, batch_totals(db, [batch.id]), plant_names(db, [batch.plant_id]), date.today(), warning_days(db))
    out.update(extra)
    return out


# ------------------------------------------------------------------ what the form needs to know
@router.get("/meta", dependencies=[VIEW])
def meta():
    """The rules the entry forms follow (so the screens and the server always agree)."""
    return {
        "kinds": [{"key": k, "label": KIND_LABEL[k], "lot_required": k in LOT_REQUIRED, "expiry_required": k in EXPIRY_REQUIRED, "default_unit": DEFAULT_UNIT[k]} for k in KINDS],
        "units": [{"key": u, "whole": u in WHOLE_UNITS} for u in ALL_UNITS],
    }


@router.get("/suggestions", dependencies=[VIEW])
def suggestions(kind: str = Query("", max_length=20), q: str = Query("", max_length=80), db: Session = Depends(get_db)):
    """Item names and companies typed before, so they can be picked again instead of retyped (no separate item master)."""
    query = db.query(SeedPacketBatch)
    if kind in KINDS:
        query = query.filter(SeedPacketBatch.item_kind == kind)
    names, companies = {}, {}
    for b in query.order_by(SeedPacketBatch.id.desc()).limit(2000):
        n = display_name(b)
        if n and (not q.strip() or q.strip().lower() in n.lower()):
            names.setdefault(norm(n), n)
        if b.company and (not q.strip() or q.strip().lower() in b.company.lower()):
            companies.setdefault(norm(b.company), b.company)
    return {"names": sorted(names.values(), key=str.lower)[:50], "companies": sorted(companies.values(), key=str.lower)[:50]}


# ------------------------------------------------------------------ create / receive
class PacketIn(BaseModel):
    item_kind: Literal["seed_packet", "medicine", "fertilizer", "supply"] = "seed_packet"
    item_name: str = Field(default="", max_length=200)
    variety: str = Field(default="", max_length=150)  # older forms: the seed name
    plant_id: Optional[int] = None  # None = Unassigned / General stock
    company: str = Field(default="", max_length=150)
    supplier: str = Field(default="", max_length=150)
    supplier_contact_id: Optional[int] = None
    lot_number: str = Field(default="", max_length=80)
    batch_number: str = Field(default="", max_length=80)  # older forms: the lot number
    quantity: Optional[float] = Field(default=None, gt=0, le=MAX_QTY)
    packets: Optional[float] = Field(default=None, gt=0, le=MAX_QTY)  # older forms: the quantity
    quantity_unit: str = Field(default="", max_length=12)
    packet_size: Optional[float] = Field(default=None, gt=0, le=1_000_000)
    packet_unit: str = Field(default="", max_length=10)
    purchase_date: date
    manufacturing_date: Optional[date] = None
    expiry_date: Optional[date] = None
    unit_price: Optional[float] = Field(default=None, ge=0, le=MAX_MONEY)
    total_amount: Optional[float] = Field(default=None, ge=0, le=MAX_MONEY)
    invoice_number: str = Field(default="", max_length=80)  # the supplier's bill number
    storage_location: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=1000)
    attachment_url: str = Field(default="", max_length=300)
    paid_now: bool = False  # not supported any more: bills stay Unpaid until Payments Out
    merge_into_existing: bool = False  # same lot again: add to that lot instead of making a new one
    allow_duplicate_bill: bool = False
    duplicate_reason: str = Field(default="", max_length=500)
    request_id: str = Field(min_length=8, max_length=60)

    @model_validator(mode="after")
    def _aliases(self):
        if self.quantity is None:
            self.quantity = self.packets
        if not self.lot_number:
            self.lot_number = self.batch_number
        if not self.item_name:
            self.item_name = self.variety
        return self


@router.post("", status_code=201, dependencies=[CREATE])
def create_packet(p: PacketIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    # the same form sent twice gives back the same result and changes nothing
    done_bill = db.query(Purchase).filter(Purchase.request_id == p.request_id).first()
    if done_bill:
        line = db.query(PurchaseLine).filter(PurchaseLine.purchase_id == done_bill.id).order_by(PurchaseLine.line_no).first()
        batch = db.query(SeedPacketBatch).filter(SeedPacketBatch.id == line.batch_id).first() if line else None
        if batch:
            return _result_for(db, batch, already_saved=True, purchase_id=done_bill.id, billed=True)
    done = db.query(SeedPacketBatch).filter(SeedPacketBatch.request_id == p.request_id).first() or db.query(SeedPacketMovement).filter(SeedPacketMovement.request_id == p.request_id).first()
    if done:
        batch = done if isinstance(done, SeedPacketBatch) else db.query(SeedPacketBatch).filter(SeedPacketBatch.id == done.batch_id).first()
        return _result_for(db, batch, already_saved=True, billed=False)
    if p.paid_now:
        raise HTTPException(status_code=400, detail="A purchase stays Unpaid until you record the payment in Accounting, Payments Out.")
    if p.quantity is None:
        raise HTTPException(status_code=400, detail="Write the quantity received")
    if p.purchase_date > date.today() + timedelta(days=1):
        raise HTTPException(status_code=400, detail="Purchase date is in the future")
    spec = normalise_line(db, {
        "item_kind": p.item_kind, "item_name": p.item_name, "plant_id": p.plant_id, "company": p.company, "lot_number": p.lot_number, "quantity": p.quantity,
        "unit": p.quantity_unit or DEFAULT_UNIT[p.item_kind], "unit_cost": p.unit_price, "total_cost": p.total_amount, "mfg_date": p.manufacturing_date, "expiry_date": p.expiry_date,
        "packet_size": p.packet_size, "packet_unit": p.packet_unit, "storage_location": p.storage_location, "notes": p.notes,
    }, p.purchase_date, label="This entry")
    total = spec["total_cost"] or 0

    contact = None
    if p.supplier_contact_id is not None:
        contact = db.query(Contact).filter(Contact.id == p.supplier_contact_id).first()
        if not contact or contact.contact_type not in ("supplier", "both"):
            raise HTTPException(status_code=400, detail="Choose a supplier from the supplier list")
    elif p.supplier.strip() and total > 0:
        contact = supplier_contact(db, p.supplier, admin)  # an existing supplier of that name, or a new supplier contact

    try:
        if contact is not None and total > 0:
            purchase = create_supply_bill(
                db, contact=contact, bill_number=p.invoice_number, fallback_number="", purchase_date=p.purchase_date, lines=[spec], admin=admin, request_id=p.request_id,
                notes=p.notes, override_duplicate=p.allow_duplicate_bill, override_reason=p.duplicate_reason, allow_merge=p.merge_into_existing,
            )
            line = db.query(PurchaseLine).filter(PurchaseLine.purchase_id == purchase.id).order_by(PurchaseLine.line_no).first()
            batch = db.query(SeedPacketBatch).filter(SeedPacketBatch.id == line.batch_id).first()
            merged, purchase_id, billed = db.query(SeedPacketMovement).filter(SeedPacketMovement.batch_id == batch.id, SeedPacketMovement.movement_type == "RECEIPT").count() > 1, purchase.id, True
        else:
            # no supplier account (or no amount): the stock is received, nothing is booked in Accounting
            batch, _m, merged = receive_line(db, spec=spec, purchase_date=p.purchase_date, supplier_text=(contact.name if contact else p.supplier.strip()), bill_number=p.invoice_number.strip(),
                                             admin=admin, request_id=p.request_id, allow_merge=p.merge_into_existing)
            purchase_id, billed = None, False
        batch.attachment_url = batch.attachment_url or p.attachment_url.strip()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This entry was just saved. Refresh the list.")
    record_admin_audit(admin, "seed_packet_received", {"batch": batch.id, "quantity": spec["quantity"], "kind": spec["item_kind"], "purchase": purchase_id})
    return _result_for(db, batch, already_saved=False, merged=merged, purchase_id=purchase_id, billed=billed)


# ------------------------------------------------------------------ inventory / detail / history
def _search(query, db: Session, q: str):
    like = f"%{q.strip()}%"
    names = [i for (i,) in db.query(Plant.id).filter(Plant.name.ilike(like))]
    return query.filter(SeedPacketBatch.variety.ilike(like) | SeedPacketBatch.item_name.ilike(like) | SeedPacketBatch.company.ilike(like) | SeedPacketBatch.batch_number.ilike(like)
                        | SeedPacketBatch.supplier.ilike(like) | SeedPacketBatch.record_no.ilike(like) | SeedPacketBatch.plant_id.in_(names or [0]))


@router.get("", dependencies=[VIEW])
def inventory(
    q: str = Query("", max_length=80),
    plant_id: Optional[int] = None,
    kind: str = Query("", max_length=20),
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
    if kind in KINDS:
        query = query.filter(SeedPacketBatch.item_kind == kind)
    if company.strip():
        query = query.filter(SeedPacketBatch.company.ilike(f"%{company.strip()}%"))
    if supplier.strip():
        query = query.filter(SeedPacketBatch.supplier.ilike(f"%{supplier.strip()}%"))
    if batch.strip():
        query = query.filter(SeedPacketBatch.batch_number.ilike(f"%{batch.strip()}%"))
    if q.strip():
        query = _search(query, db, q)
    items = query.order_by(SeedPacketBatch.expiry_date.is_(None), SeedPacketBatch.expiry_date.asc(), SeedPacketBatch.id.desc()).limit(1000).all()
    totals = batch_totals(db, [b.id for b in items])
    names = plant_names(db, [b.plant_id for b in items])
    periods, today = warning_days(db), date.today()
    rows = [batch_out(b, totals, names, today, periods) for b in items]
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
        "totals": {"batches": len(live), "remaining": round(sum(r["remaining"] for r in live), 3), "expiring_soon": sum(1 for r in live if r["status"] == "Expiring soon"), "expired": sum(1 for r in live if r["status"] == "Expired")},
    }


@router.get("/alerts", dependencies=[VIEW])
def alerts(db: Session = Depends(get_db)):
    """Batches that still hold stock and are expiring or expired, worked out from today's date.
    Each batch/period is logged the first time it is seen, so it is only announced once (`is_new`)."""
    periods, today = warning_days(db), date.today()
    batches = db.query(SeedPacketBatch).filter(SeedPacketBatch.expiry_date.isnot(None), SeedPacketBatch.expiry_date <= today + timedelta(days=max(periods))).order_by(SeedPacketBatch.expiry_date).all()
    totals = batch_totals(db, [b.id for b in batches])
    names = plant_names(db, [b.plant_id for b in batches])
    out = []
    for b in batches:
        row = batch_out(b, totals, names, today, periods)
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


def movement_rows(db: Session, rows) -> list[dict]:
    names = plant_names(db, [b.plant_id for _, b in rows])
    return [{"id": m.id, "at": m.created_at.isoformat() + "Z", "type": m.movement_type, "quantity": m.quantity, "unit": b.quantity_unit or "packets", "reason": m.reason or "", "detail": m.detail or "",
             "is_exception": m.is_exception, "by": m.performed_by, "batch_id": b.id, "record_no": b.record_no, "item_kind": b.item_kind or "seed_packet", "item_name": display_name(b),
             "plant_name": names.get(b.plant_id, "") if b.plant_id else "Unassigned / General stock", "variety": b.variety or "", "company": b.company or "", "supplier": m.supplier or b.supplier or "",
             "batch_number": b.batch_number or "", "total_amount": m.total_amount, "invoice_number": m.invoice_number or "", "purchase_id": m.purchase_id, "expense_id": m.expense_id,
             "purchase_date": b.purchase_date.isoformat() if m.movement_type == "RECEIPT" else None, "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None} for m, b in rows]


@router.get("/history", dependencies=[VIEW])
def history(batch_id: Optional[int] = None, q: str = Query("", max_length=80), limit: int = Query(300, ge=1, le=1000), db: Session = Depends(get_db)):
    query = db.query(SeedPacketMovement, SeedPacketBatch).join(SeedPacketBatch, SeedPacketBatch.id == SeedPacketMovement.batch_id)
    if batch_id:
        query = query.filter(SeedPacketMovement.batch_id == batch_id)
    if q.strip():
        like = f"%{q.strip()}%"
        names = [i for (i,) in db.query(Plant.id).filter(Plant.name.ilike(like))]
        query = query.filter(SeedPacketBatch.batch_number.ilike(like) | SeedPacketBatch.company.ilike(like) | SeedPacketBatch.variety.ilike(like) | SeedPacketBatch.item_name.ilike(like)
                             | SeedPacketMovement.reason.ilike(like) | SeedPacketMovement.performed_by.ilike(like) | SeedPacketMovement.invoice_number.ilike(like)
                             | SeedPacketBatch.plant_id.in_(names or [0]))
    return movement_rows(db, query.order_by(SeedPacketMovement.id.desc()).limit(limit).all())


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
        raise HTTPException(status_code=404, detail="Stock batch not found")
    return _result_for(db, b)


# ------------------------------------------------------------------ use / adjust / correct / write off
def _batch(db: Session, batch_id: int) -> SeedPacketBatch:
    b = db.query(SeedPacketBatch).filter(SeedPacketBatch.id == batch_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Stock batch not found")
    return b


def _result(db: Session, b: SeedPacketBatch, already: bool = False) -> dict:
    return _result_for(db, b, already_saved=already)


def _seen(db: Session, request_id: str) -> Optional[SeedPacketMovement]:
    return db.query(SeedPacketMovement).filter(SeedPacketMovement.request_id == request_id).first()


def _add_move(db: Session, **kw) -> Optional[SeedPacketMovement]:
    """Saves one movement. Returns None for a repeated request_id. If, once saved, the batch would hold
    less than 0 (two people took the last stock at the same moment), nothing is kept and a 400 is raised:
    the count can never go negative."""
    m = SeedPacketMovement(**kw)
    db.add(m)
    try:
        db.flush()
        left = batch_remaining(db, kw["batch_id"])
        if left < 0:
            db.rollback()
            raise HTTPException(status_code=400, detail="Someone else just used this stock. Refresh and check how much is left.")
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return m


class UseIn(BaseModel):
    quantity: float = Field(gt=0, le=MAX_QTY)
    reason: str = Field(default="Used for sowing", max_length=500)
    allow_expired: bool = False
    request_id: str = Field(min_length=8, max_length=60)


@router.post("/{batch_id}/use", dependencies=[EDIT])
def use_packets(batch_id: int, p: UseIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    b = _batch(db, batch_id)
    if _seen(db, p.request_id):
        return _result(db, b, True)
    unit = b.quantity_unit or "packets"
    qty = clean_quantity(p.quantity, unit, "Quantity used")
    remaining = batch_remaining(db, b.id)
    if qty > remaining + 1e-9:
        raise HTTPException(status_code=400, detail=f"Only {remaining:g} {unit} are left in this lot")
    expired = b.expiry_date is not None and b.expiry_date < date.today()
    if expired and not p.allow_expired:
        raise HTTPException(status_code=400, detail=f"This lot expired on {b.expiry_date.isoformat()}. Expired stock is not normal stock. To use it anyway, tick the exception box and give a reason.")
    if expired and len((p.reason or "").strip()) < 5:
        raise HTTPException(status_code=400, detail="Write the reason for using expired stock (at least 5 letters)")
    m = _add_move(db, batch_id=b.id, movement_type="USAGE", quantity=-qty, reason=(p.reason or "").strip(), is_exception=expired, request_id=p.request_id, performed_by=admin,
                  detail=f"Used although expired on {b.expiry_date.isoformat()}" if expired else "")
    if m is None:
        return _result(db, b, True)
    record_admin_audit(admin, "seed_packet_used", {"batch": b.id, "quantity": qty, "expired_exception": expired})
    return _result(db, b)


class AdjustIn(BaseModel):
    new_remaining: float = Field(ge=0, le=MAX_QTY)  # the real count after counting the stock
    reason: str = Field(min_length=3, max_length=500)
    request_id: str = Field(min_length=8, max_length=60)


@router.post("/{batch_id}/adjust", dependencies=[EDIT])
def adjust_packets(batch_id: int, p: AdjustIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    b = _batch(db, batch_id)
    if _seen(db, p.request_id):
        return _result(db, b, True)
    unit = b.quantity_unit or "packets"
    new = round(float(p.new_remaining), 3)
    if unit in WHOLE_UNITS and abs(new - round(new)) > 1e-9:
        raise HTTPException(status_code=400, detail=f"The count for {unit} must be a whole number")
    remaining = batch_remaining(db, b.id)
    delta = round(new - remaining, 3)
    if delta == 0:
        raise HTTPException(status_code=400, detail="The count is already the same")
    m = _add_move(db, batch_id=b.id, movement_type="ADJUSTMENT", quantity=delta, reason=p.reason.strip(), detail=f"count {remaining:g} -> {new:g}", request_id=p.request_id, performed_by=admin)
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


def _d(v: Optional[date]) -> str:
    return v.isoformat() if v else "-"


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
        changes.append(f"expiry {_d(b.expiry_date)} -> {_d(p.expiry_date)}")
        b.expiry_date = p.expiry_date
    if p.manufacturing_date is not None and p.manufacturing_date != b.manufacturing_date:
        changes.append(f"manufactured {_d(b.manufacturing_date)} -> {_d(p.manufacturing_date)}")
        b.manufacturing_date = p.manufacturing_date
    if p.batch_number is not None and p.batch_number.strip() != b.batch_number:
        changes.append(f"lot number {b.batch_number} -> {p.batch_number.strip()}")
        b.batch_number = p.batch_number.strip()
    if p.storage_location is not None and p.storage_location.strip() != (b.storage_location or ""):
        changes.append(f"storage {b.storage_location or '-'} -> {p.storage_location.strip()}")
        b.storage_location = p.storage_location.strip()
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing was changed")
    if p.batch_number is not None:
        spec = {"item_kind": b.item_kind or "seed_packet", "plant_id": b.plant_id, "item_name": display_name(b), "company": b.company or "", "lot_number": b.batch_number, "expiry_date": b.expiry_date}
        db.flush()
        clash = find_batch(db, spec)
        if clash is not None and clash.id != b.id:
            db.rollback()
            raise HTTPException(status_code=409, detail=f"Lot {b.batch_number} of this item already exists ({clash.record_no}). Two lots cannot share a lot number.")
    if b.manufacturing_date and b.expiry_date and b.manufacturing_date > b.expiry_date:
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
    """Removes the stock that is left (expired / discarded). Recorded, never deleted."""
    b = _batch(db, batch_id)
    if _seen(db, p.request_id):
        return _result(db, b, True)
    remaining = batch_remaining(db, b.id)
    if remaining <= 0:
        raise HTTPException(status_code=400, detail="Nothing is left in this lot")
    m = _add_move(db, batch_id=b.id, movement_type="EXPIRED_WRITEOFF", quantity=-remaining, reason=p.reason.strip(),
                  detail=f"expiry {_d(b.expiry_date)}", request_id=p.request_id, performed_by=admin)
    if m is None:
        return _result(db, b, True)
    record_admin_audit(admin, "seed_packet_written_off", {"batch": b.id, "quantity": remaining})
    return _result(db, b)
