from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.delivery.models import Delivery, DeliveryTrip, Driver, Vehicle
from app.delivery.permissions import require_roles
from app.delivery.schemas import TripEndIn, TripOut, TripStartIn
from app.delivery.trip_notifications import queue_trip_assigned_to_driver
from app.deps import get_current_admin

router = APIRouter(prefix="/trips", tags=["delivery-trips"])


def _get_or_404(db: Session, item_id: int) -> DeliveryTrip:
    item = (
        db.query(DeliveryTrip)
        .options(joinedload(DeliveryTrip.vehicle), joinedload(DeliveryTrip.driver))
        .filter(DeliveryTrip.id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Trip not found")
    return item


def _with_count(db: Session, trip: DeliveryTrip) -> TripOut:
    out = TripOut.model_validate(trip)
    out.delivery_count = db.query(Delivery).filter(Delivery.trip_id == trip.id).count()
    return out


@router.get("", response_model=list[TripOut])
def list_trips(
    vehicle_id: Optional[int] = Query(None),
    driver_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(DeliveryTrip).options(joinedload(DeliveryTrip.vehicle), joinedload(DeliveryTrip.driver))
    if vehicle_id:
        query = query.filter(DeliveryTrip.vehicle_id == vehicle_id)
    if driver_id:
        query = query.filter(DeliveryTrip.driver_id == driver_id)
    if status:
        query = query.filter(DeliveryTrip.status == status)
    if date_from:
        query = query.filter(DeliveryTrip.trip_date >= date_from)
    if date_to:
        query = query.filter(DeliveryTrip.trip_date <= date_to)
    trips = query.order_by(DeliveryTrip.trip_date.desc()).all()
    return [_with_count(db, t) for t in trips]


@router.get("/{item_id}", response_model=TripOut)
def get_trip(item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _with_count(db, _get_or_404(db, item_id))


@router.post("/start", response_model=TripOut, status_code=201)
def start_trip(
    payload: TripStartIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("CREATE")),
    db: Session = Depends(get_db),
):
    vehicle = db.query(Vehicle).filter(Vehicle.id == payload.vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=400, detail="Unknown vehicle")
    if vehicle.status == "Inactive":
        raise HTTPException(status_code=400, detail="This vehicle is inactive and cannot be assigned")

    driver = db.query(Driver).filter(Driver.id == payload.driver_id).first()
    if not driver:
        raise HTTPException(status_code=400, detail="Unknown driver")
    if driver.status != "Active":
        raise HTTPException(status_code=400, detail="This driver is not active and cannot be assigned")

    if db.query(DeliveryTrip).filter(DeliveryTrip.vehicle_id == vehicle.id, DeliveryTrip.status == "Ongoing").first():
        raise HTTPException(status_code=400, detail="This vehicle already has an ongoing trip")
    if db.query(DeliveryTrip).filter(DeliveryTrip.driver_id == driver.id, DeliveryTrip.status == "Ongoing").first():
        raise HTTPException(status_code=400, detail="This driver already has an ongoing trip")

    if payload.start_km < 0:
        raise HTTPException(status_code=400, detail="Starting KM cannot be negative")
    if payload.start_km < vehicle.current_km_reading:
        raise HTTPException(
            status_code=400,
            detail=f"Starting KM ({payload.start_km}) is less than the vehicle's last known reading ({vehicle.current_km_reading})",
        )

    trip = DeliveryTrip(
        trip_date=payload.trip_date,
        vehicle_id=vehicle.id,
        driver_id=driver.id,
        start_km=payload.start_km,
        start_time=payload.start_time or datetime.utcnow(),
        status="Ongoing",
        created_by=admin,
    )
    db.add(trip)
    db.flush()
    trip.trip_number = f"TRIP-{trip.trip_date.strftime('%Y-%m%d')}-{trip.id:03d}"
    vehicle.status = "On Trip"
    db.commit()
    db.refresh(trip)
    delivery_count = db.query(Delivery).filter(Delivery.trip_id == trip.id).count()
    queue_trip_assigned_to_driver(trip, delivery_count)
    return _with_count(db, trip)


@router.post("/{item_id}/end", response_model=TripOut)
def end_trip(
    item_id: int,
    payload: TripEndIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("EDIT")),
    db: Session = Depends(get_db),
):
    trip = _get_or_404(db, item_id)
    if trip.status == "Completed":
        raise HTTPException(status_code=400, detail="This trip is already completed")
    if payload.end_km < trip.start_km:
        raise HTTPException(
            status_code=400,
            detail=f"Ending KM ({payload.end_km}) cannot be less than starting KM ({trip.start_km})",
        )

    trip.end_km = payload.end_km
    trip.end_time = payload.end_time or datetime.utcnow()
    trip.total_km = round(payload.end_km - trip.start_km, 2)
    trip.status = "Completed"

    vehicle = db.query(Vehicle).filter(Vehicle.id == trip.vehicle_id).first()
    if vehicle:
        vehicle.current_km_reading = payload.end_km
        vehicle.status = "Available"

    db.commit()
    db.refresh(trip)
    return _with_count(db, trip)
