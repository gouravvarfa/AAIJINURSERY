from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.delivery.models import Delivery, DeliveryTrip, Driver
from app.delivery.permissions import require_roles
from app.delivery.schemas import DriverIn, DriverOut
from app.deps import get_current_admin

router = APIRouter(prefix="/drivers", tags=["delivery-drivers"])


def _get_or_404(db: Session, item_id: int) -> Driver:
    item = db.query(Driver).filter(Driver.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Driver not found")
    return item


def _with_stats(db: Session, driver: Driver) -> DriverOut:
    out = DriverOut.model_validate(driver)
    out.total_deliveries = db.query(Delivery).filter(Delivery.driver_id == driver.id).count()
    out.total_trips = db.query(DeliveryTrip).filter(DeliveryTrip.driver_id == driver.id).count()
    out.total_km = round(
        db.query(func.coalesce(func.sum(DeliveryTrip.total_km), 0))
        .filter(DeliveryTrip.driver_id == driver.id)
        .scalar()
        or 0,
        2,
    )
    return out


@router.get("", response_model=list[DriverOut])
def list_drivers(
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Driver)
    if status:
        query = query.filter(Driver.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(Driver.name.ilike(like) | Driver.phone.ilike(like))
    drivers = query.order_by(Driver.name).all()
    return [_with_stats(db, d) for d in drivers]


@router.get("/{item_id}", response_model=DriverOut)
def get_driver(item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _with_stats(db, _get_or_404(db, item_id))


@router.post("", response_model=DriverOut, status_code=201)
def create_driver(
    payload: DriverIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("CREATE")),
    db: Session = Depends(get_db),
):
    item = Driver(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return _with_stats(db, item)


@router.put("/{item_id}", response_model=DriverOut)
def update_driver(
    item_id: int,
    payload: DriverIn,
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
def delete_driver(
    item_id: int,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("DELETE")),
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    has_history = (
        db.query(Delivery).filter(Delivery.driver_id == item.id).first()
        or db.query(DeliveryTrip).filter(DeliveryTrip.driver_id == item.id).first()
    )
    if has_history:
        raise HTTPException(
            status_code=400, detail="Cannot delete a driver with existing deliveries or trips."
        )
    db.delete(item)
    db.commit()
