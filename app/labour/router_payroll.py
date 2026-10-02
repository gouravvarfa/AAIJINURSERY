import calendar
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.accounting.audit import record_change
from app.accounting.models import Employee
from app.database import get_db
from app.deps import get_current_admin
from app.labour import ledger
from app.labour.models import (
    AdvanceRecovery,
    EmployeeAttendance,
    Labour,
    LabourAttendance,
    Payroll,
    WorkerAdvance,
)
from app.labour.permissions import require_roles
from app.labour.schemas import PayrollAdjustIn, PayrollGenerateIn, PayrollOut

router = APIRouter(prefix="/payroll", tags=["labour-payroll"])

EMPLOYEE_PAID_STATUSES = {"Present", "Leave", "Holiday"}  # days that count as a full paid day
EMPLOYEE_HALF_STATUSES = {"Half Day"}


def _get_or_404(db: Session, item_id: int) -> Payroll:
    item = db.query(Payroll).filter(Payroll.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Payroll record not found")
    return item


def _with_extras(db: Session, item: Payroll) -> PayrollOut:
    out = PayrollOut.model_validate(item)
    if item.employee:
        out.worker_name = item.employee.name
    elif item.labour:
        out.worker_name = item.labour.name
    out.total_paid = ledger.payroll_total_paid(db, item.id)
    out.outstanding = round(item.net_payable - out.total_paid, 2)
    return out


@router.get("", response_model=list[PayrollOut])
def list_payroll(
    worker_type: Optional[str] = Query(None),
    period_year: Optional[int] = Query(None),
    period_month: Optional[int] = Query(None),
    employee_id: Optional[int] = Query(None),
    labour_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Payroll)
    if worker_type:
        query = query.filter(Payroll.worker_type == worker_type)
    if period_year:
        query = query.filter(Payroll.period_year == period_year)
    if period_month:
        query = query.filter(Payroll.period_month == period_month)
    if employee_id:
        query = query.filter(Payroll.employee_id == employee_id)
    if labour_id:
        query = query.filter(Payroll.labour_id == labour_id)
    if status:
        query = query.filter(Payroll.status == status)
    items = query.order_by(Payroll.period_year.desc(), Payroll.period_month.desc()).all()
    return [_with_extras(db, i) for i in items]


@router.get("/{item_id}", response_model=PayrollOut)
def get_payroll(item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return _with_extras(db, _get_or_404(db, item_id))


@router.post("/generate", response_model=PayrollOut, status_code=201)
def generate_payroll(
    payload: PayrollGenerateIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("CREATE")),
    db: Session = Depends(get_db),
):
    if payload.worker_type not in ("EMPLOYEE", "LABOUR"):
        raise HTTPException(status_code=400, detail="worker_type must be EMPLOYEE or LABOUR")
    if not (1 <= payload.period_month <= 12):
        raise HTTPException(status_code=400, detail="period_month must be 1-12")

    days_in_month = calendar.monthrange(payload.period_year, payload.period_month)[1]
    period_start = datetime(payload.period_year, payload.period_month, 1)
    if payload.period_month < 12:
        period_end = datetime(payload.period_year, payload.period_month + 1, 1)
    else:
        period_end = datetime(payload.period_year + 1, 1, 1)

    if payload.worker_type == "EMPLOYEE":
        if not payload.employee_id:
            raise HTTPException(status_code=400, detail="employee_id is required for EMPLOYEE payroll")
        employee = db.query(Employee).filter(Employee.id == payload.employee_id).first()
        if not employee:
            raise HTTPException(status_code=400, detail="Unknown employee")
        existing = (
            db.query(Payroll)
            .filter(
                Payroll.worker_type == "EMPLOYEE", Payroll.employee_id == employee.id,
                Payroll.period_year == payload.period_year, Payroll.period_month == payload.period_month,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Payroll for this employee and period already exists. Reopen it to make changes.",
            )

        attendance_rows = (
            db.query(EmployeeAttendance)
            .filter(
                EmployeeAttendance.employee_id == employee.id,
                EmployeeAttendance.attendance_date >= period_start,
                EmployeeAttendance.attendance_date < period_end,
            )
            .all()
        )
        days_present = sum(
            1.0 if r.status in EMPLOYEE_PAID_STATUSES else (0.5 if r.status in EMPLOYEE_HALF_STATUSES else 0.0)
            for r in attendance_rows
        )
        days_absent = sum(1.0 for r in attendance_rows if r.status == "Absent")
        overtime_hours = sum(r.overtime_hours or 0 for r in attendance_rows)

        per_day_rate = employee.salary / days_in_month if days_in_month else 0
        basic_earnings = round(days_present * per_day_rate, 2)
        overtime_earnings = round(overtime_hours * employee.overtime_rate, 2)
        gross_earnings = round(basic_earnings + overtime_earnings, 2)

        payroll = Payroll(
            worker_type="EMPLOYEE",
            employee_id=employee.id,
            period_year=payload.period_year,
            period_month=payload.period_month,
            rate_snapshot=employee.salary,
            days_present=days_present,
            days_absent=days_absent,
            basic_earnings=basic_earnings,
            overtime_earnings=overtime_earnings,
            gross_earnings=gross_earnings,
            net_payable=gross_earnings,
            status="Draft",
            generated_by=admin,
        )

    else:
        if not payload.labour_id:
            raise HTTPException(status_code=400, detail="labour_id is required for LABOUR payroll")
        labour = db.query(Labour).filter(Labour.id == payload.labour_id).first()
        if not labour:
            raise HTTPException(status_code=400, detail="Unknown labour worker")
        existing = (
            db.query(Payroll)
            .filter(
                Payroll.worker_type == "LABOUR", Payroll.labour_id == labour.id,
                Payroll.period_year == payload.period_year, Payroll.period_month == payload.period_month,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Payroll for this labour worker and period already exists. Reopen it to make changes.",
            )

        attendance_rows = (
            db.query(LabourAttendance)
            .filter(
                LabourAttendance.labour_id == labour.id,
                LabourAttendance.attendance_date >= period_start,
                LabourAttendance.attendance_date < period_end,
            )
            .all()
        )
        days_present = sum(
            1.0 if r.status == "Worked" else (0.5 if r.status == "Half Day" else 0.0)
            for r in attendance_rows
        )
        days_absent = sum(1.0 for r in attendance_rows if r.status == "Not Worked")
        basic_earnings = round(sum(r.base_earned or 0 for r in attendance_rows), 2)
        overtime_earnings = round(sum(r.overtime_earned or 0 for r in attendance_rows), 2)
        gross_earnings = round(basic_earnings + overtime_earnings, 2)

        payroll = Payroll(
            worker_type="LABOUR",
            labour_id=labour.id,
            period_year=payload.period_year,
            period_month=payload.period_month,
            rate_snapshot=labour.daily_wage,
            days_present=days_present,
            days_absent=days_absent,
            basic_earnings=basic_earnings,
            overtime_earnings=overtime_earnings,
            gross_earnings=gross_earnings,
            net_payable=gross_earnings,
            status="Draft",
            generated_by=admin,
        )

    db.add(payroll)
    db.commit()
    db.refresh(payroll)
    record_change(db, "labour_payroll", payroll.id, "create", changed_by=admin)
    db.commit()
    return _with_extras(db, payroll)


def _reverse_recoveries(db: Session, payroll: Payroll):
    db.query(AdvanceRecovery).filter(AdvanceRecovery.payroll_id == payroll.id).delete()


def _apply_advance_recovery(db: Session, payroll: Payroll, amount: float, admin: str):
    """FIFO across the worker's outstanding advances. Raises if amount
    exceeds what's actually still outstanding across those advances."""
    if amount <= 0:
        return
    query = db.query(WorkerAdvance).filter(WorkerAdvance.worker_type == payroll.worker_type)
    if payroll.worker_type == "EMPLOYEE":
        query = query.filter(WorkerAdvance.employee_id == payroll.employee_id)
    else:
        query = query.filter(WorkerAdvance.labour_id == payroll.labour_id)
    advances = query.order_by(WorkerAdvance.advance_date).all()

    remaining_to_apply = amount
    for advance in advances:
        if remaining_to_apply <= 0:
            break
        already_recovered = ledger.advance_recovered_amount(db, advance.id)
        available = advance.amount - already_recovered
        if available <= 0:
            continue
        take = min(available, remaining_to_apply)
        db.add(AdvanceRecovery(advance_id=advance.id, payroll_id=payroll.id, amount=take, created_by=admin))
        remaining_to_apply -= take

    if remaining_to_apply > 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot recover Rs {amount} -- only Rs {round(amount - remaining_to_apply, 2)} of advance is outstanding for this worker.",
        )


@router.put("/{item_id}/adjust", response_model=PayrollOut)
def adjust_payroll(
    item_id: int,
    payload: PayrollAdjustIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("EDIT")),
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    if item.status == "Finalized":
        raise HTTPException(status_code=400, detail="This payroll is finalized -- reopen it first to adjust.")

    _reverse_recoveries(db, item)
    db.flush()
    _apply_advance_recovery(db, item, payload.advance_recovery, admin)

    old_net = item.net_payable
    item.advance_recovery = payload.advance_recovery
    item.deductions = payload.deductions
    item.notes = payload.notes
    item.net_payable = round(item.gross_earnings - payload.advance_recovery - payload.deductions, 2)
    db.commit()
    db.refresh(item)
    if old_net != item.net_payable:
        record_change(
            db, "labour_payroll", item.id, "update", changed_by=admin,
            changes={"net_payable": (old_net, item.net_payable)},
        )
        db.commit()
    return _with_extras(db, item)


@router.post("/{item_id}/finalize", response_model=PayrollOut)
def finalize_payroll(
    item_id: int,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("APPROVE")),
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    if item.status == "Finalized":
        raise HTTPException(status_code=400, detail="Already finalized")
    item.status = "Finalized"
    item.finalized_by = admin
    item.finalized_at = datetime.utcnow()
    db.commit()
    record_change(db, "labour_payroll", item.id, "finalize", changed_by=admin)
    db.commit()
    return _with_extras(db, item)


@router.post("/{item_id}/reopen", response_model=PayrollOut)
def reopen_payroll(
    item_id: int,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("EDIT")),
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    if item.status != "Finalized":
        raise HTTPException(status_code=400, detail="Only a finalized payroll can be reopened")
    old_status = item.status
    item.status = "Draft"
    db.commit()
    record_change(
        db, "labour_payroll", item.id, "update", changed_by=admin,
        changes={"status": (old_status, "Draft")},
    )
    db.commit()
    return _with_extras(db, item)
