"""Receiving supplies (seed packets, medicines, fertilizers, other supplies) into batch stock, and booking them on a supplier Bill.

One system for all of it:
* a supplier Bill (`purchases`, status Unpaid, linked to the supplier contact) has many `purchase_lines`;
* every line is received into a stock batch (`seed_packet_batches` + RECEIPT movement) with its own lot number and expiry;
* quantities are always the sum of the movement log, so history and numbers can never disagree;
* nothing here touches ready-to-sell plant stock (Plant.stock_quantity / inventory_transactions).

Every line and every receipt carries its own idempotent reference (purchase_lines unique (purchase, line_no), movement
request_id "PLINE:<line id>"), and a Bill is recognised by its request_id, so a retry can never add stock or payable twice."""
import re
from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounting.audit import record_change
from app.accounting.models import Contact
from app.communications.models import SystemFlag
from app.models import Plant, Purchase
from app.seed_packet_models import SeedPacketBatch, SeedPacketMovement
from app.supply_models import PurchaseLine

MAX_QTY = 1_000_000
MAX_MONEY = 1_000_000_000
KINDS = ("seed_packet", "medicine", "fertilizer", "supply")
KIND_LABEL = {"seed_packet": "Seed packet", "medicine": "Medicine", "fertilizer": "Fertilizer", "supply": "Other supply"}
LOT_REQUIRED = {"seed_packet", "medicine"}  # lot / batch number is required for these
EXPIRY_REQUIRED = {"seed_packet", "medicine"}  # expiry date is required for these (optional for the rest)
WHOLE_UNITS = {"packets", "pcs", "bottles", "bags", "boxes", "sachets", "nos", "tubes", "cans"}
DECIMAL_UNITS = {"kg", "g", "mg", "litre", "ml", "quintal"}
ALL_UNITS = sorted(WHOLE_UNITS | DECIMAL_UNITS)
DEFAULT_UNIT = {"seed_packet": "packets", "medicine": "bottles", "fertilizer": "bags", "supply": "pcs"}
SIZE_UNITS = ("g", "kg", "mg", "seeds", "pcs", "ml", "litre")
FLAG_KEY = "seed_packet_warning_days"
DEFAULT_DAYS = [90, 30, 15, 7]


# ------------------------------------------------------------------ small helpers
def norm(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).casefold()


def clean_quantity(qty: float, unit: str, label: str = "Quantity") -> float:
    q = round(float(qty), 3)
    if q <= 0:
        raise HTTPException(status_code=400, detail=f"{label} must be more than 0")
    if q > MAX_QTY:
        raise HTTPException(status_code=400, detail=f"{label} is too large")
    if unit in WHOLE_UNITS and abs(q - round(q)) > 1e-9:
        raise HTTPException(status_code=400, detail=f"{label} for {unit} must be a whole number (use kg, g, litre or ml for fractions)")
    return float(round(q)) if unit in WHOLE_UNITS else q


def warning_days(db: Session) -> list[int]:
    row = db.query(SystemFlag).filter(SystemFlag.key == FLAG_KEY).first()
    try:
        days = sorted({int(x) for x in (row.value if row else "").split(",") if x.strip()}, reverse=True)
    except ValueError:
        days = []
    return [d for d in days if 0 < d <= 3650] or DEFAULT_DAYS


def bucket(days_left: int, periods: list[int]) -> Optional[int]:
    """The tightest warning period the batch has already entered (e.g. 20 days left -> 30)."""
    hit = [p for p in periods if days_left <= p]
    return min(hit) if hit else None


