import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { Loading, Empty } from "../components/Loading";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { statusBadgeClass } from "../utils/orderStatus";
import { useSettings } from "../context/SettingsContext";

export default function Orders() {
  useDocumentTitle("My Orders | Aaiji Nursery");
  const { session } = useAuth();
  const settings = useSettings();
  const [orders, setOrders] = useState(null);

  useEffect(() => {
    if (session?.type === "customer") {
      api
        .get("/customer/orders")
        .then(setOrders)
        .catch(() => setOrders([]));
    }
  }, [session]);

  if (session === undefined) return <Loading />;
  if (session === null)
    return (
      <Navigate
        to="/login"
        state={{ from: "/orders", backgroundLocation: { pathname: "/" } }}
        replace
      />
    );
  if (session.type !== "customer") return <Navigate to="/" replace />;

  return (
    <>
      <section className="page-hero">
        <div className="container">
          <h1>My Orders</h1>
          <p>Track and review your past orders.</p>
        </div>
      </section>

      <section className="section">
        <div className="container">
          {!orders ? (
            <Loading />
          ) : orders.length === 0 ? (
            <Empty>
              <p style={{ fontSize: "1.1rem", fontWeight: 600, color: "var(--color-text)" }}>
                You haven't placed any orders yet
              </p>
              <Link to="/plants" className="btn btn-primary" style={{ marginTop: 16 }}>
                Start Shopping
              </Link>
            </Empty>
          ) : (
            <div className="orders-list">
              {orders.map((order) => {
                const items = order.items || [];
                const visibleItems = items.slice(0, 3);
                const extraCount = items.length - visibleItems.length;
                return (
                  <Link key={order.id} to={`/orders/${order.id}`} className="card">
                    <div className="card-body orders-row-body">
                      <div className="orders-row-main">
                        {items.length > 0 && (
                          <div className="orders-row-thumbs">
                            {visibleItems.map((item) => (
                              <img
                                key={item.id}
                                src={item.plant_image_url}
                                alt={item.plant_name}
                                className="orders-row-thumb"
                              />
                            ))}
                            {extraCount > 0 && (
                              <span className="orders-row-thumb-more">+{extraCount}</span>
                            )}
                          </div>
                        )}
                        <div>
                          <div className="orders-row-id">Order #{order.id}</div>
                          {items.length > 0 && (
                            <div className="orders-row-product-names">
                              {items.map((item) => item.plant_name).join(", ")}
                            </div>
                          )}
                          <div className="orders-row-date">{new Date(order.created_at).toLocaleDateString()}</div>
                        </div>
                      </div>
                      <div>
                        <span className={`badge ${statusBadgeClass(order.status)}`}>{order.status}</span>
                        {order.status === "Delivered" && settings?.google_review_url && (
                          <button
                            type="button"
                            className="btn btn-sm btn-outline dark"
                            style={{ display: "block", marginTop: 8 }}
                            onClick={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              window.open(settings.google_review_url, "_blank", "noopener,noreferrer");
                            }}
                          >
                            ⭐ Leave a Google Review
                          </button>
                        )}
                      </div>
                      <div className="orders-row-total">&#8377;{order.total_amount}</div>
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
