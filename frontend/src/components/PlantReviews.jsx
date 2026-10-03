import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import ReviewModal from "./ReviewModal";

function Stars({ value, size }) {
  const rounded = Math.round(value);
  return (
    <span className={`review-stars${size ? ` review-stars-${size}` : ""}`} aria-label={`${value} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span key={n} aria-hidden="true">
          {rounded >= n ? "★" : "☆"}
        </span>
      ))}
    </span>
  );
}

export default function PlantReviews({ plant, data, onChanged }) {
  const { session } = useAuth();
  const isCustomer = session?.type === "customer";

  const [eligibility, setEligibility] = useState(null);
  const [showModal, setShowModal] = useState(false);

  useEffect(() => {
    if (!isCustomer) {
      setEligibility(null);
      return;
    }
    api
      .get(`/customer/plants/${plant.id}/review-eligibility`)
      .then(setEligibility)
      .catch(() => setEligibility(null));
  }, [isCustomer, plant.id]);

  function handleSubmitted() {
    setShowModal(false);
    onChanged?.();
    setEligibility({ eligible: false, reason: "already_reviewed", existing_review: null });
  }

  function renderCta() {
    if (session === undefined) return null; // auth still loading
    if (!isCustomer) {
      return (
        <Link to="/login" className="btn btn-outline dark btn-sm">
          Login to Review
        </Link>
      );
    }
    if (!eligibility) return null;
    if (eligibility.reason === "eligible") {
      return (
        <button type="button" className="btn btn-primary btn-sm" onClick={() => setShowModal(true)}>
          Write a Review
        </button>
      );
    }
    if (eligibility.reason === "already_reviewed") {
      return (
        <button type="button" className="btn btn-outline dark btn-sm" disabled>
          Review Submitted
        </button>
      );
    }
    if (eligibility.reason === "not_delivered") {
      return (
        <button type="button" className="btn btn-outline dark btn-sm" disabled>
          Review available after delivery
        </button>
      );
    }
    return (
      <span className="plant-reviews-hint">
        Purchase this plant and wait for delivery to leave a review.
      </span>
    );
  }

  return (
    <section className="plant-reviews">
      <div className="plant-reviews-header">
        <h2>Customer Reviews</h2>
        {renderCta()}
      </div>

      {data && data.review_count > 0 ? (
        <div className="plant-reviews-summary">
          <span className="plant-reviews-avg">{data.average_rating}</span>
          <div>
            <Stars value={data.average_rating} size="lg" />
            <div className="plant-reviews-count">Based on {data.review_count} review{data.review_count === 1 ? "" : "s"}</div>
          </div>
        </div>
      ) : (
        <div className="plant-reviews-empty">
          <Stars value={0} size="lg" />
          <p>No reviews yet.</p>
          <p style={{ color: "var(--color-text-muted)" }}>Be the first customer to review this plant.</p>
        </div>
      )}

      {data && data.reviews.length > 0 && (
        <div className="plant-reviews-list">
          {data.reviews.map((r) => (
            <div className="plant-review-item" key={r.id}>
              <div className="plant-review-item-head">
                <strong>{r.customer_name}</strong>
                <Stars value={r.rating} />
              </div>
              {r.comment && <p className="plant-review-comment">{r.comment}</p>}
              <div className="plant-review-date">
                {new Date(r.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
              </div>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <ReviewModal plant={plant} onClose={() => setShowModal(false)} onSubmitted={handleSubmitted} />
      )}
    </section>
  );
}
