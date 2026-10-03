import { useMemo, useState, useEffect } from "react";
import { Link, Navigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { Loading, Empty } from "../components/Loading";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { statusBadgeClass } from "../utils/orderStatus";
import { useSettings } from "../context/SettingsContext";
import GoogleReviewCTA from "../components/GoogleReviewCTA";

const CANCELLED_LIKE = ["Cancelled", "Returned", "Refund Initiated", "Refund Completed"];

// Buckets the real backend `status` values into the four filter tabs --
// never a separate/fake status, just a grouping of the existing ones.
function bucketFor(status) {
  if (status === "Delivered") return "Delivered";
  if (CANCELLED_LIKE.includes(status)) return "Cancelled";
  return "Processing";
}

const TABS = ["All Orders", "Delivered", "Processing", "Cancelled"];

export default function Orders() {
  useDocumentTitle("My Orders | Aaiji Nursery");
  const { session } = useAuth();
  const settings = useSettings();
  const [orders, setOrders] = useState(null);
  const [tab, setTab] = useState("All Orders");

  useEffect(() => {
    if (session?.type === "customer") {
      api
        .get("/customer/orders")
        .then(setOrders)
        .catch(() => setOrders([]));
    }
  }, [session]);

  const counts = useMemo(() => {
    const c = { "All Orders": 0, Delivered: 0, Processing: 0, Cancelled: 0 };
    (orders || []).forEach((o) => {
      c["All Orders"] += 1;
      c[bucketFor(o.status)] += 1;
    });
    return c;
  }, [orders]);

  const visibleOrders = useMemo(() => {
    if (!orders) return [];
    if (tab === "All Orders") return orders;
    return orders.filter((o) => bucketFor(o.status) === tab);
  }, [orders, tab]);

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
          <p>Track your orders, view details and manage your purchases.</p>
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
            <>
              <div className="order-filter-tabs">
                {TABS.map((t) => (
                  <button
                    key={t}
                    type="button"
                    className={`order-filter-tab${tab === t ? " active" : ""}`}
                    onClick={() => setTab(t)}
                  >
                    {t} <span className="order-filter-count">{counts[t]}</span>
                  </button>
                ))}
              </div>

              {visibleOrders.length === 0 ? (
                <Empty>No orders in this filter.</Empty>
              ) : (
                <div className="orders-list">
                  {visibleOrders.map((order) => {
                    const items = order.items || [];
                    const visibleItems = items.slice(0, 3);
                    const extraCount = items.length - visibleItems.length;
                    const isDelivered = order.status === "Delivered";
                    return (
                      <div key={order.id} className="order-card-layout">
                        <Link to={`/orders/${order.id}`} className="card order-card">
                          <div className="card-body">
                            <div className="orders-row-body">
                              <div>
                                <div className="orders-row-id">Order #{order.id}</div>
                                <div className="orders-row-date">
                                  {new Date(order.created_at).toLocaleDateString()}
                                </div>
                              </div>
                              <span className={`badge ${statusBadgeClass(order.status)}`}>{order.status}</span>
                            </div>

                            {items.length > 0 && (
                              <div className="orders-row-main" style={{ marginTop: 14, justifyContent: "space-between" }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
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
                                  <div className="orders-row-product-names">
                                    {items.map((item) => item.plant_name).join(", ")}
                                  </div>
                                </div>
                                <div className="orders-row-total">&#8377;{order.total_amount}</div>
                              </div>
                            )}

                            {isDelivered && (
                              <>
                                <div className="order-delivery-info">
                                  {order.delivered_at && (
                                    <div>
                                      <span className="order-delivery-info-label">Delivered On</span>
                                      {new Date(order.delivered_at).toLocaleDateString()}
                                    </div>
                                  )}
                                  {order.delivery_partner && (
                                    <div>
                                      <span className="order-delivery-info-label">Delivery Partner</span>
                                      {order.delivery_partner}
                                    </div>
                                  )}
                                  {(order.delivery_city || order.delivery_state) && (
                                    <div>
                                      <span className="order-delivery-info-label">Delivery Address</span>
                                      {[order.delivery_city, order.delivery_state].filter(Boolean).join(", ")}
                                    </div>
                                  )}
                                </div>
                                <div className="delivery-success-banner">
                                  <span className="delivery-success-icon">&#10003;</span>
                                  <div>
                                    <strong>Your order has been delivered successfully!</strong>
                                    <p>We hope you're happy with your plants. Thank you for choosing AAIJI Nursery!</p>
                                  </div>
                                </div>
                              </>
                            )}
                          </div>
                        </Link>

                        <GoogleReviewCTA orderStatus={order.status} reviewUrl={settings?.google_review_url} />
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </section>
    </>
  );
}
