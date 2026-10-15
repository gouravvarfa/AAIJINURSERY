"""Seed stock, production batches, the combined stock ledger and the yield
report. Ready plants are never edited here directly: a finished batch adds its
accepted plants through app.inventory (one ledger, one ready-stock number).

Who can do what (module "products"): view = VIEW, create seed items / batches =
CREATE, receive / issue / complete / cancel = EDIT.
"""
import math
import uuid
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_admin_audit
from app.database import get_db
from app.deps import get_current_admin
from app.inventory import MAX_ORDER_QUANTITY, adjust_stock, set_stock_with_ledger
from app.inventory_router import _open_offline_lines, _open_online_lines
from app.models import InventoryTransaction, Order, OrderItem, Plant, PlantVariant
from app.accounting.models import SalesOrder, SalesOrderItem
from app.permissions import require_permission
from app.production_models import (
    OPEN_BATCH_STATUSES,
    ProductionBatch,
    ProductionBatchOrder,
    SeedItem,
    SeedMovement,
)

router = APIRouter(prefix="/api/admin/stock", tags=["stock-production"])
VIEW = Depends(require_permission("products", "VIEW"))
CREATE = Depends(require_permission("products", "CREATE"))
EDIT = Depends(require_permission("products", "EDIT"))

Qty = Field(ge=1, le=MAX_ORDER_QUANTITY * 100)


# ----------------------------------------------------------------- seed ledger
def _seed_move(db: Session, seed_id: int, movement_type: str, qty: int, direction: int, *, source_type: str = "",
               source_id="", reference: Optional[str] = None, notes: str = "", admin: str = "") -> SeedMovement:
    """direction: -1 takes from the seed store, +1 adds to it, 0 only records (balance already moved)."""
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be at least 1")
    if reference:
        existing = db.query(SeedMovement).filter(SeedMovement.reference == reference).first()
        if existing:
            return existing
    if direction < 0:
        res = db.execute(sa_update(SeedItem).where(SeedItem.id == seed_id, SeedItem.quantity >= qty).values(quantity=SeedItem.quantity - qty))
        if res.rowcount == 0:
            have = db.query(SeedItem.quantity).filter(SeedItem.id == seed_id).scalar() or 0
            raise HTTPException(status_code=400, detail=f"Only {have} in the seed store, so {qty} can't be taken")
    elif direction > 0:
        db.execute(sa_update(SeedItem).where(SeedItem.id == seed_id).values(quantity=SeedItem.quantity + qty))
    after = db.query(SeedItem.quantity).filter(SeedItem.id == seed_id).scalar() or 0
    before = after - qty * direction
    row = SeedMovement(seed_item_id=seed_id, movement_type=movement_type, quantity=qty, before_quantity=before, after_quantity=after,
                       source_type=source_type, source_id=str(source_id or ""), reference=reference, notes=notes, created_by=admin)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        winner = db.query(SeedMovement).filter(SeedMovement.reference == reference).first()
        if winner:
            return winner
        raise
    return row


def _seed_out(s: SeedItem, in_batches: int) -> dict:
    return {"id": s.id, "name": s.name, "plant_id": s.plant_id, "unit": s.unit, "balance": s.quantity, "with_open_batches": in_batches,
            "notes": s.notes or "", "is_active": s.is_active}


def _open_seed_wip(db: Session) -> dict:
    out: dict = {}
    for b in db.query(ProductionBatch).filter(ProductionBatch.status.in_(OPEN_BATCH_STATUSES), ProductionBatch.seed_item_id.isnot(None)):
        out[b.seed_item_id] = out.get(b.seed_item_id, 0) + (b.seeds_issued - b.seeds_returned - b.seeds_consumed - b.seeds_wasted)
    return out


class SeedIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    plant_id: Optional[int] = None
    unit: str = Field(default="seeds", max_length=20)
    opening_quantity: int = Field(default=0, ge=0, le=MAX_ORDER_QUANTITY * 100)
    notes: str = ""


class SeedQtyIn(BaseModel):
    quantity: int = Qty
    notes: str = ""
    request_id: Optional[str] = Field(default=None, max_length=60)


@router.get("/seeds", dependencies=[VIEW])
def list_seeds(db: Session = Depends(get_db)):
    wip = _open_seed_wip(db)
    return [_seed_out(s, wip.get(s.id, 0)) for s in db.query(SeedItem).order_by(SeedItem.name).all()]


