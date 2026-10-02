from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.accounting.audit import record_change
from app.database import get_db
from app.deps import get_current_admin
from app.labour.models import Labour, WorkAssignment, WorkRequirement
from app.labour.permissions import require_roles
from app.labour.schemas import (
    WorkAssignmentStatusIn,
    WorkRequirementIn,
    WorkRequirementOut,
)

router = APIRouter(prefix="/work-requirements", tags=["labour-work"])


def _get_or_404(db: Session, item_id: int) -> WorkRequirement:
    item = (
        db.query(WorkRequirement)
        .options(joinedload(WorkRequirement.assignments).joinedload(WorkAssignment.labour))
        .filter(WorkRequirement.id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Work requirement not found")
    return item


@router.get("", response_model=list[WorkRequirementOut])
def list_work_requirements(
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(WorkRequirement).options(
        joinedload(WorkRequirement.assignments).joinedload(WorkAssignment.labour)
    )
    if date_from:
        query = query.filter(WorkRequirement.work_date >= date_from)
    if date_to:
        query = query.filter(WorkRequirement.work_date <= date_to)
    return query.order_by(WorkRequirement.work_date.desc()).all()


@router.get("/{item_id}", response_model=WorkRequirementOut)
def get_work_requirement(
    item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
):
    return _get_or_404(db, item_id)


@router.post("", response_model=WorkRequirementOut, status_code=201)
def create_work_requirement(
    payload: WorkRequirementIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("CREATE")),
    db: Session = Depends(get_db),
):
    item = WorkRequirement(
        work_date=payload.work_date,
        work_type=payload.work_type,
        required_count=payload.required_count,
        location=payload.location,
        estimated_hours=payload.estimated_hours,
        notes=payload.notes,
        created_by=admin,
    )
    db.add(item)
    db.flush()

    if payload.labour_ids:
        valid_ids = {
            l.id for l in db.query(Labour.id).filter(Labour.id.in_(payload.labour_ids)).all()
        }
        for labour_id in payload.labour_ids:
            if labour_id in valid_ids:
                db.add(WorkAssignment(work_requirement_id=item.id, labour_id=labour_id, status="Pending"))

    db.commit()
    record_change(db, "labour_work_requirements", item.id, "create", changed_by=admin)
    db.commit()
    return _get_or_404(db, item.id)


@router.post("/{item_id}/send-requests", response_model=WorkRequirementOut)
def send_more_requests(
    item_id: int,
    labour_ids: list[int],
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("EDIT")),
    db: Session = Depends(get_db),
):
    """Adds more Labour workers to an already-created work requirement
    (e.g. the first batch didn't accept enough)."""
    item = _get_or_404(db, item_id)
    existing_ids = {a.labour_id for a in item.assignments}
    valid_ids = {l.id for l in db.query(Labour.id).filter(Labour.id.in_(labour_ids)).all()}
    for labour_id in labour_ids:
        if labour_id in valid_ids and labour_id not in existing_ids:
            db.add(WorkAssignment(work_requirement_id=item.id, labour_id=labour_id, status="Pending"))
    db.commit()
    return _get_or_404(db, item_id)


@router.put("/assignments/{assignment_id}/status", response_model=WorkRequirementOut)
def update_assignment_status(
    assignment_id: int,
    payload: WorkAssignmentStatusIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_roles("EDIT")),
    db: Session = Depends(get_db),
):
    assignment = db.query(WorkAssignment).filter(WorkAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Work assignment not found")
    if payload.status not in ("Accepted", "Rejected", "Cancelled", "No Response", "Pending"):
        raise HTTPException(status_code=400, detail="Invalid status")
    old_status = assignment.status
    assignment.status = payload.status
    assignment.responded_at = datetime.utcnow()
    db.commit()
    record_change(
        db, "labour_work_assignments", assignment.id, "update", changed_by=admin,
        changes={"status": (old_status, payload.status)},
    )
    db.commit()
    return _get_or_404(db, assignment.work_requirement_id)