def batch_totals(db: Session, batch_ids: list[int]) -> dict:
    out = {i: {"received": 0.0, "used": 0.0, "adjusted": 0.0, "written_off": 0.0, "remaining": 0.0} for i in batch_ids}
    if not batch_ids:
        return out
    for bid, mtype, qty in db.query(SeedPacketMovement.batch_id, SeedPacketMovement.movement_type, func.sum(SeedPacketMovement.quantity)).filter(
            SeedPacketMovement.batch_id.in_(batch_ids)).group_by(SeedPacketMovement.batch_id, SeedPacketMovement.movement_type):
        t, q = out[bid], float(qty or 0)
        if mtype == "RECEIPT":
            t["received"] += q
        elif mtype == "USAGE":
            t["used"] += -q
        elif mtype == "EXPIRED_WRITEOFF":
            t["written_off"] += -q
        else:
            t["adjusted"] += q
        t["remaining"] += q
    for t in out.values():
        for k in t:
            t[k] = round(t[k], 3)
    return out


def batch_remaining(db: Session, batch_id: int) -> float:
    return round(float(db.query(func.coalesce(func.sum(SeedPacketMovement.quantity), 0)).filter(SeedPacketMovement.batch_id == batch_id).scalar() or 0), 3)


def batch_status(batch: SeedPacketBatch, remaining: float, today: date, periods: list[int]) -> tuple[str, Optional[int], Optional[int]]:
    if remaining <= 0:
        return "Empty", ((batch.expiry_date - today).days if batch.expiry_date else None), None
    if batch.expiry_date is None:
        return "OK", None, None  # no expiry to watch (fertilizers, supplies)
    days = (batch.expiry_date - today).days
    if days < 0:
        return "Expired", days, None
    b = bucket(days, periods)
    return ("Expiring soon" if b else "OK"), days, b


def plant_names(db: Session, ids) -> dict:
    return {i: n for i, n in db.query(Plant.id, Plant.name).filter(Plant.id.in_({x for x in ids if x} or {0}))}


def display_name(batch: SeedPacketBatch) -> str:
    return (batch.variety or batch.item_name or "").strip()


def batch_out(batch: SeedPacketBatch, totals: dict, names: dict, today: date, periods: list[int]) -> dict:
    t = totals.get(batch.id) or {"received": 0, "used": 0, "adjusted": 0, "written_off": 0, "remaining": 0}
    status, days, bk = batch_status(batch, t["remaining"], today, periods)
    kind = batch.item_kind or "seed_packet"
    return {
        "id": batch.id, "record_no": batch.record_no, "item_kind": kind, "kind_label": KIND_LABEL.get(kind, kind), "item_name": display_name(batch),
        "plant_id": batch.plant_id, "plant_name": names.get(batch.plant_id) if batch.plant_id else "Unassigned / General stock",
        "variety": batch.variety or "", "company": batch.company or "", "supplier": batch.supplier or "", "batch_number": batch.batch_number or "",
        "quantity_unit": batch.quantity_unit or "packets", "packet_size": batch.packet_size, "packet_unit": batch.packet_unit or "", "purchase_date": batch.purchase_date.isoformat(),
        "manufacturing_date": batch.manufacturing_date.isoformat() if batch.manufacturing_date else None, "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
        "storage_location": batch.storage_location or "", "notes": batch.notes or "", "attachment_url": batch.attachment_url or "",
        "received": t["received"], "used": t["used"], "adjusted": t["adjusted"], "written_off": t["written_off"], "remaining": t["remaining"],
        "status": status, "days_left": days, "warning_period": bk, "created_by": batch.created_by,
    }


# ------------------------------------------------------------------ suppliers and bills
def supplier_contact(db: Session, name: str, admin: str) -> Optional[Contact]:
    """An existing supplier with this exact name (any capitals), or a new supplier contact. Never touches customers."""
    name = re.sub(r"\s+", " ", (name or "").strip())
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


def find_duplicate_bill(db: Session, contact_id: int, bill_number: str, exclude_id: Optional[int] = None) -> Optional[Purchase]:
    """The same supplier bill number entered before for the same supplier (blank numbers are never duplicates)."""
    key = norm(bill_number)
    if not key:
        return None
    q = db.query(Purchase).filter(Purchase.contact_id == contact_id, Purchase.status.notin_(("Voided", "Cancelled")))
    if exclude_id:
        q = q.filter(Purchase.id != exclude_id)
    for p in q:
        if norm(p.invoice_number) == key:
            return p
    return None


