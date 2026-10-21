"""Lines of a supplier Bill for things that are not plants: seed packets, medicines, fertilizers, other supplies.

A Bill (`purchases`) is the supplier's invoice and the supplier-ledger entry. It can have many lines, each with its own lot
number and expiry. The line is what created the stock receipt (see seed_packet_movements.purchase_line_id)."""
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from app.database import Base


class PurchaseLine(Base):
    __tablename__ = "purchase_lines"
    __table_args__ = (UniqueConstraint("purchase_id", "line_no", name="uq_purchase_line_no"),)

    id = Column(Integer, primary_key=True, index=True)
    purchase_id = Column(Integer, ForeignKey("purchases.id"), nullable=False, index=True)
    line_no = Column(Integer, nullable=False, default=1)
    item_kind = Column(String(20), nullable=False, default="seed_packet")  # seed_packet | medicine | fertilizer | supply
    item_name = Column(String(200), nullable=False, default="")
    plant_id = Column(Integer, ForeignKey("plants.id"), nullable=True, index=True)  # only for seed packets; NULL = unassigned
    company = Column(String(150), default="")
    lot_number = Column(String(80), default="")
    quantity = Column(Float, nullable=False, default=0)
    unit = Column(String(12), default="packets")
    unit_cost = Column(Float, nullable=False, default=0)
    total_cost = Column(Float, nullable=False, default=0)
    mfg_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True)
    packet_size = Column(Float, nullable=True)
    packet_unit = Column(String(10), default="")
    storage_location = Column(String(120), default="")
    notes = Column(Text, default="")
    batch_id = Column(Integer, ForeignKey("seed_packet_batches.id"), nullable=True, index=True)  # the stock batch this line was received into
    created_at = Column(DateTime, default=datetime.utcnow)
