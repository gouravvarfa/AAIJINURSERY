import GoogleReviewButton, { GoogleG } from "./GoogleReviewButton";

// Single source of truth for "should the Google Review prompt show" --
// Orders.jsx and OrderDetail.jsx both render this instead of duplicating the
// status/url check. Returns null (renders nothing) unless the order is
// Delivered AND a review URL is configured in Site Settings.
export default function GoogleReviewCTA({ orderStatus, reviewUrl, compact = false }) {
  if (orderStatus !== "Delivered" || !reviewUrl) return null;

  if (compact) {
    return <GoogleReviewButton url={reviewUrl} label="Rate us on Google" />;
  }

  return (
    <div className="google-review-card">
      <div className="google-review-card-head">
        <span className="google-review-card-icon">
          <GoogleG size={22} />
        </span>
        <div>
          <strong>Rate us on Google</strong>
          <p>Your feedback helps us grow.</p>
        </div>
      </div>
      <p className="google-review-card-body">
        If you enjoyed your plants and our service, we'd love to hear about your experience.
      </p>
      <GoogleReviewButton url={reviewUrl} label="Write a Review on Google" />
      <p className="google-review-card-foot">Quick &amp; Easy &bull; Takes about 1 minute</p>
    </div>
  );
}
