from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.delivery.models import Delivery, DeliveryTrip, Vehicle, VehicleFuelLog
from app.delivery.permissions import require_roles
from app.delivery.schemas import VehicleIn, VehicleOut
from app.deps import get_current_admin

router = APIRouter(prefix="/vehicles", tags=["delivery-vehicles"])


def _get_or_404(db: Session, item_id: int) -> Vehicle:
    item = db.query(Vehicle).filter(Vehicle.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return item


def _with_stats(db: Session, vehicle: Vehicle) -> VehicleOut:
    out = VehicleOut.model_validate(vehicle)
    out.total_trips = db.query(DeliveryTrip).filter(DeliveryTrip.vehicle_id == vehicle.id).count()
    out.total_deliveries = db.query(Delivery).filter(Delivery.vehicle_id == vehicle.id).count()
    out.total_km = round(
        db.query(func.coalesce(func.sum(DeliveryTrip.total_km), 0))
        .filter(DeliveryTrip.vehicle_id == vehicle.id)
        .scalar()
        or 0,
        2,
    )
    out.total_fuel_litres = round(
        db.query(func.coalesce(func.sum(VehicleFuelLog.litres), 0))
        .filter(VehicleFuelLog.vehicle_id == vehicle.id)
        .scalar()
        or 0,
        2,
    )
    out.total_fuel_cost = round(
        db.query(func.coalesce(func.sum(VehicleFuelLog.total_amount), 0))
        .filter(VehicleFuelLog.vehicle_id == vehicle.id)
        .scalar()
        or 0,
        2,
    )
    out.avg_km_per_litre = (
        round(out.total_km / out.total_fuel_litres, 2) if out.total_fuel_litres > 0 else None
    )
    return out


@router.get("", response_model=list[VehicleOut])
def list_vehicles(
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Vehicle)
    if status:
        query = query.filter(Vehicle.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(Vehicle.registration_number.ilike(like) | Vehicle.name_model.ilike(like))
    vehicles = query.order_by(Vehicle.registration_number).all()
    return [_with_stats(db, v) for v in vehicles]


@router.get("/{item_id}", response_model=VehicleOut)
def get_vehicle(item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _with_stats(db, _get_or_404(db, item_id))


@router.post("", response_model=VehicleOut, status_code=201)
def create_vehicle(
    payload: VehicleIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("CREATE")),
    db: Session = Depends(get_db),
):
    existing = db.query(Vehicle).filter(Vehicle.registration_number == payload.registration_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="A vehicle with this registration number already exists")
    item = Vehicle(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return _with_stats(db, item)


@router.put("/{item_id}", response_model=VehicleOut)
def update_vehicle(
    item_id: int,
    payload: VehicleIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("EDIT")),
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    for field, value in payload.model_dump().items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return _with_stats(db, item)


@router.delete("/{item_id}", status_code=204)
def delete_vehicle(
    item_id: int,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("DELETE")),
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    has_history = (
        db.query(Delivery).filter(Delivery.vehicle_id == item.id).first()
        or db.query(DeliveryTrip).filter(DeliveryTrip.vehicle_id == item.id).first()
        or db.query(VehicleFuelLog).filter(VehicleFuelLog.vehicle_id == item.id).first()
    )
    if has_history:
        raise HTTPException(
            status_code=400, detail="Cannot delete a vehicle with existing deliveries, trips, or fuel logs."
        )
    db.delete(item)
    db.commit()
