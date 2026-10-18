"""Plants that were grown from a customer's own seeds and are waiting to be handed over.

They are physically in the nursery, so they belong in the stock picture (as Allocated), but they are
not for sale: they never add to "Ready now". Worked out from the seed entries, so there is one source of
truth: held = good plants recorded for the customer on every entry that was not handed over yet."""
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.production_models import SeedEntry


def held_by_target(db: Session) -> Dict[Tuple[int, Optional[int]], int]:
    """{(plant_id, variant_id): units} where units are trays for tray plants and plants otherwise (loose plants that do not fill a tray are not counted)."""
    out: Dict[Tuple[int, Optional[int]], int] = {}
    for e in db.query(SeedEntry).filter(SeedEntry.handed_over_at.is_(None), SeedEntry.prepared_plants > 0):
        units = (e.prepared_plants // e.tray_size) if e.tray_size else e.prepared_plants
        if units > 0:
            key = (e.plant_id, e.variant_id)
            out[key] = out.get(key, 0) + units
    return out
