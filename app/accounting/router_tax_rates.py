from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.accounting.audit import record_change
from app.accounting.models import TaxRate
from app.accounting.permissions import SETTINGS_WRITE_ROLES, require_accounting_action
from app.accounting.schemas import TaxRateIn, TaxRateOut
from app.database import get_db
from app.deps import get_current_admin

router = APIRouter(prefix="/tax-rates", tags=["accounting-tax-rates"])


def _get_or_404(db: Session, item_id: int) -> TaxRate:
    item = db.query(TaxRate).filter(TaxRate.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Tax rate not found")
    return item


@router.get("", response_model=list[TaxRateOut])
def list_tax_rates(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    return db.query(TaxRate).order_by(TaxRate.name).all()


@router.post("", response_model=TaxRateOut, status_code=201)
def create_tax_rate(
    payload: TaxRateIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("CREATE", SETTINGS_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    item = TaxRate(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    record_change(db, "accounting_tax_rates", item.id, "create", changed_by=admin)
    db.commit()
    return item


@router.put("/{item_id}", response_model=TaxRateOut)
def update_tax_rate(
    item_id: int,
    payload: TaxRateIn,
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
        record_change(db, "accounting_tax_rates", item.id, "update", changed_by=admin, changes=changes)
        db.commit()
    return item


@router.delete("/{item_id}", status_code=204)
def delete_tax_rate(
    item_id: int,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("DELETE", SETTINGS_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    item = _get_or_404(db, item_id)
    db.delete(item)
    db.commit()
