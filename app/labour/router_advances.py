from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.accounting.audit import record_change
from app.accounting.models import Employee
from app.database import get_db
from app.deps import get_current_admin
from app.labour import ledger
from app.labour.models import Labour, WorkerAdvance
from app.labour.permissions import require_roles
from app.labour.schemas import WorkerAdvanceIn, WorkerAdvanceOut

router = APIRouter(prefix="/advances", tags=["labour-advances"])


def _get_or_404(db: Session, item_id: int) -> WorkerAdvance:
    item = (
        db.query(WorkerAdvance)
        .options(joinedload(WorkerAdvance.recoveries))
        .filter(WorkerAdvance.id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Advance not found")
    return item


def _with_recovery(db: Session, item: WorkerAdvance) -> WorkerAdvanceOut:
    out = WorkerAdvanceOut.model_validate(item)
    out.recovered_amount = ledger.advance_recovered_amount(db, item.id)
    out.remaining_amount = round(item.amount - out.recovered_amount, 2)
    return out


@router.get("", response_model=list[WorkerAdvanceOut])
def list_advances(
    worker_type: Optional[str] = Query(None),
    employee_id: Optional[int] = Query(None),
    labour_id: Optional[int] = Query(None),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(WorkerAdvance).options(joinedload(WorkerAdvance.recoveries))
    if worker_type:
        query = query.filter(WorkerAdvance.worker_type == worker_type)
    if employee_id:
        query = query.filter(WorkerAdvance.employee_id == employee_id)
    if labour_id:
        query = query.filter(WorkerAdvance.labour_id == labour_id)
    items = query.order_by(WorkerAdvance.advance_date.desc()).all()
    return [_with_recovery(db, i) for i in items]


@router.get("/{item_id}", response_model=WorkerAdvanceOut)
def get_advance(item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _with_recovery(db, _get_or_404(db, item_id))


@router.post("", response_model=WorkerAdvanceOut, status_code=201)
def create_advance(
    payload: WorkerAdvanceIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("CREATE")),
    db: Session = Depends(get_db),
):
    if payload.worker_type not in ("EMPLOYEE", "LABOUR"):
        raise HTTPException(status_code=400, detail="worker_type must be EMPLOYEE or LABOUR")
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")
    if payload.worker_type == "EMPLOYEE":
        if not payload.employee_id or not db.query(Employee).filter(Employee.id == payload.employee_id).first():
            raise HTTPException(status_code=400, detail="Unknown employee")
    else:
        if not payload.labour_id or not db.query(Labour).filter(Labour.id == payload.labour_id).first():
            raise HTTPException(status_code=400, detail="Unknown labour worker")

    item = WorkerAdvance(
        worker_type=payload.worker_type,
        employee_id=payload.employee_id if payload.worker_type == "EMPLOYEE" else None,
        labour_id=payload.labour_id if payload.worker_type == "LABOUR" else None,
        amount=payload.amount,
        advance_date=payload.advance_date,
        reason=payload.reason,
        created_by=admin,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    record_change(db, "labour_worker_advances", item.id, "create", changed_by=admin)
    db.commit()
    return _with_recovery(db, item)
