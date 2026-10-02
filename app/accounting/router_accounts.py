from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.accounting.audit import record_change
from app.accounting.models import Account
from app.accounting.permissions import SETTINGS_WRITE_ROLES, require_accounting_action
from app.accounting.schemas import AccountIn, AccountOut
from app.database import get_db
from app.deps import get_current_admin

router = APIRouter(prefix="/accounts", tags=["accounting-accounts"])


def _get_or_404(db: Session, item_id: int) -> Account:
    item = db.query(Account).filter(Account.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Account not found")
    return item


@router.get("", response_model=list[AccountOut])
def list_accounts(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return db.query(Account).order_by(Account.code).all()


@router.post("", response_model=AccountOut, status_code=201)
def create_account(
    payload: AccountIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("CREATE", SETTINGS_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    if payload.account_type not in ("Asset", "Liability", "Equity", "Income", "Expense"):
        raise HTTPException(status_code=400, detail="Invalid account_type")
    existing = db.query(Account).filter(Account.code == payload.code).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Account code '{payload.code}' already exists")
    item = Account(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    record_change(db, "accounting_accounts", item.id, "create", changed_by=admin)
    db.commit()
    return item


@router.put("/{item_id}", response_model=AccountOut)
def update_account(
    item_id: int,
    payload: AccountIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("EDIT", SETTINGS_WRITE_ROLES)),
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
        record_change(db, "accounting_accounts", item.id, "update", changed_by=admin, changes=changes)
        db.commit()
    return item


@router.delete("/{item_id}", status_code=204)
def delete_account(
    item_id: int,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("DELETE", SETTINGS_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    if item.children:
        raise HTTPException(status_code=400, detail="Cannot delete an account that has sub-accounts")
    db.delete(item)
    db.commit()
