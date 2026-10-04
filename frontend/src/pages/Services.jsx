import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Loading, Empty } from "../components/Loading";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export default function Services() {
  const [services, setServices] = useState(null);
  useDocumentTitle("Our Services | Aaiji Nursery");

  useEffect(() => {
    api.get("/services").then(setServices);
  }, []);

  return (
    <>
      <section className="page-hero">
        <div className="container">
          <h1>Our Services</h1>
          <p>From one-time setup to ongoing care, everything your plants need.</p>
        </div>
      </section>

      <section className="section">
        <div className="container">
          {!services ? (
            <Loading />
          ) : services.length === 0 ? (
            <Empty>No services listed yet.</Empty>
          ) : (
            <div className="grid grid-3">
              {services.map((s) => (
                <div key={s.id} className="card">
                  <img src={s.image_url} alt={s.name} loading="lazy" />
                  <div className="card-body">
                    <h3 style={{ marginBottom: 6 }}>{s.name}</h3>
                    <p style={{ color: "var(--color-text-muted)", flex: "0 0 auto" }}>
                      {s.description}
                    </p>
                    {s.feature_list?.length > 0 && (
                      <ul className="feature-list" style={{ marginBottom: 16 }}>
                        {s.feature_list.map((f) => (
                          <li key={f}>{f}</li>
                        ))}
                      </ul>
                    )}
                    <div style={{ marginTop: "auto", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                      <div className="price">
                        &#8377;{s.price} <span style={{ fontSize: "0.8rem", color: "var(--color-text-muted)", fontWeight: 400 }}>{s.price_unit}</span>
                      </div>
                      <Link to="/contact" className="btn btn-sm btn-primary">
                        Enquire
                      </Link>
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
