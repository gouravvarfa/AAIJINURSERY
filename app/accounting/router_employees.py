from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.accounting.audit import record_change
from app.accounting.models import Employee
from app.accounting.permissions import EMPLOYEE_WRITE_ROLES, require_accounting_action
from app.accounting.schemas import EmployeeIn, EmployeeOut
from app.database import get_db
from app.deps import get_current_admin

router = APIRouter(prefix="/employees", tags=["accounting-employees"])


def _get_or_404(db: Session, item_id: int) -> Employee:
    item = db.query(Employee).filter(Employee.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Employee not found")
    return item


@router.get("", response_model=list[EmployeeOut])
def list_employees(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return db.query(Employee).order_by(Employee.name).all()


@router.post("", response_model=EmployeeOut, status_code=201)
def create_employee(
    payload: EmployeeIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("CREATE", EMPLOYEE_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    item = Employee(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    record_change(db, "accounting_employees", item.id, "create", changed_by=admin)
    db.commit()
    return item


@router.put("/{item_id}", response_model=EmployeeOut)
def update_employee(
    item_id: int,
    payload: EmployeeIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("EDIT", EMPLOYEE_WRITE_ROLES)),
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
        record_change(db, "accounting_employees", item.id, "update", changed_by=admin, changes=changes)
        db.commit()
    return item


@router.delete("/{item_id}", status_code=204)
def delete_employee(
    item_id: int,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("DELETE", EMPLOYEE_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    db.delete(item)
    db.commit()
