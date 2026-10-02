from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.accounting.audit import record_change
from app.accounting.models import Account, Contact, Expense
from app.accounting.permissions import PURCHASE_WRITE_ROLES, require_accounting_action
from app.accounting.schemas import ExpenseIn, ExpenseOut
from app.database import get_db
from app.deps import get_current_admin

router = APIRouter(prefix="/expenses", tags=["accounting-expenses"])


def _get_or_404(db: Session, item_id: int) -> Expense:
    item = db.query(Expense).filter(Expense.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Expense not found")
    return item


@router.get("", response_model=list[ExpenseOut])
def list_expenses(
    status: Optional[str] = Query(None),
    contact_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None, description="Search by category or description"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Expense).options(joinedload(Expense.account), joinedload(Expense.contact))
    if status:
        query = query.filter(Expense.status == status)
    if contact_id:
        query = query.filter(Expense.contact_id == contact_id)
    if q:
        like = f"%{q}%"
        query = query.filter(Expense.category.ilike(like) | Expense.description.ilike(like))
    return query.order_by(Expense.expense_date.desc()).all()


@router.get("/{item_id}", response_model=ExpenseOut)
def get_expense(item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    item = (
        db.query(Expense)
        .options(joinedload(Expense.account), joinedload(Expense.contact))
        .filter(Expense.id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Expense not found")
    return item


@router.post("", response_model=ExpenseOut, status_code=201)
def create_expense(
    payload: ExpenseIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("CREATE", PURCHASE_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")
    if payload.account_id is not None and not db.query(Account).filter(Account.id == payload.account_id).first():
        raise HTTPException(status_code=400, detail="Unknown account")
    if payload.contact_id is not None and not db.query(Contact).filter(Contact.id == payload.contact_id).first():
        raise HTTPException(status_code=400, detail="Unknown contact")

    total = round(payload.amount + payload.tax_amount, 2)
    item = Expense(
        category=payload.category,
        account_id=payload.account_id,
        contact_id=payload.contact_id,
        description=payload.description,
        expense_date=payload.expense_date,
        amount=payload.amount,
        tax_amount=payload.tax_amount,
        total_amount=total,
        amount_paid=0,
        balance_due=total,
        status="Unpaid",
        reference=payload.reference,
        notes=payload.notes,
        source="offline",
        created_by=admin,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    record_change(db, "accounting_expenses", item.id, "create", changed_by=admin)
    db.commit()
    return get_expense(item.id, admin, db)


@router.post("/{item_id}/void", response_model=ExpenseOut)
def void_expense(
    item_id: int,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("CANCEL", PURCHASE_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    """Never a hard delete -- financial documents are Voided, not removed."""
    item = _get_or_404(db, item_id)
    old_status = item.status
    item.status = "Voided"
    db.commit()
    record_change(
        db,
        "accounting_expenses",
        item.id,
        "void",
        changed_by=admin,
        changes={"status": (old_status, "Voided")},
    )
    db.commit()
    return get_expense(item.id, admin, db)
