from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.accounting.audit import record_change
from app.accounting.models import Employee
from app.database import get_db
from app.deps import get_current_admin
from app.labour import ledger
from app.labour.models import EmployeeAttendance, Payroll, WorkerAdvance, WorkerPayment
from app.labour.permissions import require_roles
from app.labour.schemas import EmployeeFullIn, EmployeeFullOut

router = APIRouter(prefix="/employees", tags=["labour-employees"])


def _get_or_404(db: Session, item_id: int) -> Employee:
    item = db.query(Employee).filter(Employee.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Employee not found")
    return item


def _with_outstanding(db: Session, item: Employee) -> EmployeeFullOut:
    out = EmployeeFullOut.model_validate(item)
    out.outstanding = ledger.employee_outstanding(db, item.id)
    return out


@router.get("", response_model=list[EmployeeFullOut])
def list_employees(
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search by name, phone, or department"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Employee)
    if status:
        query = query.filter(Employee.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(
            Employee.name.ilike(like) | Employee.phone.ilike(like) | Employee.department.ilike(like)
        )
    items = query.order_by(Employee.name).all()
    return [_with_outstanding(db, i) for i in items]


@router.get("/{item_id}", response_model=EmployeeFullOut)
def get_employee(item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _with_outstanding(db, _get_or_404(db, item_id))


@router.post("", response_model=EmployeeFullOut, status_code=201)
def create_employee(
    payload: EmployeeFullIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("CREATE")),
    db: Session = Depends(get_db),
):
    item = Employee(**payload.model_dump(), is_active=payload.status == "Active")
    db.add(item)
    db.commit()
    db.refresh(item)
    record_change(db, "accounting_employees", item.id, "create", changed_by=admin)
    db.commit()
    return _with_outstanding(db, item)


@router.put("/{item_id}", response_model=EmployeeFullOut)
def update_employee(
    item_id: int,
    payload: EmployeeFullIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("EDIT")),
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    changes = {}
    values = payload.model_dump()
    values["is_active"] = payload.status == "Active"
    for field, value in values.items():
        old = getattr(item, field)
        if old != value:
            changes[field] = (old, value)
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    if changes:
        record_change(db, "accounting_employees", item.id, "update", changed_by=admin, changes=changes)
        db.commit()
    return _with_outstanding(db, item)


@router.delete("/{item_id}", status_code=204)
def delete_employee(
    item_id: int,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("DELETE")),
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    has_history = (
        db.query(EmployeeAttendance).filter(EmployeeAttendance.employee_id == item.id).first()
        or db.query(Payroll).filter(Payroll.employee_id == item.id).first()
        or db.query(WorkerAdvance).filter(WorkerAdvance.employee_id == item.id).first()
        or db.query(WorkerPayment).filter(WorkerPayment.employee_id == item.id).first()
    )
    if has_history:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete an employee with existing attendance, payroll, advances, or payments.",
        )
    db.delete(item)
    db.commit()
