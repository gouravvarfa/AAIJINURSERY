from sqlalchemy.orm import Session

from app.models import SiteSetting

DEFAULT_SETTINGS = {
    "business_name": "Aaiji Nursery",
    "tagline": "Bringing Green Life to Every Home",
    "intro": "Aaiji Nursery has been growing happiness one plant at a time. From indoor greens to full outdoor landscaping, we help your spaces bloom.",
    "about_text": "Aaiji Nursery started as a small family-run plant stall and has grown into a full-service nursery offering plants, gardening supplies, and landscaping services. We believe every home and office deserves a touch of green.",
    "years_experience": "12",
    "team_details": "Our team of 8 horticulturists and landscape designers is passionate about helping your garden thrive, from plant selection to ongoing care.",
    "phone": "+91 91112 12524",
    "whatsapp": "919111212524",
    "email": "lucky9111sharma@gmail.com",
    "address": "Indore, Madhya Pradesh, India",
    "map_embed_url": "https://www.google.com/maps?q=Indore,Madhya+Pradesh,India&output=embed",
    "working_hours": "Mon - Sat: 9:00 AM - 7:00 PM, Sun: 10:00 AM - 4:00 PM",
    "refund_policy": "Plants that arrive damaged or die within 7 days of delivery due to a growing defect are eligible for a free replacement or full refund. Contact support with a photo of the plant.",
    "delivery_days": "3-5 business days for local delivery, 5-9 business days for outstation orders.",
    "payment_methods": "UPI, Credit/Debit Cards, Net Banking, and Cash on Delivery.",
    "facebook_url": "",
    "instagram_url": "",
    "google_review_url": "",
    # Home page hero slider -- one image URL per line, shown in this order.
    "hero_images": "\n".join([
        "https://images.unsplash.com/photo-1466692476868-aef1dfb1e735?w=900",
        "https://images.unsplash.com/photo-1416879595882-3373a0480b5b?w=900",
        "https://images.unsplash.com/photo-1512428813834-c702c7702b78?w=900",
        "https://images.unsplash.com/photo-1466781783364-36c955e42a7f?w=900",
    ]),
    "hero_slide_seconds": "4",
}


def get_settings(db: Session) -> dict:
    rows = db.query(SiteSetting).all()
    settings = dict(DEFAULT_SETTINGS)
    settings.update({row.key: row.value for row in rows if row.value})
    return settings
