import { useEffect, useState } from "react";
import { api } from "../api";
import { Loading, Empty } from "../components/Loading";
import Stars from "../components/Stars";
import GoogleReviewButton from "../components/GoogleReviewButton";
import { useSettings } from "../context/SettingsContext";
import Avatar from "../components/Avatar";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export default function Testimonials() {
  const settings = useSettings();
  const [testimonials, setTestimonials] = useState(null);
  useDocumentTitle("Testimonials | Aaiji Nursery");

  useEffect(() => {
    api.get("/testimonials").then(setTestimonials);
  }, []);

  return (
    <>
      <section className="page-hero">
        <div className="container">
          <h1>Testimonials</h1>
          <p>What our customers say about us.</p>
          {settings.google_review_url && (
            <div style={{ display: "flex", justifyContent: "center", marginTop: 16 }}>
              <GoogleReviewButton url={settings.google_review_url} label="Write a Review on Google" />
            </div>
          )}
        </div>
      </section>

      <section className="section">
        <div className="container">
          {!testimonials ? (
            <Loading />
          ) : testimonials.length === 0 ? (
            <Empty>No testimonials yet.</Empty>
          ) : (
            <div className="grid grid-3">
              {testimonials.map((t) => (
                <div key={t.id} className="card">
                  <div className="card-body">
                    <Stars rating={t.rating} />
                    <p style={{ marginTop: 10, color: "var(--color-text-muted)", flex: 1 }}>
                      &ldquo;{t.message}&rdquo;
                    </p>
                    <div className="testimonial-author">
                      <Avatar name={t.customer_name} src={t.image_url} size={40} />
                      <strong>{t.customer_name}</strong>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
