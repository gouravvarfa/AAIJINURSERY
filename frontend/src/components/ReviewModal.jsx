import { useState } from "react";
import { api } from "../api";

// Verified-purchase review form -- eligibility (has this customer bought
// this exact plant and had the order marked Delivered?) is entirely
// server-side; this modal only renders once PlantReviews has already
// confirmed eligible=true, and the POST is re-validated independently by
// the backend regardless (see api/routers/api_customer.py create_review).
export default function ReviewModal({ plant, onClose, onSubmitted }) {
  const [rating, setRating] = useState(0);
  const [hoverRating, setHoverRating] = useState(0);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (rating < 1) {
      setError("Please select a star rating.");
      return;
    }
    setError("");
    setSubmitting(true);
    try {
      const review = await api.post("/customer/reviews", {
        plant_id: plant.id,
        rating,
        comment: comment.trim(),
      });
      onSubmitted(review);
    } catch (err) {
      setError(err.message || "Could not submit your review. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
          &times;
        </button>

        <h3 style={{ marginTop: 0 }}>Write a Review</h3>
        <p style={{ color: "var(--color-text-muted)" }}>Share your experience with {plant.name}.</p>

        {error && (
          <div className="alert alert-error" style={{ marginBottom: 16 }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Rating</label>
            <div className="review-star-input" role="radiogroup" aria-label="Rating">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  className="review-star-btn"
                  aria-label={`${n} star${n > 1 ? "s" : ""}`}
                  aria-pressed={rating === n}
                  onClick={() => setRating(n)}
                  onMouseEnter={() => setHoverRating(n)}
                  onMouseLeave={() => setHoverRating(0)}
                >
                  {(hoverRating || rating) >= n ? "★" : "☆"}
                </button>
              ))}
            </div>
          </div>
          <div className="form-group">
            <label htmlFor="review-comment">Comment</label>
            <textarea
              id="review-comment"
              className="form-control"
              rows={4}
              maxLength={2000}
              placeholder="Write your experience..."
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </div>

          <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
            <button type="button" className="btn btn-outline dark" style={{ flex: 1 }} onClick={onClose} disabled={submitting}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" style={{ flex: 1 }} disabled={submitting}>
              {submitting ? "Submitting..." : "Submit Review"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