def check_duplicate_bill(db: Session, contact: Contact, bill_number: str, override: bool, reason: str, exclude_id: Optional[int] = None) -> Optional[str]:
    """Raises 409 when this supplier already has this bill number. With an explicit override and a written reason it lets it
    through and returns the reason to be stored (audited on the bill)."""
    dup = find_duplicate_bill(db, contact.id, bill_number, exclude_id)
    if not dup:
        return None
    if override and len((reason or "").strip()) >= 5:
        return reason.strip()
    raise HTTPException(
        status_code=409,
        detail=f"DUPLICATE_BILL: Supplier {contact.name} already has bill number {dup.invoice_number} (Purchase #{dup.id}, {dup.purchase_date.strftime('%d %b %Y')}, "
               f"total {dup.total_cost:,.2f}). If it really is a second bill with the same number, confirm and write the reason.",
    )


# ------------------------------------------------------------------ one line: validate, then receive into a batch
def normalise_line(db: Session, raw: dict, purchase_date: date, label: str = "Item") -> dict:
    """Checks one supply line and returns clean values (raises 400 with a readable message). `raw` keys: item_kind, item_name, plant_id,
    company, lot_number, quantity, unit, unit_cost, total_cost, mfg_date, expiry_date, packet_size, packet_unit, storage_location, notes."""
    kind = raw.get("item_kind") or "seed_packet"
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"{label}: unknown item type")
    name = re.sub(r"\s+", " ", (raw.get("item_name") or "").strip())
    plant_id = raw.get("plant_id") or None
    if plant_id and kind != "seed_packet":
        raise HTTPException(status_code=400, detail=f"{label}: only seed packets are linked to a plant")
    plant = None
    if plant_id:
        plant = db.query(Plant).filter(Plant.id == plant_id).first()
        if not plant:
            raise HTTPException(status_code=400, detail=f"{label}: choose a plant from the list")
    if kind == "seed_packet":
        if not name and not plant:
            raise HTTPException(status_code=400, detail=f"{label}: write the seed name, or choose its plant")
        name = name or plant.name
    elif not name:
        raise HTTPException(status_code=400, detail=f"{label}: write what the item is")
    company = (raw.get("company") or "").strip()
    if kind == "seed_packet" and not company:
        raise HTTPException(status_code=400, detail=f"{label}: write the seed company / brand")
    lot = (raw.get("lot_number") or "").strip()
    if kind in LOT_REQUIRED and not lot:
        raise HTTPException(status_code=400, detail=f"{label}: the lot / batch number is required for {KIND_LABEL[kind].lower()}s")
    unit = (raw.get("unit") or DEFAULT_UNIT[kind]).strip().lower()
    if unit not in WHOLE_UNITS and unit not in DECIMAL_UNITS:
        raise HTTPException(status_code=400, detail=f"{label}: unknown unit {unit}")
    qty = clean_quantity(raw.get("quantity") or 0, unit, f"{label}: quantity")
    exp, mfg = raw.get("expiry_date"), raw.get("mfg_date")
    if kind in EXPIRY_REQUIRED and not exp:
        raise HTTPException(status_code=400, detail=f"{label}: the expiry date is required for {KIND_LABEL[kind].lower()}s")
    if exp:
        if not 2000 <= exp.year <= 2100:
            raise HTTPException(status_code=400, detail=f"{label}: expiry date is not a valid date")
        if exp < purchase_date:
            raise HTTPException(status_code=400, detail=f"{label}: the expiry date is before the purchase date. Check the date on the pack.")
    if mfg and exp and mfg > exp:
        raise HTTPException(status_code=400, detail=f"{label}: manufacturing date is after the expiry date")
    cost, total = raw.get("unit_cost"), raw.get("total_cost")
    for v, nm in ((cost, "unit cost"), (total, "total amount")):
        if v is not None and (v < 0 or v > MAX_MONEY):
            raise HTTPException(status_code=400, detail=f"{label}: {nm} is not valid")
    if total is None and cost is not None:
        total = round(cost * qty, 2)
    if cost is None and total is not None:
        cost = round(total / qty, 4)
    packet_unit = (raw.get("packet_unit") or "").strip()
    if kind == "seed_packet" and raw.get("packet_size") and packet_unit not in SIZE_UNITS:
        raise HTTPException(status_code=400, detail=f"{label}: unknown packet size unit")
    return {
        "item_kind": kind, "item_name": name, "plant_id": plant.id if plant else None, "plant": plant, "company": company, "lot_number": lot, "quantity": qty, "unit": unit,
        "unit_cost": cost, "total_cost": total, "mfg_date": mfg, "expiry_date": exp, "packet_size": raw.get("packet_size") or None, "packet_unit": packet_unit or ("g" if kind == "seed_packet" else ""),
        "storage_location": (raw.get("storage_location") or "").strip(), "notes": (raw.get("notes") or "").strip(),
    }


