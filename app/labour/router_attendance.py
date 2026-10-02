from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.accounting.audit import record_change
from app.accounting.models import Employee
from app.database import get_db
from app.deps import get_current_admin
from app.labour.models import HALF_DAY_RATIO, Labour, LabourAttendance, EmployeeAttendance
from app.labour.permissions import require_roles
from app.labour.schemas import (
    EmployeeAttendanceIn,
    EmployeeAttendanceOut,
    LabourAttendanceIn,
    LabourAttendanceOut,
)

router = APIRouter(prefix="/attendance", tags=["labour-attendance"])


# ---------- Employee Attendance ----------

@router.get("/employees", response_model=list[EmployeeAttendanceOut])
def list_employee_attendance(
    employee_id: Optional[int] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(EmployeeAttendance)
    if employee_id:
        query = query.filter(EmployeeAttendance.employee_id == employee_id)
    if date_from:
        query = query.filter(EmployeeAttendance.attendance_date >= date_from)
    if date_to:
        query = query.filter(EmployeeAttendance.attendance_date <= date_to)
    return query.order_by(EmployeeAttendance.attendance_date.desc()).all()


@router.post("/employees", response_model=EmployeeAttendanceOut, status_code=201)
def mark_employee_attendance(
    payload: EmployeeAttendanceIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("CREATE")),
    db: Session = Depends(get_db),
):
    employee = db.query(Employee).filter(Employee.id == payload.employee_id).first()
    if not employee:
        raise HTTPException(status_code=400, detail="Unknown employee")

    existing = (
        db.query(EmployeeAttendance)
        .filter(
            EmployeeAttendance.employee_id == payload.employee_id,
            EmployeeAttendance.attendance_date == payload.attendance_date,
        )
        .first()
    )
    if existing:
        old_status = existing.status
        existing.status = payload.status
        existing.overtime_hours = payload.overtime_hours
        existing.notes = payload.notes
        existing.created_by = admin
        db.commit()
        if old_status != payload.status:
            record_change(
                db, "labour_employee_attendance", existing.id, "update", changed_by=admin,
                changes={"status": (old_status, payload.status)},
            )
            db.commit()
        return existing

    item = EmployeeAttendance(
        employee_id=payload.employee_id,
        attendance_date=payload.attendance_date,
        status=payload.status,
        overtime_hours=payload.overtime_hours,
        notes=payload.notes,
        created_by=admin,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    record_change(db, "labour_employee_attendance", item.id, "create", changed_by=admin)
    db.commit()
    return item


# ---------- Labour Attendance ----------

@router.get("/labour", response_model=list[LabourAttendanceOut])
def list_labour_attendance(
    labour_id: Optional[int] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(LabourAttendance)
    if labour_id:
        query = query.filter(LabourAttendance.labour_id == labour_id)
    if date_from:
        query = query.filter(LabourAttendance.attendance_date >= date_from)
    if date_to:
        query = query.filter(LabourAttendance.attendance_date <= date_to)
    return query.order_by(LabourAttendance.attendance_date.desc()).all()


def _compute_labour_earning(labour: Labour, status: str, overtime_hours: float):
    """Freezes the rate in effect right now onto the attendance row --
    historical rate protection (#37): once written, this never changes
    even if labour.daily_wage/overtime_rate change later."""
    if status == "Worked":
        base_earned = labour.daily_wage
    elif status == "Half Day":
        base_earned = labour.daily_wage * HALF_DAY_RATIO
    else:  # Not Worked
        base_earned = 0.0
    overtime_earned = (overtime_hours or 0) * labour.overtime_rate
    return round(base_earned, 2), round(overtime_earned, 2)


@router.post("/labour", response_model=LabourAttendanceOut, status_code=201)
def mark_labour_attendance(
    payload: LabourAttendanceIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("CREATE")),
    db: Session = Depends(get_db),
):
    labour = db.query(Labour).filter(Labour.id == payload.labour_id).first()
    if not labour:
        raise HTTPException(status_code=400, detail="Unknown labour worker")
    if payload.status not in ("Worked", "Not Worked", "Half Day"):
        raise HTTPException(status_code=400, detail="Invalid attendance status")

    base_earned, overtime_earned = _compute_labour_earning(labour, payload.status, payload.overtime_hours)
    earned_amount = round(base_earned + overtime_earned, 2)

    existing = (
        db.query(LabourAttendance)
        .filter(
            LabourAttendance.labour_id == payload.labour_id,
            LabourAttendance.attendance_date == payload.attendance_date,
        )
        .first()
    )
    if existing:
        old_status = existing.status
        existing.status = payload.status
        existing.overtime_hours = payload.overtime_hours
        existing.work_assignment_id = payload.work_assignment_id
        existing.daily_wage_snapshot = labour.daily_wage
        existing.overtime_rate_snapshot = labour.overtime_rate
        existing.base_earned = base_earned
        existing.overtime_earned = overtime_earned
        existing.earned_amount = earned_amount
        existing.notes = payload.notes
        existing.created_by = admin
        db.commit()
        if old_status != payload.status:
            record_change(
                db, "labour_labour_attendance", existing.id, "update", changed_by=admin,
                changes={"status": (old_status, payload.status)},
            )
            db.commit()
        return existing

    item = LabourAttendance(
        labour_id=payload.labour_id,
        work_assignment_id=payload.work_assignment_id,
        attendance_date=payload.attendance_date,
        status=payload.status,
        overtime_hours=payload.overtime_hours,
        daily_wage_snapshot=labour.daily_wage,
        overtime_rate_snapshot=labour.overtime_rate,
        base_earned=base_earned,
        overtime_earned=overtime_earned,
        earned_amount=earned_amount,
        notes=payload.notes,
        created_by=admin,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    record_change(db, "labour_labour_attendance", item.id, "create", changed_by=admin)
    db.commit()
    return item
