"""Walk-in seed entries: a customer hands seeds to the nursery to be grown for them.

Saved at once as "Seeds Given / Production Pending". Seeds are NOT ready plants and
nothing is taken from the nursery's own stock. Later the same record is updated with
the plants that were prepared:

    seeds given  =  prepared (for the customer) + extra usable + rejected + remaining

Extra usable plants go into ready stock through the normal ledger (reference
"SEEDENTRY:<id>:EXTRA:<request id>"), so a retried or double-clicked request can never
add them twice. For tray products the extra plants are added as whole trays; the
plants that do not fill a tray stay on the entry until the next update completes a tray.
"""
import re
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounting.models import Contact
from app.audit import record_admin_audit
from app.database import get_db
from app.deps import get_current_admin
from app.inventory import MAX_ORDER_QUANTITY, InsufficientStockError, adjust_stock
from app.models import AdminUser, Plant, PlantVariant
from app.permissions import check_permission
from app.production_models import SeedEntry, SeedEntryUpdate

router = APIRouter(prefix="/api/admin/stock/seed-entries", tags=["seed-entries"])
BIG = MAX_ORDER_QUANTITY * 100
LABEL = {"Pending": "Seeds Given / Production Pending", "In Progress": "In production", "Completed": "Completed"}


def _allow(action: str):
    """The stock team (module 'inventory') or anyone with 'products' access."""

    def dep(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)) -> str:
        user = db.query(AdminUser).filter(AdminUser.username == admin).first()
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if not (check_permission(db, user, "inventory", action) or check_permission(db, user, "products", action)):
            raise HTTPException(status_code=403, detail="You do not have permission to do this")
        return admin

    return dep


VIEW, CREATE, EDIT = Depends(_allow("VIEW")), Depends(_allow("CREATE")), Depends(_allow("EDIT"))


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")[-10:]


def _out(e: SeedEntry) -> dict:
    remaining = max(0, e.seeds_given - e.prepared_plants - e.extra_plants - e.rejected_plants)
    unit = "trays" if e.variant_id else "plants"
    loose = (e.extra_plants % e.tray_size) if e.tray_size else 0
    return {
        "id": e.id, "entry_number": e.entry_number, "status": e.status, "status_label": LABEL.get(e.status, e.status), "contact_id": e.contact_id, "customer_name": e.customer_name,
        "plant_id": e.plant_id, "variant_id": e.variant_id, "tray_size": e.tray_size, "unit": unit, "seeds_given": e.seeds_given, "prepared_plants": e.prepared_plants,
        "wanted_plants": e.wanted_plants, "customer_pending": max(e.wanted_plants - e.prepared_plants, 0) if e.wanted_plants else None,
        "handed_over": e.handed_over_at is not None, "handed_over_at": e.handed_over_at.isoformat() + "Z" if e.handed_over_at else None,
        "extra_plants": e.extra_plants, "extra_units_added": e.extra_units_added, "extra_loose": loose, "rejected_plants": e.rejected_plants, "remaining": remaining,
        "entry_date": e.entry_date.date().isoformat() if e.entry_date else None, "reference": e.reference or "", "notes": e.notes or "", "created_by": e.created_by,
        "completed_at": e.completed_at.isoformat() + "Z" if e.completed_at else None,
    }


def _with_plant(db: Session, items: list[SeedEntry]) -> list[dict]:
    names = {p.id: p.name for p in db.query(Plant.id, Plant.name).filter(Plant.id.in_({i.plant_id for i in items} or {0}))}
    out = []
    for e in items:
        row = _out(e)
        row["plant_name"] = names.get(e.plant_id, f"#{e.plant_id}") + (f" - tray of {e.tray_size}" if e.tray_size else "")
        out.append(row)
    return out


# ------------------------------------------------------------------ customers
@router.get("/customers", dependencies=[VIEW])
def customers(q: str = Query("", max_length=60), db: Session = Depends(get_db)):
    query = db.query(Contact).filter(Contact.contact_type == "customer", Contact.is_active.is_(True))
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(Contact.name.ilike(like) | Contact.phone.ilike(like))
    return [{"id": c.id, "name": c.name, "phone": c.phone or ""} for c in query.order_by(Contact.name).limit(40)]


