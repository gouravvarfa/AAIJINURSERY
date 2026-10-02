from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.accounting.audit import record_change
from app.accounting.models import Employee
from app.database import get_db
from app.deps import get_current_admin
from app.labour.models import Labour, Payroll, WorkerPayment
from app.labour.permissions import require_roles
from app.labour.schemas import WorkerPaymentIn, WorkerPaymentOut

router = APIRouter(prefix="/payments", tags=["labour-payments"])


@router.get("", response_model=list[WorkerPaymentOut])
def list_payments(
    worker_type: Optional[str] = Query(None),
    employee_id: Optional[int] = Query(None),
    labour_id: Optional[int] = Query(None),
    payroll_id: Optional[int] = Query(None),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(WorkerPayment)
    if worker_type:
        query = query.filter(WorkerPayment.worker_type == worker_type)
    if employee_id:
        query = query.filter(WorkerPayment.employee_id == employee_id)
    if labour_id:
        query = query.filter(WorkerPayment.labour_id == labour_id)
    if payroll_id:
        query = query.filter(WorkerPayment.payroll_id == payroll_id)
    return query.order_by(WorkerPayment.payment_date.desc()).all()


@router.post("", response_model=WorkerPaymentOut, status_code=201)
def create_payment(
    payload: WorkerPaymentIn,
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
    if payload.payroll_id and not db.query(Payroll).filter(Payroll.id == payload.payroll_id).first():
        raise HTTPException(status_code=400, detail="Unknown payroll record")

    item = WorkerPayment(
        worker_type=payload.worker_type,
        employee_id=payload.employee_id if payload.worker_type == "EMPLOYEE" else None,
        labour_id=payload.labour_id if payload.worker_type == "LABOUR" else None,
        payroll_id=payload.payroll_id,
        amount=payload.amount,
        payment_date=payload.payment_date,
        method=payload.method,
        reference=payload.reference,
        notes=payload.notes,
        created_by=admin,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    record_change(db, "labour_worker_payments", item.id, "create", changed_by=admin)
    db.commit()
    return item
