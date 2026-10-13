"""Keeps a website order's Delivery (DEL-x) in step with the order status the
team changes on the order page.

    Packed            -> Delivery is created (if none) and set to "Ready"
    Out For Delivery  -> "Out for Delivery"
    Delivered         -> completed ("Delivered", every item fully delivered)

The order's driver / vehicle are copied onto the delivery. The customer
already gets the order's own WhatsApp for each of these steps, so this sync
deliberately sends NO customer message from the delivery side (that would be
the same news twice); only the driver is told when a delivery is assigned.

Called after the order update has been committed and wrapped so that a sync
problem is logged and can never break the order update itself.
"""
import logging
from datetime import datetime

from app.database import SessionLocal

logger = logging.getLogger("delivery.order_sync")

TERMINAL = {"Delivered", "Partially Delivered", "Failed", "Cancelled"}
ORDER_TO_DELIVERY = {"Packed": "Ready", "Out For Delivery": "Out for Delivery", "Delivered": "Delivered"}


def _address(order) -> str:
    parts = [order.delivery_line1, order.delivery_line2, order.delivery_city, order.delivery_state]
    text = ", ".join(p.strip() for p in parts if p and p.strip())
    return f"{text} - {order.delivery_pincode}" if order.delivery_pincode else text


def _find_delivery(db, order_id: int):
    from app.accounting.models import SalesOrder
    from app.delivery.models import Delivery

    sales_order = db.query(SalesOrder).filter(SalesOrder.order_ref_id == order_id).first()
    if not sales_order:
        return None, None
    delivery = (
        db.query(Delivery)
        .filter(Delivery.sales_order_id == sales_order.id, Delivery.status.notin_(TERMINAL))
        .order_by(Delivery.id.desc())
        .first()
    )
    return sales_order, delivery


def _copy_driver(db, delivery, order, admin: str) -> bool:
    """Returns True when the delivery got a (new) driver."""
    from app.delivery.models import record_delivery_event

    new_driver = False
    if order.driver_id and delivery.driver_id != order.driver_id:
        record_delivery_event(db, delivery.id, "DRIVER_ASSIGNED", delivery.driver_id, order.driver_id, admin)
        delivery.driver_id = order.driver_id
        new_driver = True
    if order.vehicle_id and delivery.vehicle_id != order.vehicle_id:
        record_delivery_event(db, delivery.id, "VEHICLE_ASSIGNED", delivery.vehicle_id, order.vehicle_id, admin)
        delivery.vehicle_id = order.vehicle_id
    return new_driver


def sync_delivery_from_order(order_id: int, new_status: str, admin: str) -> None:
    target = ORDER_TO_DELIVERY.get(new_status)
    if not target:
        return
    db = SessionLocal()
    told_driver = None
    try:
        from app.delivery.models import Delivery, DeliveryItem, record_delivery_event
        from app.models import Order

        order = db.query(Order).filter(Order.id == order_id).first()
        sales_order, delivery = _find_delivery(db, order_id)
        if not order or not sales_order:
            logger.info("no accounting sales order for order %s yet, delivery sync skipped", order_id)
            return

        if delivery is None:
            delivery = Delivery(
                delivery_date=datetime.utcnow(), contact_id=sales_order.contact_id,
                customer_mobile=order.delivery_mobile or "", delivery_address=_address(order),
                sales_order_id=sales_order.id, status="Ready", source="online",
                notes=f"Created from website order #{order.id}", created_by=admin,
            )
            db.add(delivery)
            db.flush()
            delivery.delivery_number = f"DEL-{delivery.id}"
            record_delivery_event(db, delivery.id, "CREATED", None, "Ready", admin, f"From order #{order.id}")
            for line in sales_order.items:
                db.add(DeliveryItem(delivery_id=delivery.id, plant_id=line.plant_id, description=line.description, ordered_quantity=line.quantity))
            db.flush()

        got_driver = _copy_driver(db, delivery, order, admin)

        if target == "Delivered":
            for item in db.query(DeliveryItem).filter(DeliveryItem.delivery_id == delivery.id).all():
                item.delivered_quantity = item.ordered_quantity
            record_delivery_event(db, delivery.id, "COMPLETED", delivery.status, "Delivered", admin, f"Order #{order.id} marked Delivered")
            delivery.status = "Delivered"
        elif delivery.status != target:
            record_delivery_event(db, delivery.id, "STATUS_CHANGED", delivery.status, target, admin, f"Order #{order.id} marked {new_status}")
            delivery.status = target

        db.commit()
        if got_driver:
            told_driver = delivery.id
    except Exception:
        db.rollback()
        logger.exception("delivery sync failed for order_id=%s (the order update itself is unaffected)", order_id)
    finally:
        db.close()

    if told_driver:
        _tell_driver(told_driver)


def sync_delivery_driver(order_id: int, admin: str) -> None:
    """Driver/vehicle just changed on the order: copy it to the open delivery
    (if one exists yet -- otherwise it is picked up when the delivery is made)."""
    db = SessionLocal()
    told_driver = None
    try:
        from app.models import Order

        order = db.query(Order).filter(Order.id == order_id).first()
        _, delivery = _find_delivery(db, order_id)
        if not order or not delivery:
            return
        if _copy_driver(db, delivery, order, admin):
            told_driver = delivery.id
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("delivery driver sync failed for order_id=%s", order_id)
    finally:
        db.close()
    if told_driver:
        _tell_driver(told_driver)


def _tell_driver(delivery_id: int) -> None:
    try:
        from sqlalchemy.orm import joinedload

        from app.delivery.models import Delivery
        from app.delivery.notifications import queue_delivery_assigned_to_driver

        db = SessionLocal()
        try:
            delivery = (
                db.query(Delivery).options(joinedload(Delivery.driver), joinedload(Delivery.contact))
                .filter(Delivery.id == delivery_id).first()
            )
            if delivery and delivery.driver_id:
                queue_delivery_assigned_to_driver(delivery)
        finally:
            db.close()
    except Exception:
        logger.exception("could not notify the driver for delivery %s", delivery_id)