class NewCustomer(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    phone: str = Field(default="", max_length=30)


class SeedEntryIn(BaseModel):
    contact_id: Optional[int] = None
    new_customer: Optional[NewCustomer] = None
    plant_id: int
    variant_id: Optional[int] = None
    seeds_given: int = Field(ge=1, le=BIG)
    wanted_plants: Optional[int] = Field(default=None, ge=1, le=BIG)  # how many plants the customer wants
    entry_date: Optional[date] = None
    reference: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=1000)
    request_id: str = Field(min_length=8, max_length=60)


@router.post("", dependencies=[CREATE], status_code=201)
def create_entry(payload: SeedEntryIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    done = db.query(SeedEntry).filter(SeedEntry.request_id == payload.request_id).first()
    if done:
        return {**_with_plant(db, [done])[0], "already_saved": True}
    plant = db.query(Plant).filter(Plant.id == payload.plant_id).first()
    if not plant:
        raise HTTPException(status_code=400, detail="Unknown plant")
    variant = None
    if payload.variant_id:
        variant = db.query(PlantVariant).filter(PlantVariant.id == payload.variant_id, PlantVariant.plant_id == plant.id).first()
        if not variant:
            raise HTTPException(status_code=400, detail="That tray option does not belong to this plant")
    elif db.query(PlantVariant.id).filter(PlantVariant.plant_id == plant.id).first():
        raise HTTPException(status_code=400, detail="This plant is sold in trays: choose the tray size")

    contact = None
    if payload.contact_id:
        contact = db.query(Contact).filter(Contact.id == payload.contact_id).first()
        if not contact:
            raise HTTPException(status_code=400, detail="Unknown customer")
    elif payload.new_customer:
        name, phone = payload.new_customer.name.strip(), payload.new_customer.phone.strip()
        if phone and len(_digits(phone)) >= 10:
            contact = next((c for c in db.query(Contact).filter(Contact.phone.ilike(f"%{_digits(phone)}")) if _digits(c.phone) == _digits(phone)), None)  # same mobile = same customer
        if not contact:
            contact = Contact(name=name, phone=phone, source="offline", created_by=admin)
            db.add(contact)
            db.flush()
    else:
        raise HTTPException(status_code=400, detail="Choose a customer or add a new one")

    when = datetime.combine(payload.entry_date or date.today(), datetime.min.time())
    entry = SeedEntry(request_id=payload.request_id, contact_id=contact.id, customer_name=contact.name, plant_id=plant.id, variant_id=variant.id if variant else None,
                      tray_size=variant.tray_size if variant else None, seeds_given=payload.seeds_given, wanted_plants=payload.wanted_plants, entry_date=when, reference=payload.reference.strip(),
                      notes=payload.notes.strip(), created_by=admin, status="Pending")
    db.add(entry)
    try:
        db.flush()
        entry.entry_number = f"SE-{entry.id}"
        db.commit()
    except IntegrityError:
        db.rollback()
        done = db.query(SeedEntry).filter(SeedEntry.request_id == payload.request_id).first()
        if done:
            return {**_with_plant(db, [done])[0], "already_saved": True}
        raise
    record_admin_audit(admin, "seed_entry_created", {"entry": entry.id, "seeds": entry.seeds_given})
    return {**_with_plant(db, [entry])[0], "already_saved": False}


# ------------------------------------------------------------------ list / detail
@router.get("", dependencies=[VIEW])
def list_entries(status: str = Query("open", pattern="^(open|all)$"), q: str = Query("", max_length=60), db: Session = Depends(get_db)):
    query = db.query(SeedEntry)
    if status == "open":
        query = query.filter(SeedEntry.status != "Completed")
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(SeedEntry.customer_name.ilike(like) | SeedEntry.entry_number.ilike(like) | SeedEntry.reference.ilike(like))
    items = query.order_by(SeedEntry.entry_date.desc(), SeedEntry.id.desc()).limit(300).all()
    rows = _with_plant(db, items)
    openrows = [r for r in rows if r["status"] != "Completed"]
    # Seeds given / good / extra / bad are totals over EVERY entry (a closed entry is still seeds we were given);
    # "still to grow" and "open entries" are about the entries not finished yet.
    every = db.query(func.coalesce(func.sum(SeedEntry.seeds_given), 0), func.coalesce(func.sum(SeedEntry.prepared_plants), 0), func.coalesce(func.sum(SeedEntry.extra_plants), 0),
                     func.coalesce(func.sum(SeedEntry.rejected_plants), 0)).one()
    open_all = [_out(e) for e in db.query(SeedEntry).filter(SeedEntry.status != "Completed").all()]
    return {
        "items": rows,
        "totals": {
            "open_entries": len(open_all), "seeds_given": int(every[0]), "remaining": sum(r["remaining"] for r in open_all),
            "prepared": int(every[1]), "extra": int(every[2]), "rejected": int(every[3]),
        },
    }


@router.get("/history", dependencies=[VIEW])
def history(q: str = Query("", max_length=60), db: Session = Depends(get_db)):
    """Every seed entry (open and completed), grouped by customer, with its full update log."""
    query = db.query(SeedEntry)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(SeedEntry.customer_name.ilike(like) | SeedEntry.entry_number.ilike(like) | SeedEntry.reference.ilike(like))
    items = query.order_by(SeedEntry.entry_date.desc(), SeedEntry.id.desc()).limit(1000).all()
    rows = _with_plant(db, items)
    logs = {}
    for u in db.query(SeedEntryUpdate).filter(SeedEntryUpdate.entry_id.in_({i.id for i in items} or {0})).order_by(SeedEntryUpdate.id):
        logs.setdefault(u.entry_id, []).append({"id": u.id, "at": u.created_at.isoformat() + "Z", "prepared": u.prepared_add, "extra": u.extra_add, "rejected": u.rejected_add,
                                                "finished": u.finished, "notes": u.notes or "", "by": u.created_by})
    phones = {c.id: c.phone or "" for c in db.query(Contact.id, Contact.phone).filter(Contact.id.in_({i.contact_id for i in items} or {0}))}
    groups: dict = {}
    for r in rows:
        r["log"] = logs.get(r["id"], [])
        g = groups.setdefault(r["contact_id"], {"contact_id": r["contact_id"], "name": r["customer_name"], "phone": phones.get(r["contact_id"], ""), "entries": [],
                                                "seeds": 0, "good": 0, "extra": 0, "rejected": 0, "remaining": 0})
        g["entries"].append(r)
        g["seeds"] += r["seeds_given"]
        g["good"] += r["prepared_plants"]
        g["extra"] += r["extra_plants"]
        g["rejected"] += r["rejected_plants"]
        g["remaining"] += r["remaining"]
    return {"customers": sorted(groups.values(), key=lambda g: g["entries"][0]["entry_date"] or "", reverse=True)}


@router.get("/{entry_id}", dependencies=[VIEW])
def entry_detail(entry_id: int, db: Session = Depends(get_db)):
    e = db.query(SeedEntry).filter(SeedEntry.id == entry_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Seed entry not found")
    out = _with_plant(db, [e])[0]
    out["updates"] = [{"id": u.id, "at": u.created_at.isoformat() + "Z", "prepared": u.prepared_add, "extra": u.extra_add, "rejected": u.rejected_add, "finished": u.finished, "notes": u.notes, "by": u.created_by}
                      for u in db.query(SeedEntryUpdate).filter(SeedEntryUpdate.entry_id == e.id).order_by(SeedEntryUpdate.id)]
    return out


# ------------------------------------------------------------------ production update
class SeedEntryUpdateIn(BaseModel):
    prepared_plants: int = Field(default=0, ge=0, le=BIG)  # added now
    extra_plants: int = Field(default=0, ge=0, le=BIG)  # added now
    rejected_plants: int = Field(default=0, ge=0, le=BIG)  # added now
    finish: bool = False  # nothing more will grow: the seeds still remaining count as lost (and the plants were handed over)
    # Simplest way to update: only say how many GOOD plants came out. The customer's share is worked out from
    # "wanted_plants" and the rest is extra, which goes straight to Ready now.
    good_plants: Optional[int] = Field(default=None, ge=0, le=BIG)
    wanted_plants: Optional[int] = Field(default=None, ge=1, le=BIG)  # set / change what the customer wants
    raise_seeds: bool = False  # more plants than seeds were written: raise "seeds given" to match (recorded in the note)
    notes: str = Field(default="", max_length=1000)
    request_id: str = Field(min_length=8, max_length=60)


@router.post("/{entry_id}/update", dependencies=[EDIT])
def update_entry(entry_id: int, payload: SeedEntryUpdateIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    e = db.query(SeedEntry).filter(SeedEntry.id == entry_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Seed entry not found")
    if db.query(SeedEntryUpdate.id).filter(SeedEntryUpdate.request_id == payload.request_id).first():
        return {**_with_plant(db, [e])[0], "already_saved": True}  # a retry / double click
    if e.status == "Completed":
        raise HTTPException(status_code=400, detail="This entry is already completed")
    extra_note = ""
    if payload.wanted_plants is not None and payload.wanted_plants != e.wanted_plants:
        extra_note += f" Customer wants {payload.wanted_plants} plants" + (f" (was {e.wanted_plants})." if e.wanted_plants else ".")
        e.wanted_plants = payload.wanted_plants
    prepared_add, extra_add, rejected_add = payload.prepared_plants, payload.extra_plants, payload.rejected_plants
    if payload.good_plants is not None:
        if payload.prepared_plants or payload.extra_plants:
            raise HTTPException(status_code=400, detail="Write either the good plants, or the customer's share and the extra separately, not both")
        if not e.wanted_plants:
            raise HTTPException(status_code=400, detail="First write how many plants the customer wants, so the extra can go to stock")
        prepared_add = min(payload.good_plants, max(e.wanted_plants - e.prepared_plants, 0))
        extra_add = payload.good_plants - prepared_add
    add_total = prepared_add + extra_add + rejected_add
    if add_total == 0 and not payload.finish:
        raise HTTPException(status_code=400, detail="Write at least one number (good plants, bad plants), or finish the entry")
    used = e.prepared_plants + e.extra_plants + e.rejected_plants + add_total
    if used > e.seeds_given:
        if not payload.raise_seeds:
            raise HTTPException(status_code=400, detail=f"That is {used - e.seeds_given} more plants than seeds given ({e.seeds_given}). Only {e.seeds_given - (used - add_total)} seeds are still remaining.")
        extra_note += f" Seeds given raised from {e.seeds_given} to {used} because more plants came out."
        e.seeds_given = used

    e.prepared_plants += prepared_add
    e.extra_plants += extra_add
    e.rejected_plants += rejected_add
    lost = 0
    if payload.finish:
        lost = e.seeds_given - (e.prepared_plants + e.extra_plants + e.rejected_plants)
        e.rejected_plants += lost  # seeds that never grew are recorded, not forgotten
    # extra usable plants -> ready stock (whole trays for tray products)
    total_units = (e.extra_plants // e.tray_size) if e.tray_size else e.extra_plants
    delta = total_units - e.extra_units_added
    if delta > 0:
        adjust_stock(db, plant_id=e.plant_id, variant_id=e.variant_id, quantity_delta=delta, transaction_type="PRODUCTION_RECEIVED", source_type="SEED_ENTRY", source_id=e.id,
                     reference=f"SEEDENTRY:{e.id}:EXTRA:{payload.request_id}", created_by=admin, notes=f"{e.entry_number}: extra usable plants from {e.customer_name}'s seeds")
        e.extra_units_added = total_units
    remaining = e.seeds_given - (e.prepared_plants + e.extra_plants + e.rejected_plants)
    e.status = "Completed" if (payload.finish or remaining == 0) else "In Progress"
    e.completed_at = datetime.utcnow() if e.status == "Completed" else None
    e.updated_at = datetime.utcnow()
    if payload.finish and e.handed_over_at is None:
        e.handed_over_at = datetime.utcnow()  # closing means the plants were handed over
    note = (payload.notes.strip() + (f" (Finished: {lost} seeds that did not grow are counted as lost)" if lost else "") + extra_note).strip()
    db.add(SeedEntryUpdate(entry_id=e.id, request_id=payload.request_id, prepared_add=prepared_add, extra_add=extra_add, rejected_add=rejected_add + lost,
                           finished=e.status == "Completed", notes=note, created_by=admin))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {**_with_plant(db, [db.query(SeedEntry).filter(SeedEntry.id == entry_id).first()])[0], "already_saved": True}
    record_admin_audit(admin, "seed_entry_updated", {"entry": e.id})
    db.refresh(e)
    return {**_with_plant(db, [e])[0], "already_saved": False}


class HandoverIn(BaseModel):
    request_id: str = Field(min_length=8, max_length=60)


@router.post("/{entry_id}/handover", dependencies=[EDIT])
def handover(entry_id: int, payload: HandoverIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """The plants were given to the customer: they stop being held in the nursery. If seeds were still left, they are counted as not grown."""
    e = db.query(SeedEntry).filter(SeedEntry.id == entry_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Seed entry not found")
    if e.handed_over_at is not None:
        return {**_with_plant(db, [e])[0], "already_saved": True}
    if db.query(SeedEntryUpdate.id).filter(SeedEntryUpdate.request_id == payload.request_id).first():
        return {**_with_plant(db, [e])[0], "already_saved": True}
    lost = max(e.seeds_given - (e.prepared_plants + e.extra_plants + e.rejected_plants), 0)
    e.rejected_plants += lost
    e.handed_over_at = datetime.utcnow()
    e.status = "Completed"
    e.completed_at = e.completed_at or datetime.utcnow()
    e.updated_at = datetime.utcnow()
    db.add(SeedEntryUpdate(entry_id=e.id, request_id=payload.request_id, prepared_add=0, extra_add=0, rejected_add=lost, finished=True,
                           notes="Plants handed over to the customer" + (f" ({lost} seeds that did not grow are counted as lost)" if lost else ""), created_by=admin))
    db.commit()
    record_admin_audit(admin, "seed_entry_handed_over", {"entry": e.id})
    db.refresh(e)
    return {**_with_plant(db, [e])[0], "already_saved": False}


# ------------------------------------------------------------------ edit / correct / remove
def _new_tag() -> str:
    import uuid

    return uuid.uuid4().hex


def _recalc(db: Session, e: SeedEntry, admin: str) -> None:
    """Totals always come from the update log; extra plants follow into ready stock by the difference."""
    ups = db.query(SeedEntryUpdate).filter(SeedEntryUpdate.entry_id == e.id).all()
    prepared, extra, rejected = sum(u.prepared_add for u in ups), sum(u.extra_add for u in ups), sum(u.rejected_add for u in ups)
    if prepared + extra + rejected > e.seeds_given:
        raise HTTPException(status_code=400, detail=f"That adds up to {prepared + extra + rejected} plants, but only {e.seeds_given} seeds were given")
    units = (extra // e.tray_size) if e.tray_size else extra
    delta = units - e.extra_units_added
    if delta != 0:
        try:
            adjust_stock(db, plant_id=e.plant_id, variant_id=e.variant_id, quantity_delta=delta, transaction_type="ADJUSTMENT", source_type="SEED_ENTRY", source_id=e.id,
                         reference=f"SEEDENTRY:{e.id}:CORR:{_new_tag()}", created_by=admin, notes=f"{e.entry_number}: correction of extra plants ({'+' if delta > 0 else ''}{delta})")
        except InsufficientStockError:
            raise HTTPException(status_code=400, detail="Those extra plants are already sold or given, so they cannot be taken back from stock")
    e.prepared_plants, e.extra_plants, e.rejected_plants, e.extra_units_added = prepared, extra, rejected, units
    remaining = e.seeds_given - prepared - extra - rejected
    e.status = "Completed" if (ups and remaining == 0) else ("In Progress" if ups else "Pending")
    e.completed_at = datetime.utcnow() if e.status == "Completed" else None
    e.updated_at = datetime.utcnow()


def _entry(db: Session, entry_id: int) -> SeedEntry:
    e = db.query(SeedEntry).filter(SeedEntry.id == entry_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Seed entry not found")
    return e


class EntryEdit(BaseModel):
    contact_id: Optional[int] = None
    plant_id: Optional[int] = None
    variant_id: Optional[int] = None
    seeds_given: Optional[int] = Field(default=None, ge=1, le=BIG)
    wanted_plants: Optional[int] = Field(default=None, ge=1, le=BIG)
    entry_date: Optional[date] = None
    reference: Optional[str] = Field(default=None, max_length=80)
    notes: Optional[str] = Field(default=None, max_length=1000)


@router.put("/{entry_id}", dependencies=[EDIT])
def edit_entry(entry_id: int, payload: EntryEdit, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    e = _entry(db, entry_id)
    has_updates = db.query(SeedEntryUpdate.id).filter(SeedEntryUpdate.entry_id == e.id).first() is not None
    if payload.contact_id is not None and payload.contact_id != e.contact_id:
        c = db.query(Contact).filter(Contact.id == payload.contact_id).first()
        if not c:
            raise HTTPException(status_code=400, detail="Unknown customer")
        e.contact_id, e.customer_name = c.id, c.name
    if payload.plant_id is not None and (payload.plant_id != e.plant_id or (payload.variant_id or None) != e.variant_id):
        if has_updates:
            raise HTTPException(status_code=400, detail="The plant cannot be changed after plants were recorded. Remove the updates first, or make a new entry.")
        plant = db.query(Plant).filter(Plant.id == payload.plant_id).first()
        if not plant:
            raise HTTPException(status_code=400, detail="Unknown plant")
        variant = None
        if payload.variant_id:
            variant = db.query(PlantVariant).filter(PlantVariant.id == payload.variant_id, PlantVariant.plant_id == plant.id).first()
            if not variant:
                raise HTTPException(status_code=400, detail="That tray option does not belong to this plant")
        elif db.query(PlantVariant.id).filter(PlantVariant.plant_id == plant.id).first():
            raise HTTPException(status_code=400, detail="This plant is sold in trays: choose the tray size")
        e.plant_id, e.variant_id, e.tray_size = plant.id, (variant.id if variant else None), (variant.tray_size if variant else None)
    if payload.seeds_given is not None:
        used = e.prepared_plants + e.extra_plants + e.rejected_plants
        if payload.seeds_given < used:
            raise HTTPException(status_code=400, detail=f"{used} plants are already recorded, so seeds cannot be less than {used}")
        e.seeds_given = payload.seeds_given
    if payload.wanted_plants is not None:
        e.wanted_plants = payload.wanted_plants
    if payload.entry_date is not None:
        e.entry_date = datetime.combine(payload.entry_date, datetime.min.time())
    if payload.reference is not None:
        e.reference = payload.reference.strip()
    if payload.notes is not None:
        e.notes = payload.notes.strip()
    try:
        _recalc(db, e, admin)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    record_admin_audit(admin, "seed_entry_edited", {"entry": e.id})
    db.refresh(e)
    return _with_plant(db, [e])[0]


class UpdateEdit(BaseModel):
    prepared_plants: int = Field(ge=0, le=BIG)
    extra_plants: int = Field(ge=0, le=BIG)
    rejected_plants: int = Field(ge=0, le=BIG)
    notes: str = Field(default="", max_length=1000)


@router.put("/{entry_id}/updates/{update_id}", dependencies=[EDIT])
def edit_update(entry_id: int, update_id: int, payload: UpdateEdit, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    e = _entry(db, entry_id)
    u = db.query(SeedEntryUpdate).filter(SeedEntryUpdate.id == update_id, SeedEntryUpdate.entry_id == e.id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Update not found")
    u.prepared_add, u.extra_add, u.rejected_add, u.notes = payload.prepared_plants, payload.extra_plants, payload.rejected_plants, payload.notes.strip()
    try:
        db.flush()
        _recalc(db, e, admin)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    record_admin_audit(admin, "seed_entry_update_edited", {"entry": e.id, "update": update_id})
    db.refresh(e)
    return _with_plant(db, [e])[0]


@router.delete("/{entry_id}/updates/{update_id}", dependencies=[EDIT])
def delete_update(entry_id: int, update_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    e = _entry(db, entry_id)
    u = db.query(SeedEntryUpdate).filter(SeedEntryUpdate.id == update_id, SeedEntryUpdate.entry_id == e.id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Update not found")
    try:
        db.delete(u)
        db.flush()
        _recalc(db, e, admin)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    record_admin_audit(admin, "seed_entry_update_removed", {"entry": e.id, "update": update_id})
    db.refresh(e)
    return _with_plant(db, [e])[0]


@router.delete("/{entry_id}", dependencies=[EDIT])
def delete_entry(entry_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    e = _entry(db, entry_id)
    if db.query(SeedEntryUpdate.id).filter(SeedEntryUpdate.entry_id == e.id).first():
        raise HTTPException(status_code=400, detail="Plants were already recorded on this entry. Remove those updates first.")
    db.delete(e)
    db.commit()
    record_admin_audit(admin, "seed_entry_deleted", {"entry": entry_id})
    return {"ok": True}
