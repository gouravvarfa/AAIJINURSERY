from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.accounting.models import Contact, PaymentOut
from app.accounting.schemas import BillOut, SupplyLineOut
from app.database import get_db
from app.deps import get_current_admin
from app.models import Purchase
from app.supply_models import PurchaseLine

router = APIRouter(prefix="/bills", tags=["accounting-bills"])


def _with_summary(db: Session, bill: Purchase) -> BillOut:
    total_paid = (
        db.query(func.coalesce(func.sum(PaymentOut.amount), 0))
        .filter(PaymentOut.purchase_id == bill.id)
        .scalar()
        or 0
    )
    out = BillOut.model_validate(bill)
    out.supply_lines = [SupplyLineOut.model_validate(l) for l in db.query(PurchaseLine).filter(PurchaseLine.purchase_id == bill.id).order_by(PurchaseLine.line_no)]
    out.amount_paid = round(total_paid, 2)
    out.balance_due = round(max(bill.total_cost - total_paid, 0), 2)
    if bill.contact_id:
        contact = db.query(Contact).filter(Contact.id == bill.contact_id).first()
        if contact:
            out.contact = contact
    return out


@router.get("", response_model=list[BillOut])
def list_bills(
    status: Optional[str] = Query(None),
    contact_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None, description="Search by bill #, supplier name/text"),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Purchase).options(joinedload(Purchase.items))
    if status:
        query = query.filter(Purchase.status == status)
    if contact_id:
        query = query.filter(Purchase.contact_id == contact_id)
    if q:
        like = f"%{q}%"
        query = query.filter(Purchase.invoice_number.ilike(like) | Purchase.supplier.ilike(like))
    bills = query.order_by(Purchase.purchase_date.desc()).all()
    return [_with_summary(db, b) for b in bills]


@router.get("/{item_id}", response_model=BillOut)
def get_bill(item_id: int, admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    bill = (
        db.query(Purchase)
        .options(joinedload(Purchase.items))
        .filter(Purchase.id == item_id)
        .first()
    )
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return _with_summary(db, bill)
