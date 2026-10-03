"""Delivery Management module (Phase A + B of the master prompt).

Reuses existing tables wherever a delivery needs to reference one --
Contact (Party), SalesOrder, Invoice, Plant -- via plain foreign keys,
exactly like the Accounting and Labour modules do. Nothing here
duplicates customer/order/item data, and no existing table is modified.

Driver Portal auth (Phase C) is deliberately out of scope here; the
Driver model already carries username/hashed_password columns so no
later migration is needed, but no login endpoint exists yet.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base

DRIVER_STATUSES = ["Active", "Inactive", "On Leave"]
VEHICLE_STATUSES = ["Available", "On Trip", "Maintenance", "Inactive"]
VEHICLE_FUEL_TYPES = ["Petrol", "Diesel", "CNG", "Electric"]
DELIVERY_STATUSES = [
    "Assigned", "Ready", "Out for Delivery", "Arrived",
    "Delivered", "Partially Delivered", "Failed", "Cancelled",
]
TRIP_STATUSES = ["Ongoing", "Completed"]
PAYMENT_METHODS = ["Cash", "Card", "UPI", "Company Account", "Other"]


class Driver(Base):
    __tablename__ = "delivery_drivers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    phone = Column(String(30), default="")
    username = Column(String(80), unique=True, nullable=True)
    hashed_password = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, default="Active", index=True)
    assigned_vehicle_id = Column(Integer, ForeignKey("delivery_vehicles.id"), nullable=True)
    joining_date = Column(DateTime, nullable=True)
    address = Column(Text, default="")
    emergency_contact = Column(String(30), default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    assigned_vehicle = relationship("Vehicle", foreign_keys=[assigned_vehicle_id])


class Vehicle(Base):
    __tablename__ = "delivery_vehicles"

    id = Column(Integer, primary_key=True, index=True)
    registration_number = Column(String(30), nullable=False, unique=True)
    name_model = Column(String(150), default="")
    vehicle_type = Column(String(50), default="")
    fuel_type = Column(String(20), default="Petrol")
    status = Column(String(20), nullable=False, default="Available", index=True)
    current_km_reading = Column(Float, default=0)
    insurance_expiry = Column(DateTime, nullable=True)
    puc_expiry = Column(DateTime, nullable=True)
    service_due = Column(DateTime, nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class DeliveryTrip(Base):
    """One vehicle's daily run -- carries multiple Deliveries."""

    __tablename__ = "delivery_trips"

    id = Column(Integer, primary_key=True, index=True)
    trip_number = Column(String(40), default="")
    trip_date = Column(DateTime, nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("delivery_vehicles.id"), nullable=False, index=True)
    driver_id = Column(Integer, ForeignKey("delivery_drivers.id"), nullable=False, index=True)
    start_km = Column(Float, nullable=False, default=0)
    start_time = Column(DateTime, nullable=True)
    end_km = Column(Float, nullable=True)
    end_time = Column(DateTime, nullable=True)
    total_km = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default="Ongoing", index=True)
    created_by = Column(String(80), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    vehicle = relationship("Vehicle")
    driver = relationship("Driver")
    deliveries = relationship("Delivery", back_populates="trip")


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, index=True)
    delivery_number = Column(String(40), default="")
    delivery_date = Column(DateTime, nullable=False, index=True)
    expected_time = Column(String(20), default="")  # free-text e.g. "10:00 AM - 12:00 PM"

    contact_id = Column(Integer, ForeignKey("accounting_contacts.id"), nullable=True, index=True)
    customer_mobile = Column(String(30), default="")  # snapshot at creation time
    delivery_address = Column(Text, default="")

    sales_order_id = Column(Integer, ForeignKey("accounting_sales_orders.id"), nullable=True, index=True)
    invoice_id = Column(Integer, ForeignKey("accounting_invoices.id"), nullable=True, index=True)

    driver_id = Column(Integer, ForeignKey("delivery_drivers.id"), nullable=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("delivery_vehicles.id"), nullable=True, index=True)
    trip_id = Column(Integer, ForeignKey("delivery_trips.id"), nullable=True, index=True)

    status = Column(String(30), nullable=False, default="Assigned", index=True)
    source = Column(String(10), nullable=False, default="offline", index=True)
    notes = Column(Text, default="")

    proof_signature_note = Column(Text, default="")  # text/base64 placeholder -- no file storage yet
    proof_photo_url = Column(String(300), default="")
    delivery_remarks = Column(Text, default="")

    created_by = Column(String(80), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    contact = relationship("Contact")
    sales_order = relationship("SalesOrder")
    invoice = relationship("Invoice")
    driver = relationship("Driver")
    vehicle = relationship("Vehicle")
    trip = relationship("DeliveryTrip", back_populates="deliveries")
    items = relationship("DeliveryItem", back_populates="delivery", cascade="all, delete-orphan")


class DeliveryItem(Base):
    __tablename__ = "delivery_items"

    id = Column(Integer, primary_key=True, index=True)
    delivery_id = Column(Integer, ForeignKey("deliveries.id"), nullable=False, index=True)
    plant_id = Column(Integer, ForeignKey("plants.id"), nullable=True)
    description = Column(String(200), default="")
    unit = Column(String(20), default="pcs")
    ordered_quantity = Column(Integer, default=0)
    delivered_quantity = Column(Integer, nullable=True)  # filled in at completion
    notes = Column(Text, default="")

    delivery = relationship("Delivery", back_populates="items")
    plant = relationship("Plant")


class VehicleFuelLog(Base):
    __tablename__ = "delivery_fuel_logs"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("delivery_vehicles.id"), nullable=False, index=True)
    driver_id = Column(Integer, ForeignKey("delivery_drivers.id"), nullable=True, index=True)
    fuel_type = Column(String(20), default="Petrol")
    litres = Column(Float, nullable=False, default=0)
    rate_per_litre = Column(Float, nullable=False, default=0)
    total_amount = Column(Float, default=0)  # litres * rate, computed at write time
    odometer_reading = Column(Float, nullable=True)
    petrol_pump = Column(String(150), default="")
    payment_method = Column(String(30), default="Cash")
    receipt_reference = Column(String(120), default="")
    notes = Column(Text, default="")
    created_by = Column(String(80), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    vehicle = relationship("Vehicle")
    driver = relationship("Driver")


class DeliveryStatusHistory(Base):
    """Append-only who/when trail for a Delivery -- the Delivery row itself
    is mutated in place (driver, vehicle, status) with no actor, so every
    such mutation also writes one row here. Only covers changes made after
    this table was introduced; earlier events have no record."""

    __tablename__ = "delivery_status_history"

    id = Column(Integer, primary_key=True, index=True)
    delivery_id = Column(Integer, ForeignKey("deliveries.id"), nullable=False, index=True)
    event = Column(String(30), nullable=False)  # CREATED | DRIVER_ASSIGNED | VEHICLE_ASSIGNED | STATUS_CHANGED | COMPLETED
    old_value = Column(String(120), nullable=True)
    new_value = Column(String(120), nullable=True)
    changed_by = Column(String(80), default="")
    remarks = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


def record_delivery_event(db, delivery_id: int, event: str, old_value=None, new_value=None, changed_by: str = "", remarks: str = ""):
    db.add(
        DeliveryStatusHistory(
            delivery_id=delivery_id,
            event=event,
            old_value=None if old_value is None else str(old_value),
            new_value=None if new_value is None else str(new_value),
            changed_by=changed_by,
            remarks=remarks or "",
        )
    )
