from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.accounting.models import Contact, SalesOrder, SalesOrderItem
from app.database import get_db
from app.delivery.models import Delivery, DeliveryItem, DeliveryTrip, Driver, Vehicle, VehicleFuelLog, record_delivery_event
from app.delivery.permissions import require_roles
from app.delivery.schemas import (
    DeliveryAssignIn,
    DeliveryCompleteIn,
    DeliveryDashboardOut,
    DeliveryIn,
    DeliveryOut,
    DeliveryStatusIn,
)
from app.delivery.notifications import queue_delivery_assigned_to_driver, queue_delivery_event
from app.deps import get_current_admin

router = APIRouter(prefix="/deliveries", tags=["delivery-deliveries"])

TERMINAL_STATUSES = {"Delivered", "Partially Delivered", "Failed", "Cancelled"}
COMPLETED_STATUSES = {"Delivered", "Partially Delivered"}


def _get_or_404(db: Session, item_id: int) -> Delivery:
    item = (
        db.query(Delivery)
        .options(
            joinedload(Delivery.contact), joinedload(Delivery.driver),
            joinedload(Delivery.vehicle), joinedload(Delivery.items),
        )
        .filter(Delivery.id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return item


def _with_total(delivery: Delivery) -> DeliveryOut:
    out = DeliveryOut.model_validate(delivery)
    out.total_quantity = sum(i.ordered_quantity for i in delivery.items)
    return out


@router.get("", response_model=list[DeliveryOut])
def list_deliveries(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    driver_id: Optional[int] = Query(None),
    vehicle_id: Optional[int] = Query(None),
    contact_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search by delivery #, customer name, or mobile"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Delivery).options(
        joinedload(Delivery.contact), joinedload(Delivery.driver),
        joinedload(Delivery.vehicle), joinedload(Delivery.items),
    )
    if date_from:
        query = query.filter(Delivery.delivery_date >= date_from)
    if date_to:
        query = query.filter(Delivery.delivery_date <= date_to)
    if driver_id:
        query = query.filter(Delivery.driver_id == driver_id)
    if vehicle_id:
        query = query.filter(Delivery.vehicle_id == vehicle_id)
    if contact_id:
        query = query.filter(Delivery.contact_id == contact_id)
    if status:
        query = query.filter(Delivery.status == status)
    if source in ("online", "offline"):
        query = query.filter(Delivery.source == source)
    if q:
        like = f"%{q}%"
        query = query.join(Contact, Contact.id == Delivery.contact_id).filter(
            Delivery.delivery_number.ilike(like) | Delivery.customer_mobile.ilike(like) | Contact.name.ilike(like)
        )
    deliveries = query.order_by(Delivery.delivery_date.desc()).all()
    return [_with_total(d) for d in deliveries]


@router.get("/dashboard", response_model=DeliveryDashboardOut)
def delivery_dashboard(
    date: Optional[datetime] = Query(None, description="defaults to today"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    day = (date or datetime.utcnow()).replace(hour=0, minute=0, second=0, microsecond=0)
    next_day = day + timedelta(days=1)

    deliveries = (
        db.query(Delivery)
        .options(joinedload(Delivery.items))
        .filter(Delivery.delivery_date >= day, Delivery.delivery_date < next_day)
        .all()
    )
    total_deliveries = len(deliveries)
    completed = sum(1 for d in deliveries if d.status in COMPLETED_STATUSES)
    cancelled = sum(1 for d in deliveries if d.status == "Cancelled")
    pending = total_deliveries - completed - cancelled
    vehicles_on_route = len({d.vehicle_id for d in deliveries if d.vehicle_id and d.status not in TERMINAL_STATUSES})
    total_quantity = sum(sum(i.ordered_quantity for i in d.items) for d in deliveries)

    trips_today = db.query(DeliveryTrip).filter(DeliveryTrip.trip_date >= day, DeliveryTrip.trip_date < next_day).all()
    total_km = round(sum(t.total_km or 0 for t in trips_today), 2)

    fuel_today = (
        db.query(func.coalesce(func.sum(VehicleFuelLog.litres), 0))
        .filter(VehicleFuelLog.date >= day, VehicleFuelLog.date < next_day)
        .scalar()
        or 0
    )

    return DeliveryDashboardOut(
        date_label=day.strftime("%d %b %Y"),
        total_deliveries=total_deliveries,
        vehicles_on_route=vehicles_on_route,
        completed=completed,
        pending=max(pending, 0),
        cancelled=cancelled,
        total_quantity=total_quantity,
        total_km=total_km,
        fuel_used_litres=round(fuel_today, 2),
    )


@router.get("/{item_id}", response_model=DeliveryOut)
def get_delivery(item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _with_total(_get_or_404(db, item_id))


@router.post("", response_model=DeliveryOut, status_code=201)
def create_delivery(
    payload: DeliveryIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("CREATE")),
    db: Session = Depends(get_db),
):
    contact = db.query(Contact).filter(Contact.id == payload.contact_id).first()
    if not contact:
        raise HTTPException(status_code=400, detail="Unknown party/customer")

    sales_order = None
    if payload.sales_order_id:
        sales_order = (
            db.query(SalesOrder)
            .options(joinedload(SalesOrder.items))
            .filter(SalesOrder.id == payload.sales_order_id)
            .first()
        )
        if not sales_order:
            raise HTTPException(status_code=400, detail="Unknown sales order")

    if payload.driver_id:
        driver = db.query(Driver).filter(Driver.id == payload.driver_id).first()
        if not driver or driver.status != "Active":
            raise HTTPException(status_code=400, detail="Selected driver is not available")
    if payload.vehicle_id:
        vehicle = db.query(Vehicle).filter(Vehicle.id == payload.vehicle_id).first()
        if not vehicle or vehicle.status == "Inactive":
            raise HTTPException(status_code=400, detail="Selected vehicle is not available")

    delivery = Delivery(
        delivery_date=payload.delivery_date,
        expected_time=payload.expected_time,
        contact_id=contact.id,
        customer_mobile=payload.customer_mobile or contact.phone,
        delivery_address=payload.delivery_address or contact.address,
        sales_order_id=payload.sales_order_id,
        invoice_id=payload.invoice_id,
        driver_id=payload.driver_id,
        vehicle_id=payload.vehicle_id,
        status="Assigned" if (payload.driver_id and payload.vehicle_id) else "Ready",
        source=sales_order.source if sales_order else "offline",
        notes=payload.notes,
        created_by=admin,
    )
    db.add(delivery)
    db.flush()
    delivery.delivery_number = f"DEL-{delivery.id}"
    record_delivery_event(db, delivery.id, "CREATED", None, delivery.status, admin)
    if payload.driver_id:
        record_delivery_event(db, delivery.id, "DRIVER_ASSIGNED", None, payload.driver_id, admin)
    if payload.vehicle_id:
        record_delivery_event(db, delivery.id, "VEHICLE_ASSIGNED", None, payload.vehicle_id, admin)

    items = payload.items
    if not items and sales_order:
        # Auto-pull from the Sales Order -- never modifies the original.
        for line in sales_order.items:
            db.add(DeliveryItem(
                delivery_id=delivery.id, plant_id=line.plant_id, description=line.description,
                ordered_quantity=line.quantity,
            ))
    else:
        for line in items:
            if line.ordered_quantity < 0:
                raise HTTPException(status_code=400, detail="Quantity cannot be negative")
            db.add(DeliveryItem(
                delivery_id=delivery.id, plant_id=line.plant_id, description=line.description,
                unit=line.unit, ordered_quantity=line.ordered_quantity, notes=line.notes,
            ))

    db.commit()
    result = _get_or_404(db, delivery.id)
    queue_delivery_event(result)
    if result.driver_id:
        queue_delivery_assigned_to_driver(result)
    return _with_total(result)


@router.put("/{item_id}/assign", response_model=DeliveryOut)
def assign_delivery(
    item_id: int,
    payload: DeliveryAssignIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("EDIT")),
    db: Session = Depends(get_db),
):
    delivery = _get_or_404(db, item_id)
    if payload.driver_id is not None:
        driver = db.query(Driver).filter(Driver.id == payload.driver_id).first()
        if not driver or driver.status != "Active":
            raise HTTPException(status_code=400, detail="Selected driver is not available")
        if delivery.driver_id != payload.driver_id:
            record_delivery_event(db, delivery.id, "DRIVER_ASSIGNED", delivery.driver_id, payload.driver_id, admin)
        delivery.driver_id = payload.driver_id
    if payload.vehicle_id is not None:
        vehicle = db.query(Vehicle).filter(Vehicle.id == payload.vehicle_id).first()
        if not vehicle or vehicle.status == "Inactive":
            raise HTTPException(status_code=400, detail="Selected vehicle is not available")
        if delivery.vehicle_id != payload.vehicle_id:
            record_delivery_event(db, delivery.id, "VEHICLE_ASSIGNED", delivery.vehicle_id, payload.vehicle_id, admin)
        delivery.vehicle_id = payload.vehicle_id
    if delivery.driver_id and delivery.vehicle_id and delivery.status == "Ready":
        record_delivery_event(db, delivery.id, "STATUS_CHANGED", delivery.status, "Assigned", admin)
        delivery.status = "Assigned"
    db.commit()
    result = _get_or_404(db, item_id)
    queue_delivery_event(result)
    if result.driver_id:
        queue_delivery_assigned_to_driver(result)
    return _with_total(result)


@router.put("/{item_id}/status", response_model=DeliveryOut)
def update_delivery_status(
    item_id: int,
    payload: DeliveryStatusIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("EDIT")),
    db: Session = Depends(get_db),
):
    from app.delivery.models import DELIVERY_STATUSES

    delivery = _get_or_404(db, item_id)
    if payload.status not in DELIVERY_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if delivery.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"This delivery is already {delivery.status} and can't be changed")
    record_delivery_event(db, delivery.id, "STATUS_CHANGED", delivery.status, payload.status, admin)
    delivery.status = payload.status
    db.commit()
    result = _get_or_404(db, item_id)
    queue_delivery_event(result)
    return _with_total(result)


@router.post("/{item_id}/complete", response_model=DeliveryOut)
def complete_delivery(
    item_id: int,
    payload: DeliveryCompleteIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("EDIT")),
    db: Session = Depends(get_db),
):
    delivery = _get_or_404(db, item_id)
    if delivery.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"This delivery is already {delivery.status}")

    items_by_id = {i.id: i for i in delivery.items}
    fully_delivered = True
    for entry in payload.items:
        item = items_by_id.get(entry.item_id)
        if not item:
            raise HTTPException(status_code=400, detail=f"Unknown delivery item {entry.item_id}")
        if entry.delivered_quantity < 0:
            raise HTTPException(status_code=400, detail="Delivered quantity cannot be negative")
        item.delivered_quantity = entry.delivered_quantity
        if entry.delivered_quantity < item.ordered_quantity:
            fully_delivered = False

    new_status = "Delivered" if fully_delivered else "Partially Delivered"
    record_delivery_event(db, delivery.id, "COMPLETED", delivery.status, new_status, admin, payload.remarks)
    delivery.status = new_status
    delivery.delivery_remarks = payload.remarks
    delivery.proof_photo_url = payload.proof_photo_url
    delivery.proof_signature_note = payload.proof_signature_note
    db.commit()
    result = _get_or_404(db, item_id)
    queue_delivery_event(result)
    return _with_total(result)