def find_batch(db: Session, spec: dict) -> Optional[SeedPacketBatch]:
    """The batch this exact lot already lives in: same kind, plant, item, company and lot (a lot-less item is told apart by its expiry)."""
    q = db.query(SeedPacketBatch).filter(SeedPacketBatch.item_kind == spec["item_kind"], func.lower(SeedPacketBatch.batch_number) == spec["lot_number"].lower())
    q = q.filter(SeedPacketBatch.plant_id == spec["plant_id"]) if spec["plant_id"] else q.filter(SeedPacketBatch.plant_id.is_(None))
    for b in q:
        if norm(display_name(b)) == norm(spec["item_name"]) and norm(b.company) == norm(spec["company"]):
            if not spec["lot_number"] and b.expiry_date != spec["expiry_date"]:
                continue
            return b
    return None


def receive_line(db: Session, *, spec: dict, purchase_date: date, supplier_text: str, bill_number: str, admin: str, line: Optional[PurchaseLine] = None,
                 purchase: Optional[Purchase] = None, request_id: Optional[str] = None, allow_merge: bool = True) -> tuple[SeedPacketBatch, SeedPacketMovement, bool]:
    """Puts the received quantity into its batch (a new one, or the existing batch of the same lot) and writes the RECEIPT movement.
    Never changes plant stock. The movement request_id is unique, so receiving the same line twice is impossible."""
    existing = find_batch(db, spec)
    merged = existing is not None
    if existing:
        if existing.expiry_date != spec["expiry_date"]:
            have = existing.expiry_date.isoformat() if existing.expiry_date else "no expiry"
            raise HTTPException(status_code=409, detail=f"Lot {spec['lot_number'] or '(no lot)'} of {spec['item_name']} already exists with {have}. A lot has one expiry date. Check the pack, or use a different lot number.")
        if (existing.quantity_unit or "packets") != spec["unit"]:
            raise HTTPException(status_code=409, detail=f"Lot {spec['lot_number']} of {spec['item_name']} is counted in {existing.quantity_unit}, but this receipt is in {spec['unit']}. Use the same unit.")
        if not allow_merge:
            rem = batch_remaining(db, existing.id)
            raise HTTPException(status_code=409, detail=f"BATCH_EXISTS: Lot {spec['lot_number']} of this item is already recorded ({existing.record_no}, {rem:g} {existing.quantity_unit} left). Add this quantity to that lot?")
        batch = existing
    else:
        batch = SeedPacketBatch(
            plant_id=spec["plant_id"], item_kind=spec["item_kind"], item_name=spec["item_name"], quantity_unit=spec["unit"],
            variety=spec["item_name"] if spec["item_kind"] == "seed_packet" else "", company=spec["company"], supplier=supplier_text, batch_number=spec["lot_number"],
            packet_size=spec["packet_size"], packet_unit=spec["packet_unit"], purchase_date=purchase_date, manufacturing_date=spec["mfg_date"], expiry_date=spec["expiry_date"],
            storage_location=spec["storage_location"], notes=spec["notes"], request_id=request_id or (f"PLINE:{line.id}" if line else f"B{purchase.id if purchase else 0}"),
            created_by=admin,
        )
        db.add(batch)
        db.flush()
        batch.record_no = f"SP-{batch.id}"
    move = SeedPacketMovement(
        batch_id=batch.id, movement_type="RECEIPT", quantity=spec["quantity"], reason=f"{KIND_LABEL[spec['item_kind']]} received" + (" (added to existing lot)" if merged else ""),
        unit_price=spec["unit_cost"], total_amount=spec["total_cost"], invoice_number=bill_number, supplier=supplier_text,
        purchase_id=purchase.id if purchase else None, purchase_line_id=line.id if line else None,
        request_id=(f"PLINE:{line.id}" if line else (request_id if merged else None)), performed_by=admin,
    )
    db.add(move)
    db.flush()
    return batch, move, merged


