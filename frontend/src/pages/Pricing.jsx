import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Loading, Empty } from "../components/Loading";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export default function Pricing() {
  const [plans, setPlans] = useState(null);
  useDocumentTitle("Pricing Plans | Aaiji Nursery");

  useEffect(() => {
    api.get("/pricing-plans").then(setPlans);
  }, []);

  return (
    <>
      <section className="page-hero">
        <div className="container">
          <h1>Pricing Plans</h1>
          <p>Simple, transparent plans for every need.</p>
        </div>
      </section>

      <section className="section">
        <div className="container">
          {!plans ? (
            <Loading />
          ) : plans.length === 0 ? (
            <Empty>No pricing plans configured yet.</Empty>
          ) : (
            <div className="grid grid-3">
              {plans.map((plan) => (
                <div
                  key={plan.id}
                  className="card"
                  style={
                    plan.is_featured
                      ? { border: "2px solid var(--color-accent)", transform: "translateY(-6px)" }
                      : undefined
                  }
                >
                  <div className="card-body" style={{ textAlign: "center" }}>
                    {plan.is_featured && (
                      <span className="badge badge-accent" style={{ marginBottom: 10 }}>
                        Most Popular
                      </span>
                    )}
                    <h3>{plan.name}</h3>
                    <div className="price" style={{ fontSize: "2rem", margin: "10px 0" }}>
                      &#8377;{plan.price}
                      <span style={{ fontSize: "0.9rem", color: "var(--color-text-muted)", fontWeight: 400 }}>
                        {" "}
                        /{plan.billing_cycle}
                      </span>
                    </div>
                    {plan.feature_list?.length > 0 && (
                      <ul className="feature-list" style={{ textAlign: "left", marginBottom: 20 }}>
                        {plan.feature_list.map((f) => (
                          <li key={f}>{f}</li>
                        ))}
                      </ul>
                    )}
                    <Link
                      to="/contact"
                      className={`btn btn-block ${plan.is_featured ? "btn-primary" : "btn-outline dark"}`}
                    >
                      Choose Plan
                    </Link>
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
