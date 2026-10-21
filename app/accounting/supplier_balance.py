"""What we owe a supplier, in one place (used by the supplier profile, the supplier-outstanding report and the statement).

    owed  = bills (Purchases) of the supplier, not voided
          + expenses booked against the supplier, not voided
    paid  = every payment made out to the supplier (against a bill OR an expense)
    payable = owed - paid

The older version counted payments made against an expense but not the expense itself, so a paid expense pushed the
supplier's payable below zero. Both sides are counted now, so a bill or expense and its payment always cancel out."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.accounting.models import Expense, PaymentOut
from app.models import Purchase

DEAD = ("Voided", "Cancelled")


def supplier_position(db: Session, contact_id: int) -> dict:
    bills = float(db.query(func.coalesce(func.sum(Purchase.total_cost), 0)).filter(Purchase.contact_id == contact_id, Purchase.status.notin_(DEAD)).scalar() or 0)
    expenses = float(db.query(func.coalesce(func.sum(Expense.total_amount), 0)).filter(Expense.contact_id == contact_id, Expense.status.notin_(DEAD)).scalar() or 0)
    paid = float(db.query(func.coalesce(func.sum(PaymentOut.amount), 0)).filter(PaymentOut.contact_id == contact_id).scalar() or 0)
    owed = round(bills + expenses, 2)
    return {"bills": round(bills, 2), "expenses": round(expenses, 2), "owed": owed, "paid": round(paid, 2), "payable": round(owed - paid, 2)}
