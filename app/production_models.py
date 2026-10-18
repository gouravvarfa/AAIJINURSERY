"""Seed stock and plant-production batches.

Ready-to-sell plants stay where they always were (Plant / PlantVariant
.stock_quantity, with the inventory_transactions ledger). This module only adds
what sits *before* that: seeds, and the batches that turn seeds into ready
plants. A finished batch moves its accepted plants into the ready stock through
the normal inventory service (reference "BATCH:<id>:ACCEPT"), so there is still
exactly one ready-stock number per plant / tray.

Seed balance: ISSUED lowers it, RECEIVED / RETURNED raise it. CONSUMED and
WASTED (batch level) are recorded for the audit trail but do not change the
balance again -- the seeds already left stock when they were issued.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.database import Base

BATCH_STATUSES = ["Draft", "In Progress", "Completed", "Cancelled"]
OPEN_BATCH_STATUSES = ("Draft", "In Progress")


class SeedItem(Base):
    __tablename__ = "seed_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, unique=True)
    plant_id = Column(Integer, ForeignKey("plants.id"), nullable=True, index=True)  # the variety this seed grows into
    unit = Column(String(20), nullable=False, default="seeds")
    quantity = Column(Integer, nullable=False, default=0)  # balance in the seed store
    notes = Column(Text, default="")
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(80), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class SeedMovement(Base):
    """Append-only seed ledger. `reference` is a unique idempotency key."""

    __tablename__ = "seed_movements"
    __table_args__ = (UniqueConstraint("reference", name="uq_seed_movement_reference"),)

    id = Column(Integer, primary_key=True, index=True)
    seed_item_id = Column(Integer, ForeignKey("seed_items.id"), nullable=False, index=True)
    movement_type = Column(String(20), nullable=False)  # RECEIVED ISSUED RETURNED CONSUMED WASTED DAMAGED
    quantity = Column(Integer, nullable=False)  # always positive
    before_quantity = Column(Integer, nullable=False)
    after_quantity = Column(Integer, nullable=False)
    source_type = Column(String(30), default="")
    source_id = Column(String(40), default="")
    reference = Column(String(120), nullable=True)
    notes = Column(Text, default="")
    created_by = Column(String(80), default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ProductionBatch(Base):
    __tablename__ = "production_batches"

    id = Column(Integer, primary_key=True, index=True)
    batch_number = Column(String(30), default="")
    plant_id = Column(Integer, ForeignKey("plants.id"), nullable=False, index=True)
    variant_id = Column(Integer, nullable=True, index=True)  # tray option the output goes to (None = plain plant)
    tray_size = Column(Integer, nullable=True)  # snapshot of that tray's size
    seed_item_id = Column(Integer, ForeignKey("seed_items.id"), nullable=True, index=True)
    planned_quantity = Column(Integer, nullable=False, default=0)  # PLANTS the team intends to produce
    status = Column(String(20), nullable=False, default="Draft", index=True)

    seeds_issued = Column(Integer, nullable=False, default=0)
    seeds_consumed = Column(Integer, nullable=False, default=0)
    seeds_returned = Column(Integer, nullable=False, default=0)
    seeds_wasted = Column(Integer, nullable=False, default=0)

    healthy_plants = Column(Integer, nullable=False, default=0)
    rejected_plants = Column(Integer, nullable=False, default=0)
    accepted_plants = Column(Integer, nullable=False, default=0)  # passed quality checks
    accepted_units = Column(Integer, nullable=False, default=0)  # what was added to ready stock (trays or plants)
    loose_plants = Column(Integer, nullable=False, default=0)  # accepted plants that did not fill a whole tray

    notes = Column(Text, default="")
    created_by = Column(String(80), default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    completed_by = Column(String(80), default="")


class ProductionBatchOrder(Base):
    """Which order lines a batch is meant for (information; allocation stays an admin decision)."""

    __tablename__ = "production_batch_orders"
    __table_args__ = (UniqueConstraint("batch_id", "kind", "item_id", name="uq_batch_order_line"),)

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("production_batches.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)  # order | sales_order
    item_id = Column(Integer, nullable=False)


class SeedEntry(Base):
    """A customer visits and hands over seeds to be grown for them. The seeds are the
    customer's (not the nursery's seed store), so nothing is deducted from stock. The
    entry is saved at once as "seeds given / production pending" and is updated later
    with the plants that were prepared. Extra usable plants (beyond what the customer
    needs) go into ready stock through the normal ledger."""

    __tablename__ = "seed_entries"
    __table_args__ = (UniqueConstraint("request_id", name="uq_seed_entry_request"),)

    id = Column(Integer, primary_key=True, index=True)
    entry_number = Column(String(20), default="")
    request_id = Column(String(60), nullable=False)  # one id per form, so a double click saves once
    contact_id = Column(Integer, ForeignKey("accounting_contacts.id"), nullable=False, index=True)
    customer_name = Column(String(150), default="")  # snapshot
    plant_id = Column(Integer, ForeignKey("plants.id"), nullable=False, index=True)
    variant_id = Column(Integer, nullable=True)
    tray_size = Column(Integer, nullable=True)
    seeds_given = Column(Integer, nullable=False, default=0)
    # How many plants the customer wants (optional). Good plants up to this number are kept for the customer,
    # anything more is extra and goes to Ready now.
    wanted_plants = Column(Integer, nullable=True)
    # Set when the plants were given to the customer. Until then they are held in the nursery (shown in Stock as Allocated).
    handed_over_at = Column(DateTime, nullable=True)
    prepared_plants = Column(Integer, nullable=False, default=0)  # healthy plants made for the customer (running total)
    extra_plants = Column(Integer, nullable=False, default=0)  # extra usable plants -> ready stock (running total)
    extra_units_added = Column(Integer, nullable=False, default=0)  # what has already gone into ready stock (trays or plants)
    rejected_plants = Column(Integer, nullable=False, default=0)  # dead / not usable, incl. seeds that never grew
    status = Column(String(20), nullable=False, default="Pending", index=True)  # Pending | In Progress | Completed
    entry_date = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    reference = Column(String(80), default="")
    notes = Column(Text, default="")
    created_by = Column(String(80), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class SeedEntryUpdate(Base):
    __tablename__ = "seed_entry_updates"
    __table_args__ = (UniqueConstraint("request_id", name="uq_seed_entry_update_request"),)

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(Integer, ForeignKey("seed_entries.id"), nullable=False, index=True)
    request_id = Column(String(60), nullable=False)
    prepared_add = Column(Integer, nullable=False, default=0)
    extra_add = Column(Integer, nullable=False, default=0)
    rejected_add = Column(Integer, nullable=False, default=0)
    finished = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, default="")
    created_by = Column(String(80), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