@router.post("/seeds", dependencies=[CREATE], status_code=201)
def create_seed(payload: SeedIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    name = payload.name.strip()
    if db.query(SeedItem).filter(func.lower(SeedItem.name) == name.lower()).first():
        raise HTTPException(status_code=400, detail="A seed item with this name already exists")
    if payload.plant_id and not db.query(Plant.id).filter(Plant.id == payload.plant_id).first():
        raise HTTPException(status_code=400, detail="Unknown plant")
    seed = SeedItem(name=name, plant_id=payload.plant_id, unit=payload.unit.strip() or "seeds", quantity=0, notes=payload.notes.strip(), created_by=admin)
    db.add(seed)
    db.flush()
    if payload.opening_quantity:
        _seed_move(db, seed.id, "RECEIVED", payload.opening_quantity, +1, source_type="OPENING", reference=f"SEED:{seed.id}:OPENING", notes="Opening balance", admin=admin)
    db.commit()
    record_admin_audit(admin, "seed_item_created", {"seed": seed.id})
    return _seed_out(seed, 0)


@router.post("/seeds/{seed_id}/receive", dependencies=[EDIT])
def receive_seeds(seed_id: int, payload: SeedQtyIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    seed = db.query(SeedItem).filter(SeedItem.id == seed_id).first()
    if not seed:
        raise HTTPException(status_code=404, detail="Seed item not found")
    _seed_move(db, seed.id, "RECEIVED", payload.quantity, +1, source_type="RECEIPT", reference=f"SEED:{seed.id}:RECEIVE:{payload.request_id}" if payload.request_id else None,
               notes=payload.notes.strip() or "Seeds received", admin=admin)
    db.commit()
    db.refresh(seed)
    return _seed_out(seed, _open_seed_wip(db).get(seed.id, 0))


@router.post("/seeds/{seed_id}/damaged", dependencies=[EDIT])
def damaged_seeds(seed_id: int, payload: SeedQtyIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    seed = db.query(SeedItem).filter(SeedItem.id == seed_id).first()
    if not seed:
        raise HTTPException(status_code=404, detail="Seed item not found")
    if not payload.notes.strip():
        raise HTTPException(status_code=400, detail="Please write the reason")
    _seed_move(db, seed.id, "DAMAGED", payload.quantity, -1, source_type="STORE", reference=f"SEED:{seed.id}:DAMAGED:{payload.request_id}" if payload.request_id else None,
               notes=payload.notes.strip(), admin=admin)
    db.commit()
    db.refresh(seed)
    return _seed_out(seed, _open_seed_wip(db).get(seed.id, 0))


# --------------------------------------------------------------------- batches
def _unit_name(b: ProductionBatch) -> str:
    return "trays" if b.variant_id else "plants"


def planned_units(b: ProductionBatch) -> int:
    """Planned output in the same unit as the ready stock (trays for tray products)."""
    return math.ceil(b.planned_quantity / b.tray_size) if b.variant_id and b.tray_size else b.planned_quantity


def planned_by_target(db: Session) -> dict:
    out: dict = {}
    for b in db.query(ProductionBatch).filter(ProductionBatch.status.in_(OPEN_BATCH_STATUSES)):
        key = (b.plant_id, b.variant_id or None)
        out[key] = out.get(key, 0) + planned_units(b)
    return out


def _batch_out(db: Session, b: ProductionBatch) -> dict:
    plant = db.query(Plant).filter(Plant.id == b.plant_id).first()
    seed = db.query(SeedItem).filter(SeedItem.id == b.seed_item_id).first() if b.seed_item_id else None
    return {
        "id": b.id, "batch_number": b.batch_number, "status": b.status, "plant_id": b.plant_id,
        "plant_name": (plant.name if plant else "") + (f" - tray of {b.tray_size}" if b.variant_id else ""),
        "variant_id": b.variant_id, "tray_size": b.tray_size, "unit": _unit_name(b), "seed_item_id": b.seed_item_id, "seed_name": seed.name if seed else "",
        "planned_quantity": b.planned_quantity, "planned_units": planned_units(b),
        "seeds_issued": b.seeds_issued, "seeds_consumed": b.seeds_consumed, "seeds_returned": b.seeds_returned, "seeds_wasted": b.seeds_wasted,
        "seeds_not_accounted": (b.seeds_issued - b.seeds_consumed - b.seeds_returned - b.seeds_wasted) if b.status in OPEN_BATCH_STATUSES else 0,
        "healthy_plants": b.healthy_plants, "rejected_plants": b.rejected_plants, "accepted_plants": b.accepted_plants,
        "accepted_units": b.accepted_units, "loose_plants": b.loose_plants, "notes": b.notes or "",
        "created_by": b.created_by, "created_at": b.created_at.isoformat() + "Z" if b.created_at else None,
        "started_at": b.started_at.isoformat() + "Z" if b.started_at else None,
        "completed_at": b.completed_at.isoformat() + "Z" if b.completed_at else None, "completed_by": b.completed_by,
    }


class LinkIn(BaseModel):
    kind: Literal["order", "sales_order"]
    item_id: int


class BatchIn(BaseModel):
    plant_id: int
    variant_id: Optional[int] = None
    seed_item_id: Optional[int] = None
    planned_quantity: int = Qty
    notes: str = ""
    links: list[LinkIn] = []


class IssueIn(BaseModel):
    quantity: int = Qty
    request_id: Optional[str] = Field(default=None, max_length=60)


class CompleteIn(BaseModel):
    seeds_consumed: int = Field(default=0, ge=0)
    seeds_returned: int = Field(default=0, ge=0)
    seeds_wasted: int = Field(default=0, ge=0)
    healthy_plants: int = Field(ge=0)
    rejected_plants: int = Field(default=0, ge=0)
    accepted_plants: Optional[int] = Field(default=None, ge=0)
    notes: str = ""


def _get_batch(db: Session, batch_id: int) -> ProductionBatch:
    b = db.query(ProductionBatch).filter(ProductionBatch.id == batch_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Batch not found")
    return b


@router.get("/batches", dependencies=[VIEW])
def list_batches(status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(ProductionBatch)
    if status:
        q = q.filter(ProductionBatch.status == status)
    return [_batch_out(db, b) for b in q.order_by(ProductionBatch.id.desc()).limit(300).all()]


@router.post("/batches", dependencies=[CREATE], status_code=201)
def create_batch(payload: BatchIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    plant = db.query(Plant).filter(Plant.id == payload.plant_id).first()
    if not plant:
        raise HTTPException(status_code=400, detail="Unknown plant")
    variant = None
    if payload.variant_id:
        variant = db.query(PlantVariant).filter(PlantVariant.id == payload.variant_id, PlantVariant.plant_id == plant.id).first()
        if not variant:
            raise HTTPException(status_code=400, detail="That tray option does not belong to this plant")
    elif db.query(PlantVariant.id).filter(PlantVariant.plant_id == plant.id).first():
        raise HTTPException(status_code=400, detail="This plant is sold in trays: choose the tray size the batch is for")
    seed = None
    if payload.seed_item_id:
        seed = db.query(SeedItem).filter(SeedItem.id == payload.seed_item_id).first()
        if not seed:
            raise HTTPException(status_code=400, detail="Unknown seed item")
        if seed.plant_id and seed.plant_id != plant.id:
            raise HTTPException(status_code=400, detail="This seed is for a different plant variety")
    b = ProductionBatch(plant_id=plant.id, variant_id=variant.id if variant else None, tray_size=variant.tray_size if variant else None,
                        seed_item_id=seed.id if seed else None, planned_quantity=payload.planned_quantity, status="Draft", notes=payload.notes.strip(), created_by=admin)
    db.add(b)
    db.flush()
    b.batch_number = f"BATCH-{b.id}"
    for link in payload.links:
        line = (db.query(OrderItem) if link.kind == "order" else db.query(SalesOrderItem)).filter_by(id=link.item_id).first()
        if not line or line.plant_id != plant.id or (line.variant_id or None) != (variant.id if variant else None):
            raise HTTPException(status_code=400, detail="A linked order line is for a different plant or tray size")
        db.add(ProductionBatchOrder(batch_id=b.id, kind=link.kind, item_id=link.item_id))
    db.commit()
    record_admin_audit(admin, "production_batch_created", {"batch": b.id})
    return _batch_out(db, b)


@router.get("/batches/{batch_id}", dependencies=[VIEW])
def batch_detail(batch_id: int, db: Session = Depends(get_db)):
    b = _get_batch(db, batch_id)
    out = _batch_out(db, b)
    out["seed_movements"] = [
        {"id": m.id, "type": m.movement_type, "quantity": m.quantity, "before": m.before_quantity, "after": m.after_quantity, "notes": m.notes,
         "by": m.created_by, "at": m.created_at.isoformat() + "Z"}
        for m in db.query(SeedMovement).filter(SeedMovement.source_type == "BATCH", SeedMovement.source_id == str(b.id)).order_by(SeedMovement.id)
    ]
    out["links"] = [{"kind": l.kind, "item_id": l.item_id} for l in db.query(ProductionBatchOrder).filter(ProductionBatchOrder.batch_id == b.id)]
    return out


@router.post("/batches/{batch_id}/issue-seeds", dependencies=[EDIT])
def issue_seeds(batch_id: int, payload: IssueIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    b = _get_batch(db, batch_id)
    if b.status not in OPEN_BATCH_STATUSES:
        raise HTTPException(status_code=400, detail=f"This batch is {b.status}; seeds can't be issued")
    if not b.seed_item_id:
        raise HTTPException(status_code=400, detail="This batch has no seed item")
    ref = f"BATCH:{b.id}:ISSUE:{payload.request_id or uuid.uuid4().hex[:12]}"
    existed = db.query(SeedMovement.id).filter(SeedMovement.reference == ref).first() is not None
    _seed_move(db, b.seed_item_id, "ISSUED", payload.quantity, -1, source_type="BATCH", source_id=b.id, reference=ref, notes=f"Issued to {b.batch_number}", admin=admin)
    if not existed:  # a retried request (same request_id) must not count the seeds twice
        db.execute(sa_update(ProductionBatch).where(ProductionBatch.id == b.id).values(seeds_issued=ProductionBatch.seeds_issued + payload.quantity))
        if b.status == "Draft":
            b.status, b.started_at = "In Progress", datetime.utcnow()
    db.commit()
    db.refresh(b)
    return _batch_out(db, b)


@router.post("/batches/{batch_id}/complete", dependencies=[EDIT])
def complete_batch(batch_id: int, payload: CompleteIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    b = _get_batch(db, batch_id)
    if b.status not in OPEN_BATCH_STATUSES:
        raise HTTPException(status_code=409, detail=f"This batch is already {b.status}")
    accepted = payload.healthy_plants if payload.accepted_plants is None else payload.accepted_plants
    if accepted > payload.healthy_plants:
        raise HTTPException(status_code=400, detail="Accepted plants can't be more than the healthy plants produced")
    if b.seed_item_id or b.seeds_issued:
        if payload.seeds_consumed + payload.seeds_returned + payload.seeds_wasted != b.seeds_issued:
            raise HTTPException(status_code=400, detail=f"Account for every seed: {b.seeds_issued} were issued, but consumed + returned + wasted = {payload.seeds_consumed + payload.seeds_returned + payload.seeds_wasted}")
        if payload.healthy_plants + payload.rejected_plants > payload.seeds_consumed:
            raise HTTPException(status_code=400, detail="Healthy + rejected plants can't be more than the seeds consumed")
    elif payload.seeds_consumed or payload.seeds_returned or payload.seeds_wasted:
        raise HTTPException(status_code=400, detail="No seeds were issued to this batch")

    # one winner only: a double click or retry finds the batch already completed
    won = db.execute(sa_update(ProductionBatch).where(ProductionBatch.id == b.id, ProductionBatch.status.in_(OPEN_BATCH_STATUSES))
                     .values(status="Completed", completed_at=datetime.utcnow(), completed_by=admin))
    if won.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=409, detail="This batch was just completed by someone else")

    if b.seed_item_id:
        for kind, qty, direction in (("CONSUMED", payload.seeds_consumed, 0), ("RETURNED", payload.seeds_returned, +1), ("WASTED", payload.seeds_wasted, 0)):
            if qty:
                _seed_move(db, b.seed_item_id, kind, qty, direction, source_type="BATCH", source_id=b.id, reference=f"BATCH:{b.id}:{kind}", notes=f"{b.batch_number} completed", admin=admin)

    units, loose = (accepted // b.tray_size, accepted % b.tray_size) if b.variant_id and b.tray_size else (accepted, 0)
    if units:
        adjust_stock(db, plant_id=b.plant_id, variant_id=b.variant_id, quantity_delta=units, transaction_type="PRODUCTION_RECEIVED", source_type="PRODUCTION_BATCH",
                     source_id=b.id, reference=f"BATCH:{b.id}:ACCEPT", created_by=admin,
                     notes=f"{b.batch_number}: {accepted} plants accepted" + (f" ({units} trays, {loose} loose plants held back)" if loose else ""))
    db.execute(sa_update(ProductionBatch).where(ProductionBatch.id == b.id).values(
        seeds_consumed=payload.seeds_consumed, seeds_returned=payload.seeds_returned, seeds_wasted=payload.seeds_wasted,
        healthy_plants=payload.healthy_plants, rejected_plants=payload.rejected_plants, accepted_plants=accepted, accepted_units=units, loose_plants=loose,
        notes=(b.notes + ("\n" if b.notes and payload.notes else "") + payload.notes.strip()).strip()))
    db.commit()
    record_admin_audit(admin, "production_batch_completed", {"batch": b.id, "accepted": accepted})
    db.refresh(b)
    return _batch_out(db, b)


@router.post("/batches/{batch_id}/cancel", dependencies=[EDIT])
def cancel_batch(batch_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    b = _get_batch(db, batch_id)
    won = db.execute(sa_update(ProductionBatch).where(ProductionBatch.id == b.id, ProductionBatch.status.in_(OPEN_BATCH_STATUSES)).values(status="Cancelled", completed_at=datetime.utcnow(), completed_by=admin))
    if won.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"This batch is already {b.status}")
    if b.seed_item_id and b.seeds_issued:
        _seed_move(db, b.seed_item_id, "RETURNED", b.seeds_issued, +1, source_type="BATCH", source_id=b.id, reference=f"BATCH:{b.id}:CANCEL_RETURN",
                   notes=f"{b.batch_number} cancelled: all issued seeds returned", admin=admin)
        db.execute(sa_update(ProductionBatch).where(ProductionBatch.id == b.id).values(seeds_returned=b.seeds_issued))
    db.commit()
    db.refresh(b)
    return _batch_out(db, b)


def _pending_lines(db: Session, plant_id: int, variant_id: Optional[int]) -> list:
    rows = []
    online = _open_online_lines(db).filter(OrderItem.plant_id == plant_id)
    offline = _open_offline_lines(db).filter(SalesOrderItem.plant_id == plant_id)
    for line in online.all():
        if (line.variant_id or None) == variant_id and line.pending > 0:
            o = db.query(Order).filter(Order.id == line.order_id).first()
            rows.append(("order", line, o.created_at, f"ORD-{o.id}", o.delivery_name or "", f"/admin/orders/{o.id}"))
    for line in offline.all():
        if (line.variant_id or None) == variant_id and line.pending > 0 and line.to_prepare is not None:
            so = db.query(SalesOrder).filter(SalesOrder.id == line.sales_order_id).first()
            if so and so.status in ("Confirmed", "Invoiced"):
                rows.append(("sales_order", line, so.order_date, so.order_number, so.contact.name if so.contact else "", f"/admin/accounting/sales-orders/{so.id}"))
    rows.sort(key=lambda r: (r[2] or datetime.min, r[1].id))
    return rows


@router.get("/batches/{batch_id}/suggest", dependencies=[VIEW])
def suggest_allocation(batch_id: int, db: Session = Depends(get_db)):
    """First-come-first-served suggestion of which waiting order lines the ready stock could go to.
    Nothing is allocated here: the admin gives each line from stock (Stock & Preparation card)."""
    b = _get_batch(db, batch_id)
    target = db.query(PlantVariant).filter(PlantVariant.id == b.variant_id).first() if b.variant_id else db.query(Plant).filter(Plant.id == b.plant_id).first()
    available = (target.stock_quantity if target else 0) or 0
    left, out = available, []
    for kind, line, when, number, who, link in _pending_lines(db, b.plant_id, b.variant_id):
        give = min(line.pending, left)
        out.append({"kind": kind, "item_id": line.id, "order_number": number, "customer": who, "pending": line.pending, "suggested": give, "link": link})
        left -= give
    return {"available_stock": available, "unit": _unit_name(b), "lines": out, "left_after": left}


# ------------------------------------------------------------ ledger and reports
@router.get("/movements", dependencies=[VIEW])
def movements(kind: Literal["all", "stock", "seed"] = "all", plant_id: Optional[int] = None, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    items = []
    if kind in ("all", "stock"):
        q = db.query(InventoryTransaction)
        if plant_id:
            q = q.filter(InventoryTransaction.plant_id == plant_id)
        for t in q.order_by(InventoryTransaction.id.desc()).limit(limit):
            plant = db.query(Plant).filter(Plant.id == t.plant_id).first()
            variant = db.query(PlantVariant).filter(PlantVariant.id == t.variant_id).first() if t.variant_id else None
            items.append({"kind": "plants", "at": t.created_at.isoformat() + "Z", "item": (plant.name if plant else f"#{t.plant_id}") + (f" - tray of {variant.tray_size}" if variant else ""),
                          "type": t.transaction_type, "quantity": t.quantity, "before": t.before_quantity, "after": t.after_quantity, "source": f"{t.source_type} {t.source_id or ''}".strip(),
                          "by": t.created_by, "notes": t.notes or ""})
    if kind in ("all", "seed") and not plant_id:
        for m in db.query(SeedMovement).order_by(SeedMovement.id.desc()).limit(limit):
            seed = db.query(SeedItem).filter(SeedItem.id == m.seed_item_id).first()
            items.append({"kind": "seeds", "at": m.created_at.isoformat() + "Z", "item": seed.name if seed else f"#{m.seed_item_id}", "type": m.movement_type, "quantity": m.quantity,
                          "before": m.before_quantity, "after": m.after_quantity, "source": f"{m.source_type} {m.source_id or ''}".strip(), "by": m.created_by, "notes": m.notes or ""})
    items.sort(key=lambda r: r["at"], reverse=True)
    return {"items": items[:limit]}


@router.get("/allocations", dependencies=[VIEW])
def allocations(db: Session = Depends(get_db)):
    rows = []
    for line in _open_online_lines(db).all():
        if line.allocated > 0 or line.pending > 0:
            o = db.query(Order).filter(Order.id == line.order_id).first()
            rows.append({"kind": "order", "item_id": line.id, "plant_id": line.plant_id, "variant_id": line.variant_id, "number": f"ORD-{o.id}", "link": f"/admin/orders/{o.id}", "customer": o.delivery_name or "", "plant": line.plant_name + (f" - tray of {line.tray_size}" if line.tray_size else ""),
                         "ordered": line.quantity, "allocated": line.allocated, "pending": line.pending, "to_prepare": bool(line.to_prepare), "status": o.status, "when": o.created_at.isoformat() + "Z"})
    for line in _open_offline_lines(db).all():
        if line.allocated > 0 or line.pending > 0:
            so = db.query(SalesOrder).filter(SalesOrder.id == line.sales_order_id).first()
            rows.append({"kind": "sales_order", "item_id": line.id, "plant_id": line.plant_id, "variant_id": line.variant_id, "number": so.order_number, "link": f"/admin/accounting/sales-orders/{so.id}", "customer": so.contact.name if so.contact else "",
                         "plant": (line.description or "") + (f" - tray of {line.tray_size}" if line.tray_size else ""), "ordered": line.quantity, "allocated": line.allocated, "pending": line.pending,
                         "to_prepare": bool(line.to_prepare), "status": so.status, "when": so.order_date.isoformat() + "Z" if so.order_date else None})
    rows.sort(key=lambda r: r["when"] or "")
    return {"items": rows}


@router.get("/reports/yield", dependencies=[VIEW])
def yield_report(db: Session = Depends(get_db)):
    rows, per_plant = [], {}
    for b in db.query(ProductionBatch).filter(ProductionBatch.status == "Completed").order_by(ProductionBatch.id.desc()).all():
        o = _batch_out(db, b)
        consumed = b.seeds_consumed or 0
        o["yield_pct"] = round(100 * b.healthy_plants / consumed, 1) if consumed else None
        o["rejected_pct"] = round(100 * b.rejected_plants / consumed, 1) if consumed else None
        rows.append(o)
        t = per_plant.setdefault(o["plant_name"], {"plant": o["plant_name"], "batches": 0, "seeds_consumed": 0, "healthy": 0, "rejected": 0, "accepted": 0, "seeds_wasted": 0})
        t["batches"] += 1
        t["seeds_consumed"] += consumed
        t["healthy"] += b.healthy_plants
        t["rejected"] += b.rejected_plants
        t["accepted"] += b.accepted_plants
        t["seeds_wasted"] += b.seeds_wasted
    for t in per_plant.values():
        t["yield_pct"] = round(100 * t["healthy"] / t["seeds_consumed"], 1) if t["seeds_consumed"] else None
    return {"batches": rows, "by_plant": sorted(per_plant.values(), key=lambda r: r["plant"])}


class ReadyAdjustIn(BaseModel):
    plant_id: int
    variant_id: Optional[int] = None
    new_quantity: int = Field(ge=0, le=MAX_ORDER_QUANTITY * 100)
    reason: str = Field(min_length=3, max_length=200)


@router.post("/ready/adjust", dependencies=[EDIT])
def adjust_ready_stock(payload: ReadyAdjustIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Correct the count of ready plants (e.g. after a physical count). The
    difference is written to the ledger together with the reason."""
    plant = db.query(Plant).filter(Plant.id == payload.plant_id).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")
    has_trays = db.query(PlantVariant.id).filter(PlantVariant.plant_id == plant.id).first() is not None
    if payload.variant_id:
        if not db.query(PlantVariant.id).filter(PlantVariant.id == payload.variant_id, PlantVariant.plant_id == plant.id).first():
            raise HTTPException(status_code=400, detail="That tray option does not belong to this plant")
    elif has_trays:
        raise HTTPException(status_code=400, detail="This plant is sold in trays: choose the tray size")
    delta = set_stock_with_ledger(db, plant_id=plant.id, variant_id=payload.variant_id, new_quantity=payload.new_quantity, source_type="STOCK_COUNT",
                                  created_by=admin, notes=payload.reason.strip())
    db.commit()
    record_admin_audit(admin, "ready_stock_adjusted", {"plant": plant.id, "delta": delta})
    return {"changed_by": delta, "new_quantity": payload.new_quantity}


class AddPlantsIn(BaseModel):
    plant_id: int
    variant_id: Optional[int] = None
    good_plants: int = Qty
    rejected_plants: int = Field(default=0, ge=0)
    seeds_used: Optional[int] = Field(default=None, ge=0)
    notes: str = ""
    request_id: str = Field(min_length=8, max_length=60)


@router.post("/add-plants", dependencies=[EDIT])
def add_plants(payload: AddPlantsIn, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """The simple way to record plants that were made: how many came out good (and bad), optionally
    how many seeds were used. The good plants go straight into ready stock through the ledger, and a
    finished batch record is kept for the yield numbers. `request_id` makes a double click harmless."""
    ref = f"ADDPLANTS:{payload.request_id}"
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
    if payload.seeds_used is not None and payload.good_plants + payload.rejected_plants > payload.seeds_used:
        raise HTTPException(status_code=400, detail="Good + bad plants can't be more than the seeds used")
    tray = variant.tray_size if variant else None
    units, loose = (payload.good_plants // tray, payload.good_plants % tray) if tray else (payload.good_plants, 0)
    if tray and units == 0:
        raise HTTPException(status_code=400, detail=f"{payload.good_plants} plants are less than one full tray ({tray})")
    target = variant if variant else plant

    done = db.query(InventoryTransaction).filter(InventoryTransaction.reference == ref).first()
    if done:
        return {"already_added": True, "added_units": done.quantity, "unit": "trays" if variant else "plants", "loose_plants": 0, "new_ready": target.stock_quantity}

    now = datetime.utcnow()
    b = ProductionBatch(plant_id=plant.id, variant_id=variant.id if variant else None, tray_size=tray, planned_quantity=payload.good_plants, status="Completed",
                        seeds_consumed=payload.seeds_used or 0, healthy_plants=payload.good_plants, rejected_plants=payload.rejected_plants, accepted_plants=payload.good_plants,
                        accepted_units=units, loose_plants=loose, notes=payload.notes.strip(), created_by=admin, started_at=now, completed_at=now, completed_by=admin)
    db.add(b)
    db.flush()
    b.batch_number = f"BATCH-{b.id}"
    try:
        adjust_stock(db, plant_id=plant.id, variant_id=b.variant_id, quantity_delta=units, transaction_type="PRODUCTION_RECEIVED", source_type="PRODUCTION_BATCH", source_id=b.id,
                     reference=ref, created_by=admin, notes=f"{b.batch_number}: {payload.good_plants} good plants" + (f", {loose} loose plants kept aside" if loose else ""))
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"already_added": True, "added_units": units, "unit": "trays" if variant else "plants", "loose_plants": 0, "new_ready": target.stock_quantity}
    record_admin_audit(admin, "plants_added", {"batch": b.id, "good": payload.good_plants})
    db.refresh(target)
    return {"already_added": False, "batch_number": b.batch_number, "added_units": units, "unit": "trays" if variant else "plants", "loose_plants": loose, "new_ready": target.stock_quantity}
