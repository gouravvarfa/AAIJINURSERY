"""Plant History: everything that ever happened around one plant, in one place.

Read only. Ready-to-sell stock (inventory ledger), plant purchases, the seed packets linked to the plant (with supplier,
purchase date, lot, quantity, expiry and the supplier bill number), the packet stock movements, and customers' seeds."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import InventoryTransaction, Plant, PlantVariant, Purchase, PurchaseItem
from app.permissions import require_permission
from app.production_models import SeedEntry
from app.seed_packet_models import SeedPacketBatch, SeedPacketMovement
from app.seed_packets import movement_rows
from app.supply_inventory import batch_out, batch_totals, plant_names, warning_days

router = APIRouter(prefix="/api/admin/plants", tags=["plant-history"])


@router.get("/{plant_id}/history", dependencies=[Depends(require_permission("products", "VIEW"))])
def plant_history(plant_id: int, db: Session = Depends(get_db)):
    plant = db.query(Plant).filter(Plant.id == plant_id).first()
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")
    variants = db.query(PlantVariant).filter(PlantVariant.plant_id == plant.id).all()
    today, periods = date.today(), warning_days(db)

    # ---- seed packets linked to this plant: every lot, with each receipt (supplier, date, qty, bill number)
    batches = db.query(SeedPacketBatch).filter(SeedPacketBatch.plant_id == plant.id).order_by(SeedPacketBatch.id.desc()).all()
    totals = batch_totals(db, [b.id for b in batches])
    names = plant_names(db, [plant.id])
    packets = []
    for b in batches:
        row = batch_out(b, totals, names, today, periods)
        receipts = db.query(SeedPacketMovement).filter(SeedPacketMovement.batch_id == b.id, SeedPacketMovement.movement_type == "RECEIPT").order_by(SeedPacketMovement.id).all()
        row["receipts"] = [{"at": m.created_at.isoformat() + "Z", "quantity": m.quantity, "unit": b.quantity_unit or "packets", "supplier": m.supplier or b.supplier or "", "bill_number": m.invoice_number or "",
                            "purchase_id": m.purchase_id, "total_amount": m.total_amount, "purchase_date": b.purchase_date.isoformat()} for m in receipts]
        packets.append(row)
    movement_pairs = (
        db.query(SeedPacketMovement, SeedPacketBatch)
        .join(SeedPacketBatch, SeedPacketBatch.id == SeedPacketMovement.batch_id)
        .filter(SeedPacketBatch.plant_id == plant.id)
        .order_by(SeedPacketMovement.id.desc())
        .limit(200)
        .all()
    )

    stock = [{"id": t.id, "at": t.created_at.isoformat() + "Z", "type": t.transaction_type, "quantity": t.quantity, "before": t.before_quantity, "after": t.after_quantity, "variant_id": t.variant_id,
              "source": f"{t.source_type or ''} {t.source_id or ''}".strip(), "by": t.created_by, "notes": t.notes or ""}
             for t in db.query(InventoryTransaction).filter(InventoryTransaction.plant_id == plant.id).order_by(InventoryTransaction.id.desc()).limit(200)]

    purchases = [{"purchase_id": p.id, "date": p.purchase_date.isoformat(), "supplier": p.supplier or "", "bill_number": p.invoice_number or "", "status": p.status, "quantity": i.quantity,
                  "unit_cost": i.unit_cost, "total_cost": i.total_cost}
                 for i, p in db.query(PurchaseItem, Purchase).join(Purchase, Purchase.id == PurchaseItem.purchase_id).filter(PurchaseItem.plant_id == plant.id).order_by(Purchase.purchase_date.desc()).limit(100)]

    seeds = [{"id": e.id, "entry_number": e.entry_number, "customer": e.customer_name, "date": e.entry_date.date().isoformat(), "seeds_given": e.seeds_given, "wanted_plants": e.wanted_plants,
              "good_for_customer": e.prepared_plants, "extra": e.extra_plants, "bad": e.rejected_plants, "status": e.status, "handed_over": e.handed_over_at is not None}
             for e in db.query(SeedEntry).filter(SeedEntry.plant_id == plant.id).order_by(SeedEntry.id.desc()).limit(100)]

    return {
        "plant": {"id": plant.id, "name": plant.name, "slug": plant.slug, "is_active": bool(plant.is_active), "category_id": plant.category_id, "ready_stock": plant.stock_quantity or 0,
                  "variants": [{"id": v.id, "tray_size": v.tray_size, "stock": v.stock_quantity} for v in variants]},
        "packets": packets,
        "packet_totals": {"lots": len(packets), "remaining_lots": sum(1 for r in packets if r["remaining"] > 0), "expired": sum(1 for r in packets if r["status"] == "Expired" and r["remaining"] > 0)},
        "packet_movements": movement_rows(db, movement_pairs),
        "stock_movements": stock,
        "plant_purchases": purchases,
        "customer_seeds": seeds,
    }
