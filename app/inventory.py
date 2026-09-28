"""Single source of truth for every stock movement -- online checkout,
order cancellation, delivery rejection, procurement receipts (both the
legacy Purchase form and Purchase-Order-to-Bill conversion), and offline/
manual Sales Order invoicing all call through here instead of touching
Plant.stock_quantity / PlantVariant.stock_quantity directly.

Two guarantees this module exists to provide, that inline `+=`/`-=` on the
ORM object can't:

1. Concurrency safety -- availability check and deduction happen as ONE
   atomic conditional UPDATE (`UPDATE ... SET stock = stock - :qty WHERE
   id = :id AND stock >= :qty`), so two simultaneous requests for the last
   unit can't both read "1 available" and both succeed. Whichever request's
   UPDATE commits first wins; the loser's WHERE clause matches zero rows and
   InsufficientStockError is raised for it. This works under SQLite (and
   any other SQL database) because the UPDATE itself -- not a prior SELECT
   -- is what the availability check is embedded in.

2. Idempotency -- an optional `reference` string (e.g. "ORDER:123:SALE") is
   enforced unique at the database level via InventoryTransaction's unique
   constraint. Calling deduct_stock/restore_stock twice with the same
   reference returns the original transaction instead of moving stock
   again, so a retried request (or a bug that calls this twice) can't
   double-deduct or double-restore.
"""
from dataclasses import dataclass

from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import InventoryTransaction, Plant, PlantVariant


class InsufficientStockError(Exception):
    def __init__(self, message: str, plant_id: int, variant_id: int | None = None):
        super().__init__(message)
        self.plant_id = plant_id
        self.variant_id = variant_id


@dataclass
class StockTarget:
    model: type
    id: int
    plant_id: int
    variant_id: int | None


def _target(plant_id: int, variant_id: int | None) -> StockTarget:
    if variant_id:
        return StockTarget(model=PlantVariant, id=variant_id, plant_id=plant_id, variant_id=variant_id)
    return StockTarget(model=Plant, id=plant_id, plant_id=plant_id, variant_id=None)


def _existing_by_reference(db: Session, reference: str | None) -> InventoryTransaction | None:
    if not reference:
        return None
    return db.query(InventoryTransaction).filter(InventoryTransaction.reference == reference).first()


def _record(db, target: StockTarget, transaction_type, quantity, before, after, source_type, source_id, reference, created_by, notes):
    txn = InventoryTransaction(
        plant_id=target.plant_id,
        variant_id=target.variant_id,
        transaction_type=transaction_type,
        quantity=quantity,
        before_quantity=before,
        after_quantity=after,
        source_type=source_type,
        source_id=str(source_id) if source_id is not None else None,
        reference=reference,
        created_by=created_by,
        notes=notes,
    )
    db.add(txn)
    db.flush()
    return txn


def deduct_stock(
    db: Session,
    *,
    plant_id: int,
    variant_id: int | None = None,
    quantity: int,
    source_type: str,
    source_id=None,
    reference: str | None = None,
    transaction_type: str = "SALE",
    created_by: str = "system",
    notes: str = "",
) -> InventoryTransaction:
    """Atomically decrements stock for a sale. Raises InsufficientStockError
    if fewer than `quantity` units are available at the moment the UPDATE
    runs (which is the only moment that matters under concurrency)."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    existing = _existing_by_reference(db, reference)
    if existing:
        return existing

    target = _target(plant_id, variant_id)
    try:
        result = db.execute(
            sa_update(target.model.__table__)
            .where(target.model.id == target.id, target.model.stock_quantity >= quantity)
            .values(stock_quantity=target.model.stock_quantity - quantity)
        )
    except IntegrityError:
        db.rollback()
        raise
    if result.rowcount == 0:
        current = db.query(target.model.stock_quantity).filter(target.model.id == target.id).scalar()
        if current is None:
            raise InsufficientStockError(f"Unknown stock target id={target.id}", plant_id, variant_id)
        raise InsufficientStockError(
            f"Not enough stock (have {current}, need {quantity})", plant_id, variant_id
        )

    after = db.query(target.model.stock_quantity).filter(target.model.id == target.id).scalar()
    before = after + quantity
    try:
        return _record(
            db, target, transaction_type, quantity, before, after, source_type, source_id, reference, created_by, notes
        )
    except IntegrityError:
        # Lost a race on the `reference` uniqueness itself (two concurrent
        # callers with the exact same idempotency key) -- the stock UPDATE
        # above already committed for exactly one of them; the other must
        # not report success as if it deducted too.
        db.rollback()
        winner = _existing_by_reference(db, reference)
        if winner:
            return winner
        raise


def restore_stock(
    db: Session,
    *,
    plant_id: int,
    variant_id: int | None = None,
    quantity: int,
    source_type: str,
    source_id=None,
    reference: str | None = None,
    transaction_type: str = "SALE_REVERSAL",
    created_by: str = "system",
    notes: str = "",
) -> InventoryTransaction:
    """Atomically increments stock back (cancellation, delivery rejection,
    voided offline invoice). Always succeeds (no floor to respect going up),
    idempotent the same way deduct_stock is."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    existing = _existing_by_reference(db, reference)
    if existing:
        return existing

    target = _target(plant_id, variant_id)
    db.execute(
        sa_update(target.model.__table__)
        .where(target.model.id == target.id)
        .values(stock_quantity=target.model.stock_quantity + quantity)
    )
    after = db.query(target.model.stock_quantity).filter(target.model.id == target.id).scalar()
    before = after - quantity
    try:
        return _record(
            db, target, transaction_type, quantity, before, after, source_type, source_id, reference, created_by, notes
        )
    except IntegrityError:
        db.rollback()
        winner = _existing_by_reference(db, reference)
        if winner:
            return winner
        raise


def adjust_stock(
    db: Session,
    *,
    plant_id: int,
    variant_id: int | None = None,
    quantity_delta: int,
    transaction_type: str,
    source_type: str,
    source_id=None,
    reference: str | None = None,
    created_by: str = "system",
    notes: str = "",
) -> InventoryTransaction:
    """General-purpose stock movement for a known signed delta (procurement
    receipts are always positive in this app today, but this stays sign-
    agnostic). A negative delta is still floor-checked the same way
    deduct_stock is; a positive delta always succeeds."""
    if quantity_delta == 0:
        raise ValueError("quantity_delta must be non-zero")
    if quantity_delta > 0:
        return restore_stock(
            db,
            plant_id=plant_id,
            variant_id=variant_id,
            quantity=quantity_delta,
            source_type=source_type,
            source_id=source_id,
            reference=reference,
            transaction_type=transaction_type,
            created_by=created_by,
            notes=notes,
        )
    return deduct_stock(
        db,
        plant_id=plant_id,
        variant_id=variant_id,
        quantity=-quantity_delta,
        source_type=source_type,
        source_id=source_id,
        reference=reference,
        transaction_type=transaction_type,
        created_by=created_by,
        notes=notes,
    )
