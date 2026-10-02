from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.delivery.models import Vehicle, VehicleFuelLog
from app.delivery.permissions import require_roles
from app.delivery.schemas import FuelLogIn, FuelLogOut
from app.deps import get_current_admin

router = APIRouter(prefix="/fuel", tags=["delivery-fuel"])


@router.get("", response_model=list[FuelLogOut])
def list_fuel_logs(
    vehicle_id: Optional[int] = Query(None),
    driver_id: Optional[int] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(VehicleFuelLog)
    if vehicle_id:
        query = query.filter(VehicleFuelLog.vehicle_id == vehicle_id)
    if driver_id:
        query = query.filter(VehicleFuelLog.driver_id == driver_id)
    if date_from:
        query = query.filter(VehicleFuelLog.date >= date_from)
    if date_to:
        query = query.filter(VehicleFuelLog.date <= date_to)
    return query.order_by(VehicleFuelLog.date.desc()).all()


@router.post("", response_model=FuelLogOut, status_code=201)
def create_fuel_log(
    payload: FuelLogIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("CREATE")),
    db: Session = Depends(get_db),
):
    if not db.query(Vehicle).filter(Vehicle.id == payload.vehicle_id).first():
        raise HTTPException(status_code=400, detail="Unknown vehicle")
    if payload.litres <= 0:
        raise HTTPException(status_code=400, detail="Litres must be greater than 0")
    if payload.rate_per_litre < 0:
        raise HTTPException(status_code=400, detail="Rate cannot be negative")

    item = VehicleFuelLog(
        **payload.model_dump(),
        total_amount=round(payload.litres * payload.rate_per_litre, 2),
        created_by=admin,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
