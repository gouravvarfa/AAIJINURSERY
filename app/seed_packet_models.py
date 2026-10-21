"""Seed packets (and medicines, fertilizers, other supplies) bought from suppliers: one row per batch (lot), and an append-only
movement log. Quantities are NOT stored on the batch: received / used / adjusted / remaining
are always the sums of the movement log, so history can never disagree with the numbers.

Deliberately separate from plant stock (Plant.stock_quantity / inventory_transactions)."""
from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from app.database import Base

MOVEMENT_TYPES = ["RECEIPT", "USAGE", "ADJUSTMENT", "EXPIRED_WRITEOFF", "CORRECTION"]


class SeedPacketBatch(Base):
    __tablename__ = "seed_packet_batches"
    __table_args__ = (UniqueConstraint("request_id", name="uq_seed_packet_batch_request"),)

    id = Column(Integer, primary_key=True, index=True)
    record_no = Column(String(20), default="")
    # Which plant a seed packet is for. NULL = "Unassigned / General stock" (and for medicines, fertilizers and other supplies).
    plant_id = Column(Integer, ForeignKey("plants.id"), nullable=True, index=True)
    # seed_packet | medicine | fertilizer | supply
    item_kind = Column(String(20), nullable=False, default="seed_packet", index=True)
    item_name = Column(String(200), default="")  # what it is, e.g. "Chlorpyrifos" (seed packets use `variety`)
    quantity_unit = Column(String(12), default="packets")  # the unit the stock is counted in (packets, bottles, kg, litre ...)
    variety = Column(String(150), default="")
    company = Column(String(150), default="", index=True)
    supplier = Column(String(150), default="", index=True)
    batch_number = Column(String(80), nullable=False, index=True)
    packet_size = Column(Float, nullable=True)
    packet_unit = Column(String(10), default="g")
    purchase_date = Column(Date, nullable=False)
    manufacturing_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=False, index=True)
    storage_location = Column(String(120), default="")
    notes = Column(Text, default="")
    attachment_url = Column(String(300), default="")
    request_id = Column(String(60), nullable=False)
    created_by = Column(String(80), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class SeedPacketMovement(Base):
    __tablename__ = "seed_packet_movements"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_seed_packet_move_request"),
        Index("ix_seed_packet_move_batch", "batch_id", "id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("seed_packet_batches.id"), nullable=False)
    movement_type = Column(String(20), nullable=False, index=True)
    quantity = Column(Float, nullable=False, default=0)  # signed units: + in, - out, 0 for a status/detail correction (decimals for kg / litre)
    reason = Column(Text, default="")
    detail = Column(Text, default="")  # e.g. "expiry 2026-11-15 -> 2026-12-01"
    is_exception = Column(Boolean, nullable=False, default=False)  # used although expired, by an authorised admin
    # Purchase details (RECEIPT only)
    unit_price = Column(Float, nullable=True)
    total_amount = Column(Float, nullable=True)
    invoice_number = Column(String(80), default="")
    supplier = Column(String(150), default="")
    expense_id = Column(Integer, nullable=True)  # older receipts only: the expense that was booked before bills were used
    purchase_id = Column(Integer, nullable=True, index=True)  # the supplier Bill this receipt came from
    purchase_line_id = Column(Integer, nullable=True)
    request_id = Column(String(60), nullable=True)
    performed_by = Column(String(80), default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class SeedPacketAlertLog(Base):
    """One row per batch and warning period, so the same alert is announced only once."""

    __tablename__ = "seed_packet_alert_log"
    __table_args__ = (UniqueConstraint("batch_id", "alert_key", name="uq_seed_packet_alert"),)

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(Integer, ForeignKey("seed_packet_batches.id"), nullable=False, index=True)
    alert_key = Column(String(20), nullable=False)  # d90 | d30 | d15 | d7 | expired
    first_seen_at = Column(DateTime, default=datetime.utcnow)
