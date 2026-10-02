from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.accounting.audit import record_change
from app.accounting.models import Expense, PaymentOut
from app.accounting.permissions import PURCHASE_WRITE_ROLES, require_accounting_action
from app.accounting.schemas import PaymentOutIn, PaymentOutOut
from app.database import get_db
from app.deps import get_current_admin
from app.models import Purchase

router = APIRouter(prefix="/payments-out", tags=["accounting-payments-out"])


@router.get("", response_model=list[PaymentOutOut])
def list_payments_out(
    purchase_id: Optional[int] = Query(None),
    expense_id: Optional[int] = Query(None),
    contact_id: Optional[int] = Query(None),
    admin: str = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(PaymentOut)
    if purchase_id is not None:
        query = query.filter(PaymentOut.purchase_id == purchase_id)
    if expense_id is not None:
        query = query.filter(PaymentOut.expense_id == expense_id)
    if contact_id is not None:
        query = query.filter(PaymentOut.contact_id == contact_id)
    return query.order_by(PaymentOut.payment_date.desc()).all()


@router.post("", response_model=PaymentOutOut, status_code=201)
def create_payment_out(
    payload: PaymentOutIn,
    admin: str = Depends(get_current_admin),
    _role: str = Depends(require_accounting_action("CREATE", PURCHASE_WRITE_ROLES)),
    db: Session = Depends(get_db),
):
    if bool(payload.purchase_id) == bool(payload.expense_id):
        raise HTTPException(
            status_code=400, detail="Provide exactly one of purchase_id or expense_id"
        )
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    contact_id = None

    if payload.purchase_id:
        bill = db.query(Purchase).filter(Purchase.id == payload.purchase_id).first()
        if not bill:
            raise HTTPException(status_code=400, detail="Unknown bill")
        if bill.status in ("Voided", "Cancelled"):
            raise HTTPException(status_code=400, detail=f"Cannot record a payment against a {bill.status} bill")
        contact_id = bill.contact_id

        payment = PaymentOut(
            purchase_id=bill.id,
            contact_id=contact_id,
            amount=payload.amount,
            method=payload.method,
            payment_date=payload.payment_date,
            reference=payload.reference,
            notes=payload.notes,
            source="offline",
        )
        db.add(payment)
        db.flush()

        total_paid = (
            db.query(func.coalesce(func.sum(PaymentOut.amount), 0))
            .filter(PaymentOut.purchase_id == bill.id)
            .scalar()
            or 0
        )
        old_status = bill.status
        balance_due = round(max(bill.total_cost - total_paid, 0), 2)
        bill.status = "Paid" if balance_due <= 0 else "PartiallyPaid"
        db.commit()
        db.refresh(payment)
        record_change(db, "accounting_payments_out", payment.id, "create", changed_by=admin)
        if bill.status != old_status:
            record_change(
                db, "purchases", bill.id, "update", changed_by=admin,
                changes={"status": (old_status, bill.status)},
            )
        db.commit()
        return payment

    expense = db.query(Expense).filter(Expense.id == payload.expense_id).first()
    if not expense:
        raise HTTPException(status_code=400, detail="Unknown expense")
    if expense.status in ("Voided", "Cancelled"):
        raise HTTPException(
            status_code=400, detail=f"Cannot record a payment against a {expense.status} expense"
        )
    contact_id = expense.contact_id

    payment = PaymentOut(
        expense_id=expense.id,
        contact_id=contact_id,
        amount=payload.amount,
        method=payload.method,
        payment_date=payload.payment_date,
        reference=payload.reference,
        notes=payload.notes,
        source="offline",
    )
    db.add(payment)
    db.flush()

    total_paid = (
        db.query(func.coalesce(func.sum(PaymentOut.amount), 0))
        .filter(PaymentOut.expense_id == expense.id)
        .scalar()
        or 0
    )
    old_status = expense.status
    expense.amount_paid = round(total_paid, 2)
    expense.balance_due = round(max(expense.total_amount - total_paid, 0), 2)
    expense.status = "Paid" if expense.balance_due <= 0 else "PartiallyPaid"
    db.commit()
    db.refresh(payment)
    record_change(db, "accounting_payments_out", payment.id, "create", changed_by=admin)
    if expense.status != old_status:
        record_change(
            db, "accounting_expenses", expense.id, "update", changed_by=admin,
            changes={"status": (old_status, expense.status)},
        )
    db.commit()
    return payment
