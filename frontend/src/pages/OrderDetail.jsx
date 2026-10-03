import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { useSettings } from "../context/SettingsContext";
import GoogleReviewCTA from "../components/GoogleReviewCTA";
import { Loading, Empty } from "../components/Loading";
import OrderTracker from "../components/OrderTracker";
import CancelOrderModal from "../components/CancelOrderModal";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import {
  CANCELLABLE_STATUSES,
  TEAM_CONFIRMATION_LABELS,
  paymentBadgeClass,
  statusLabel,
  teamConfirmationBadgeClass,
} from "../utils/orderStatus";
import { loadRazorpayScript, withReference } from "../utils/razorpay";

export default function OrderDetail() {
  const { id } = useParams();
  useDocumentTitle(`Order #${id} | Aaiji Nursery`);
  const { session } = useAuth();
  const settings = useSettings();
  const [order, setOrder] = useState(null);
  const [error, setError] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const [showCancelModal, setShowCancelModal] = useState(false);
  const [cancelError, setCancelError] = useState("");
  const cancelSubmittingRef = useRef(false);
  const [payingNow, setPayingNow] = useState(false);
  const [paymentError, setPaymentError] = useState("");

  function load() {
    setOrder(null);
    setError("");
    api
      .get(`/customer/orders/${id}`)
      .then(setOrder)
      .catch((err) =>
        setError(err.status === 404 ? "Order not found." : err.message || "Could not load this order.")
      );
  }

  useEffect(() => {
    if (session?.type === "customer") load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, id]);

  if (session === undefined) return <Loading />;
  if (session === null)
    return (
      <Navigate
        to="/login"
        state={{ from: `/orders/${id}`, backgroundLocation: { pathname: "/" } }}
        replace
      />
    );
  if (session.type !== "customer") return <Navigate to="/" replace />;

  // Feature 2's Pay Now flow: this is the ONLY place a Razorpay payment can
  // be initiated for a normal order -- only reachable once the order card
  // below shows team_confirmation_status === "CONFIRMED" (also enforced on
  // the backend independently of this UI, see create-payment/verify-payment
  // in app/routers/api_customer.py).
  async function handlePayNow() {
    setPaymentError("");
    setPayingNow(true);
    try {
      const withRazorpayOrder = await api.post(`/customer/orders/${id}/create-payment`);
      await loadRazorpayScript();

      const rzp = new window.Razorpay({
        key: import.meta.env.VITE_RAZORPAY_KEY_ID,
        amount: Math.round(withRazorpayOrder.total_amount * 100),
        currency: "INR",
        name: "Aaiji Nursery",
        description: `Order #${withRazorpayOrder.id}`,
        order_id: withRazorpayOrder.razorpay_order_id,
        prefill: {
          name: withRazorpayOrder.delivery_name,
          contact: withRazorpayOrder.delivery_mobile,
          email: session?.email || "",
        },
        theme: { color: "#40916c" },
        handler: async function (response) {
          try {
            await api.post(`/customer/orders/${id}/verify-payment`, {
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
            });
            load();
          } catch (err) {
            setPaymentError(
              withReference(
                err.message ||
                  "We couldn't verify your payment. If money was deducted, please contact support with your order ID.",
                err
              )
            );
          } finally {
            setPayingNow(false);
          }
        },
        modal: {
          ondismiss: async function () {
            setPayingNow(false);
            setPaymentError("Payment was cancelled. You can try again.");
            try {
              await api.post(`/customer/orders/${id}/payment-failed`, { reason: "cancelled_by_user" });
            } catch {
              // best-effort status sync
            }
          },
        },
      });

      rzp.on("payment.failed", async function (response) {
        setPayingNow(false);
        setPaymentError(response.error?.description || "Payment failed. Please try again.");
        try {
          await api.post(`/customer/orders/${id}/payment-failed`, {
            reason: response.error?.description || "payment_failed",
          });
        } catch {
          // best-effort status sync
        }
      });

      rzp.open();
    } catch (err) {
      setPaymentError(withReference(err.message || "Could not start payment. Please try again.", err));
      setPayingNow(false);
    }
  }

  async function handleCancel(remarks) {
    if (cancelSubmittingRef.current) return;
    cancelSubmittingRef.current = true;
    setCancelling(true);
    setCancelError("");
    try {
      await api.post(`/customer/orders/${id}/cancel`, { remarks });
      setShowCancelModal(false);
      load();
    } catch (err) {
      setCancelError(err.message || "Unable to cancel this order. Please try again.");
    } finally {
      cancelSubmittingRef.current = false;
      setCancelling(false);
    }
  }

  return (
    <>
      <section className="page-hero">
        <div className="container">
          <h1>Order Details</h1>
          <p>Track and review this order.</p>
        </div>
      </section>

      <section className="section">
        <div className="container" style={{ maxWidth: 960 }}>
          <Link
            to="/orders"
            className="btn btn-sm btn-outline dark"
            style={{ marginBottom: 20, display: "inline-block" }}
          >
            &larr; Back to My Orders
          </Link>

          {error ? (
            <Empty>{error}</Empty>
          ) : !order ? (
            <Loading />
          ) : (
            <>
              {order.team_confirmation_status !== "CONFIRMED" && (
                <div className="card" style={{ marginBottom: 20 }}>
                  <div className="card-body">
                    <span className={`badge ${teamConfirmationBadgeClass(order.team_confirmation_status)}`}>
                      {TEAM_CONFIRMATION_LABELS[order.team_confirmation_status] || order.team_confirmation_status}
                    </span>
                    {order.team_confirmation_status === "PENDING" && (
                      <p style={{ marginTop: 10, marginBottom: 0 }}>
                        Our team will contact you within 1 hour to confirm delivery availability, charges, and the
                        final order amount. Payment is not available until then.
                      </p>
                    )}
                    {order.team_confirmation_status === "DELIVERY_UNAVAILABLE" && (
                      <p style={{ marginTop: 10, marginBottom: 0 }}>
                        We're sorry, our team is currently unable to deliver this order to your location. Our team
                        will contact you if an alternative arrangement is possible.
                      </p>
                    )}
                  </div>
                </div>
              )}

              {order.team_confirmation_status === "CONFIRMED" &&
                order.payment_method === "Razorpay" &&
                order.payment_status !== "Paid" && (
                  <div className="card" style={{ marginBottom: 20 }}>
                    <div className="card-body">
                      <span className="badge badge-accent" style={{ marginBottom: 10 }}>
                        Order Confirmed — Payment Pending
                      </span>
                      <p>Our team has confirmed we can deliver this order.</p>
                      <div className="cart-summary-row">
                        <span>Products</span>
                        <span>&#8377;{order.subtotal}</span>
                      </div>
                      <div className="cart-summary-row">
                        <span>Delivery</span>
                        <span>&#8377;{order.shipping_fee}</span>
                      </div>
                      <div className="cart-summary-row cart-summary-total">
                        <span>Total</span>
                        <span>&#8377;{order.total_amount}</span>
                      </div>

                      {paymentError && (
                        <div className="alert alert-error" style={{ marginTop: 12 }}>
                          {paymentError}
                        </div>
                      )}

                      <button
                        type="button"
                        className="btn btn-primary btn-block"
                        style={{ marginTop: 12 }}
                        disabled={payingNow}
                        onClick={handlePayNow}
                      >
                        {payingNow ? "Opening Payment..." : "Pay Now"}
                      </button>
                    </div>
                  </div>
                )}

              <div className="order-detail-layout" style={{ marginBottom: 20 }}>
                <div className="card">
                  <div className="card-body">
                    <div className="orders-row-body" style={{ marginBottom: 0 }}>
                      <div>
                        <div className="orders-row-id">Order #{order.id}</div>
                        <div className="orders-row-date">
                          Placed on {new Date(order.created_at).toLocaleDateString()}
                        </div>
                      </div>
                      <span className="badge badge-muted">{statusLabel(order.status)}</span>
                    </div>

                    <OrderTracker status={order.status} />

                    {order.status === "Delivered" && (
                      <div className="delivery-success-banner">
                        <span className="delivery-success-icon">&#10003;</span>
                        <div>
                          <strong>Your order has been delivered successfully!</strong>
                          <p>We hope you're happy with your plants. Thank you for choosing AAIJI Nursery!</p>
                        </div>
                      </div>
                    )}

                    {CANCELLABLE_STATUSES.includes(order.status) && (
                      <button
                        type="button"
                        className="btn btn-sm btn-danger"
                        style={{ marginTop: 20 }}
                        disabled={cancelling}
                        onClick={() => setShowCancelModal(true)}
                      >
                        Cancel Order
                      </button>
                    )}
                  </div>
                </div>

                <GoogleReviewCTA orderStatus={order.status} reviewUrl={settings?.google_review_url} />
              </div>

              <div className="card" style={{ marginBottom: 20 }}>
                <div className="card-body">
                  <h3 style={{ marginTop: 0 }}>Products</h3>
                  {order.items.map((item) => (
                    <div key={item.id} className="cart-summary-row">
                      <span>
                        {item.plant_name}
                        {item.tray_size ? ` (${item.tray_size} Plants Tray)` : ""} &times; {item.quantity} (&#8377;
                        {item.unit_price} each)
                      </span>
                      <span>&#8377;{item.line_total}</span>
                    </div>
                  ))}
                  <div className="cart-summary-row">
                    <span>Subtotal</span>
                    <span>&#8377;{order.subtotal}</span>
                  </div>
                  <div className="cart-summary-row">
                    <span>Shipping</span>
                    <span>&#8377;{order.shipping_fee}</span>
                  </div>
                  <div className="cart-summary-row cart-summary-total">
                    <span>Total</span>
                    <span>&#8377;{order.total_amount}</span>
                  </div>
                </div>
              </div>

              <div className="grid grid-2">
                <div className="card">
                  <div className="card-body">
                    <h3 style={{ marginTop: 0 }}>Delivery Address</h3>
                    <p style={{ margin: 0 }}>{order.delivery_name}</p>
                    <p style={{ margin: 0 }}>{order.delivery_mobile}</p>
                    <p style={{ margin: "8px 0 0" }}>
                      {order.delivery_line1}
                      {order.delivery_line2 ? `, ${order.delivery_line2}` : ""}
                    </p>
                    <p style={{ margin: 0 }}>
                      {order.delivery_city}, {order.delivery_state} - {order.delivery_pincode}
                    </p>
                  </div>
                </div>

                <div className="card">
                  <div className="card-body">
                    <h3 style={{ marginTop: 0 }}>Payment</h3>
                    <p style={{ margin: "0 0 8px" }}>
                      Method: <strong>{order.payment_method}</strong>
                    </p>
                    <span className={`badge ${paymentBadgeClass(order.payment_status)}`}>
                      {order.payment_status}
                    </span>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </section>

      {showCancelModal && (
        <CancelOrderModal
          orderId={order?.id}
          submitting={cancelling}
          error={cancelError}
          onClose={() => {
            setShowCancelModal(false);
            setCancelError("");
          }}
          onConfirm={handleCancel}
        />
      )}
    </>
  );
}