def create_supply_bill(db: Session, *, contact: Contact, bill_number: str, fallback_number: str, purchase_date: date, lines: list[dict], admin: str, request_id: Optional[str],
                       notes: str = "", override_duplicate: bool = False, override_reason: str = "", purchase_order_id: Optional[int] = None,
                       allow_merge: bool = True, extra_total: float = 0.0, purchase: Optional[Purchase] = None) -> Purchase:
    """Creates the supplier Bill (Unpaid) with all lines and receives every line into stock, in the caller's transaction.
    `lines` are normalised dicts (see normalise_line). The caller commits. Payment is recorded later in Accounting, Payments Out."""
    bill_number = (bill_number or "").strip()
    reason = check_duplicate_bill(db, contact, bill_number, override_duplicate, override_reason, exclude_id=purchase.id if purchase else None)
    if purchase is None:
        purchase = Purchase(
            purchase_date=datetime.combine(purchase_date, datetime.min.time()), supplier=contact.name, invoice_number=bill_number or fallback_number,
            notes=(notes or "").strip(), created_by=admin, request_id=request_id, status="Unpaid", contact_id=contact.id, purchase_order_id=purchase_order_id,
        )
        db.add(purchase)
        db.flush()
    if reason:
        purchase.duplicate_override_reason, purchase.duplicate_override_by = reason, admin
        record_change(db, "purchases", purchase.id, "update", changed_by=admin, changes={"duplicate_bill_override": (None, f"{bill_number}: {reason}")})
    total = float(extra_total or 0)
    supplier_text = contact.name
    for n, spec in enumerate(lines, 1):
        line = PurchaseLine(
            purchase_id=purchase.id, line_no=n, item_kind=spec["item_kind"], item_name=spec["item_name"], plant_id=spec["plant_id"], company=spec["company"], lot_number=spec["lot_number"],
            quantity=spec["quantity"], unit=spec["unit"], unit_cost=spec["unit_cost"] or 0, total_cost=spec["total_cost"] or 0, mfg_date=spec["mfg_date"], expiry_date=spec["expiry_date"],
            packet_size=spec["packet_size"], packet_unit=spec["packet_unit"], storage_location=spec["storage_location"], notes=spec["notes"],
        )
        db.add(line)
        db.flush()
        batch, _move, _merged = receive_line(db, spec=spec, purchase_date=purchase_date, supplier_text=supplier_text, bill_number=purchase.invoice_number if bill_number else "", admin=admin,
                                             line=line, purchase=purchase, allow_merge=allow_merge)
        line.batch_id = batch.id
        total += float(spec["total_cost"] or 0)
    purchase.total_cost = round(total, 2)
    return purchase
