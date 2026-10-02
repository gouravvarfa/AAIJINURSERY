from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.accounting.audit import record_change
from app.database import get_db
from app.deps import get_current_admin
from app.labour import ledger
from app.labour.models import (
    Labour,
    LabourAttendance,
    Payroll,
    WorkAssignment,
    WorkerAdvance,
    WorkerPayment,
)
from app.labour.permissions import require_roles
from app.labour.schemas import LabourIn, LabourOut

router = APIRouter(prefix="/labour", tags=["labour-labour"])


def _get_or_404(db: Session, item_id: int) -> Labour:
    item = db.query(Labour).filter(Labour.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Labour worker not found")
    return item


def _with_outstanding(db: Session, item: Labour) -> LabourOut:
    out = LabourOut.model_validate(item)
    out.outstanding = ledger.labour_outstanding(db, item.id)
    return out


@router.get("", response_model=list[LabourOut])
def list_labour(
    status: Optional[str] = Query(None),
    work_type: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search by name, phone, or work type"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Labour)
    if status:
        query = query.filter(Labour.status == status)
    if work_type:
        query = query.filter(Labour.work_type == work_type)
    if q:
        like = f"%{q}%"
        query = query.filter(
            Labour.name.ilike(like) | Labour.phone.ilike(like) | Labour.work_type.ilike(like)
        )
    items = query.order_by(Labour.name).all()
    return [_with_outstanding(db, i) for i in items]


@router.get("/{item_id}", response_model=LabourOut)
def get_labour(item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _with_outstanding(db, _get_or_404(db, item_id))


@router.post("", response_model=LabourOut, status_code=201)
def create_labour(
    payload: LabourIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("CREATE")),
    db: Session = Depends(get_db),
):
    item = Labour(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    record_change(db, "labour_workers", item.id, "create", changed_by=admin)
    db.commit()
    return _with_outstanding(db, item)


@router.put("/{item_id}", response_model=LabourOut)
def update_labour(
    item_id: int,
    payload: LabourIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("EDIT")),
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    changes = {}
    for field, value in payload.model_dump().items():
        old = getattr(item, field)
        if old != value:
            changes[field] = (old, value)
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    if changes:
        record_change(db, "labour_workers", item.id, "update", changed_by=admin, changes=changes)
        db.commit()
    return _with_outstanding(db, item)


@router.delete("/{item_id}", status_code=204)
def delete_labour(
    item_id: int,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("DELETE")),
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    has_history = (
        db.query(LabourAttendance).filter(LabourAttendance.labour_id == item.id).first()
        or db.query(Payroll).filter(Payroll.labour_id == item.id).first()
        or db.query(WorkerAdvance).filter(WorkerAdvance.labour_id == item.id).first()
        or db.query(WorkerPayment).filter(WorkerPayment.labour_id == item.id).first()
        or db.query(WorkAssignment).filter(WorkAssignment.labour_id == item.id).first()
    )
    if has_history:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a labour worker with existing work requests, attendance, payroll, advances, or payments.",
        )
    db.delete(item)
    db.commit()
