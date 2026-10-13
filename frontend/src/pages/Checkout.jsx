import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { useCart } from "../context/CartContext";
import { Loading, Empty } from "../components/Loading";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { withReference } from "../utils/razorpay";

const MOBILE_PATTERN = /^[6-9]\d{9}$/;

// Feature 2: every order -- regardless of payment method -- lands here
// first. No payment has been taken or even initiated (Razorpay's order
// isn't created until the team confirms); the customer just waits.
function OrderRequestReceived({ order }) {
  return (
    <section className="section">
      <div className="container" style={{ maxWidth: 640 }}>
        <div className="card">
          <div className="card-body" style={{ textAlign: "center" }}>
            <div
              className="badge badge-gold"
              style={{ fontSize: "0.9rem", padding: "8px 18px", marginBottom: 18 }}
            >
              Order Request Received ✓
            </div>
            <h2 style={{ marginBottom: 8 }}>Thank you, {order.delivery_name}!</h2>
            <p style={{ color: "var(--color-text-muted)" }}>
              Our team will review your delivery location and calculate the delivery charges.
            </p>
            <p style={{ color: "var(--color-text-muted)" }}>
              Our team will contact you within 1 hour to confirm:
              <br />
              &#10003; Delivery availability
              <br />
              &#10003; Delivery charges
              <br />
              &#10003; Final order amount
              <br />
              &#10003; Expected delivery time
            </p>
            <p>
              Please wait for our team to confirm your order before making payment.
            </p>
            <div className="badge badge-muted" style={{ marginBottom: 8 }}>
              Status: WAITING FOR TEAM CONFIRMATION
            </div>

            <div style={{ textAlign: "left", marginTop: 24 }}>
              {order.items.map((item) => (
                <div key={item.id} className="cart-summary-row">
                  <span>
                    {item.plant_name}
                    {item.tray_size ? ` (${item.tray_size} Plants Tray)` : ""} &times; {item.quantity}
                  </span>
                  <span>&#8377;{item.line_total}</span>
                </div>
              ))}
              <div className="cart-summary-row cart-summary-total">
                <span>Products Total (delivery charge added after confirmation)</span>
                <span>&#8377;{order.subtotal}</span>
              </div>
            </div>

            <div style={{ marginTop: 24, display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
              <Link to={`/orders/${order.id}`} className="btn btn-primary">
                Track This Order
              </Link>
              <Link to="/plants" className="btn btn-outline dark">
                Continue Shopping
              </Link>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export default function Checkout() {
  useDocumentTitle("Checkout | Aaiji Nursery");
  const { session } = useAuth();
  const location = useLocation();
  const { items: cartItems, loading: cartLoading, refreshCart } = useCart();

  const buyNowRequest = location.state?.buyNow || null;
  const [buyNowPlant, setBuyNowPlant] = useState(null);
  const [buyNowError, setBuyNowError] = useState("");
  const [loadingBuyNowPlant, setLoadingBuyNowPlant] = useState(Boolean(buyNowRequest));

  const [form, setForm] = useState({
    delivery_name: "",
    delivery_mobile: "",
    delivery_line1: "",
    delivery_line2: "",
    delivery_city: "",
    delivery_state: "",
    delivery_pincode: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [placedOrder, setPlacedOrder] = useState(null);
  const [paymentMethod, setPaymentMethod] = useState("COD");

  // Generated once per checkout-form mount, never regenerated on retry, so a
  // network retry of the same submit resolves to the same order server-side
  // instead of placing a duplicate one (see checkout()'s idempotency_key
  // lookup in app/routers/api_customer.py).
  const idempotencyKeyRef = useRef(crypto.randomUUID());

  const [addresses, setAddresses] = useState([]);
  const [selectedAddressId, setSelectedAddressId] = useState(null);

  useEffect(() => {
    if (session?.type !== "customer") return;
    api
      .get("/customer/addresses")
      .then((data) => {
        setAddresses(data);
        const preferred = data.find((a) => a.is_default) || data[0];
        if (preferred) applyAddress(preferred);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  function applyAddress(address) {
    setSelectedAddressId(address.id);
    setForm({
      delivery_name: address.full_name,
      delivery_mobile: address.mobile,
      delivery_line1: address.line1,
      delivery_line2: address.line2,
      delivery_city: address.city,
      delivery_state: address.state,
      delivery_pincode: address.pincode,
    });
  }

  function useNewAddress() {
    setSelectedAddressId(null);
    setForm({
      delivery_name: "",
      delivery_mobile: "",
      delivery_line1: "",
      delivery_line2: "",
      delivery_city: "",
      delivery_state: "",
      delivery_pincode: "",
    });
  }

  useEffect(() => {
    if (!buyNowRequest?.slug) return;
    setLoadingBuyNowPlant(true);
    api
      .get(`/plants/${buyNowRequest.slug}`)
      .then(setBuyNowPlant)
      .catch(() => setBuyNowError("This product is no longer available."))
      .finally(() => setLoadingBuyNowPlant(false));
  }, [buyNowRequest?.slug]);

  if (session === undefined) return <Loading />;
  if (session === null)
    return (
      <Navigate
        to="/login"
        state={{ from: "/checkout", backgroundLocation: { pathname: "/" } }}
        replace
      />
    );
  if (session.type !== "customer") return <Navigate to="/" replace />;

  const isBuyNow = Boolean(buyNowRequest);
  const buyNowVariant =
    isBuyNow && buyNowPlant
      ? (buyNowPlant.variants || []).find((v) => v.id === buyNowRequest.variantId) || null
      : null;
  const buyNowNeedsVariant =
    isBuyNow && buyNowPlant && (buyNowPlant.variants || []).length > 0 && !buyNowVariant;

  const lines = isBuyNow
    ? buyNowPlant
      ? [{ plant: buyNowPlant, variant: buyNowVariant, quantity: buyNowRequest.quantity }]
      : []
    : cartItems.map((item) => ({
        plant: item.plant,
        variant: item.variant,
        quantity: item.quantity,
        unitPrice: item.unit_price,
      }));

  function lineUnitPrice(line) {
    if (line.unitPrice != null) return line.unitPrice;
    return line.variant ? line.variant.price : (line.plant?.effective_price ?? 0);
  }

  const itemCount = lines.reduce((sum, l) => sum + l.quantity, 0);
  const subtotal = lines.reduce((sum, l) => sum + lineUnitPrice(l) * l.quantity, 0);

  function update(field, value) {
    setSelectedAddressId(null);
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const mobile = form.delivery_mobile.trim();
    if (!MOBILE_PATTERN.test(mobile)) {
      setError("Please enter a valid 10-digit mobile number.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const payload = {
        ...form,
        delivery_mobile: mobile,
        payment_method: paymentMethod,
        idempotency_key: idempotencyKeyRef.current,
      };
      if (isBuyNow) {
        payload.buy_now_plant_id = buyNowRequest.plantId;
        payload.buy_now_variant_id = buyNowRequest.variantId ?? null;
        payload.buy_now_quantity = buyNowRequest.quantity;
      }
      // Feature 2: checkout only ever creates an order awaiting team
      // delivery confirmation now -- no payment gateway is contacted here
      // for either payment method, regardless of which one was chosen.
      const order = await api.post("/customer/checkout", payload);
      setPlacedOrder(order);
      if (!isBuyNow) refreshCart();
    } catch (err) {
      setError(withReference(err.message || "Could not place your order. Please try again.", err));
    } finally {
      setSubmitting(false);
    }
  }

  if (placedOrder) return <OrderRequestReceived order={placedOrder} />;

  if (isBuyNow && loadingBuyNowPlant) return <Loading />;

  if (isBuyNow && (buyNowError || !buyNowPlant)) {
    return (
      <div className="section container">
        <Empty>{buyNowError || "This product is no longer available."}</Empty>
        <div style={{ textAlign: "center" }}>
          <Link to="/plants" className="btn btn-primary">
            Back to Catalog
          </Link>
        </div>
      </div>
    );
  }

  if (!isBuyNow && !cartLoading && cartItems.length === 0) {
    return (
      <div className="section container">
        <Empty>
          <p style={{ fontSize: "1.1rem", fontWeight: 600, color: "var(--color-text)" }}>
            Your cart is empty
          </p>
          <Link to="/plants" className="btn btn-primary" style={{ marginTop: 16 }}>
            Continue Shopping
          </Link>
        </Empty>
      </div>
    );
  }

  return (
    <>
      <section className="page-hero">
        <div className="container">
          <h1>Checkout</h1>
          <p>{isBuyNow ? "Complete your purchase." : "Review your order and enter delivery details."}</p>
        </div>
      </section>

      <section className="section">
        <div className="container cart-layout">
          <div className="card">
            <div className="card-body">
              <h3 style={{ marginTop: 0, marginBottom: 16 }}>Delivery Details</h3>

              {addresses.length > 0 && (
                <div className="form-group">
                  <label>Choose a Saved Address</label>
                  <div className="checkout-address-list">
                    {addresses.map((address) => (
                      <label
                        key={address.id}
                        className={`checkout-address-option ${selectedAddressId === address.id ? "checkout-address-option-active" : ""}`}
                      >
                        <input
                          type="radio"
                          name="saved_address"
                          checked={selectedAddressId === address.id}
                          onChange={() => applyAddress(address)}
                        />
                        <span>
                          <strong>{address.address_type}</strong> &mdash; {address.full_name}, {address.line1}, {address.city}, {address.state} - {address.pincode}
                        </span>
                      </label>
                    ))}
                    <label className={`checkout-address-option ${selectedAddressId === null ? "checkout-address-option-active" : ""}`}>
                      <input
                        type="radio"
                        name="saved_address"
                        checked={selectedAddressId === null}
                        onChange={useNewAddress}
                      />
                      <span>Enter a new address</span>
                    </label>
                  </div>
                </div>
              )}

              {error && <div className="alert alert-error">{error}</div>}

              {buyNowNeedsVariant && (
                <div className="alert alert-error">
                  Please go back and select a tray size for {buyNowPlant.name}.
                </div>
              )}

              <form onSubmit={handleSubmit}>
                <div className="form-row">
                  <div className="form-group">
                    <label htmlFor="delivery_name">Full Name</label>
                    <input
                      id="delivery_name"
                      className="form-control"
                      required
                      value={form.delivery_name}
                      onChange={(e) => update("delivery_name", e.target.value)}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="delivery_mobile">Mobile Number</label>
                    <input
                      id="delivery_mobile"
                      className="form-control"
                      type="tel"
                      inputMode="numeric"
                      maxLength={10}
                      placeholder="10-digit mobile number"
                      required
                      value={form.delivery_mobile}
                      onChange={(e) => update("delivery_mobile", e.target.value.replace(/\D/g, ""))}
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label htmlFor="delivery_line1">Address Line 1</label>
                  <input
                    id="delivery_line1"
                    className="form-control"
                    required
                    value={form.delivery_line1}
                    onChange={(e) => update("delivery_line1", e.target.value)}
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="delivery_line2">Address Line 2 (optional)</label>
                  <input
                    id="delivery_line2"
                    className="form-control"
                    value={form.delivery_line2}
                    onChange={(e) => update("delivery_line2", e.target.value)}
                  />
                </div>

                <div className="form-row">
                  <div className="form-group">
                    <label htmlFor="delivery_city">City</label>
                    <input
                      id="delivery_city"
                      className="form-control"
                      required
                      value={form.delivery_city}
                      onChange={(e) => update("delivery_city", e.target.value)}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="delivery_state">State</label>
                    <input
                      id="delivery_state"
                      className="form-control"
                      required
                      value={form.delivery_state}
                      onChange={(e) => update("delivery_state", e.target.value)}
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label htmlFor="delivery_pincode">Pincode</label>
                  <input
                    id="delivery_pincode"
                    className="form-control"
                    inputMode="numeric"
                    maxLength={6}
                    required
                    value={form.delivery_pincode}
                    onChange={(e) => update("delivery_pincode", e.target.value.replace(/\D/g, ""))}
                  />
                </div>

                <div className="form-group">
                  <label>Payment Method</label>
                  <div className="checkbox-row">
                    <input
                      type="radio"
                      id="pm_cod"
                      name="payment_method"
                      checked={paymentMethod === "COD"}
                      onChange={() => setPaymentMethod("COD")}
                    />
                    <label htmlFor="pm_cod" style={{ margin: 0, fontWeight: 600 }}>
                      Cash on Delivery
                    </label>
                  </div>
                  <div className="checkbox-row" style={{ marginTop: 8 }}>
                    <input
                      type="radio"
                      id="pm_online"
                      name="payment_method"
                      checked={paymentMethod === "Razorpay"}
                      onChange={() => setPaymentMethod("Razorpay")}
                    />
                    <label htmlFor="pm_online" style={{ margin: 0, fontWeight: 600 }}>
                      Online Payment (Razorpay) &mdash; Cards, UPI, Netbanking, Wallets
                    </label>
                  </div>
                </div>

                <button
                  className="btn btn-primary btn-block"
                  disabled={submitting || buyNowNeedsVariant || lines.length === 0}
                >
                  {submitting ? "Submitting Order Request..." : "Submit Order Request"}
                </button>
              </form>
            </div>
          </div>

          <aside className="cart-summary card">
            <div className="card-body">
              <h3 style={{ marginBottom: 16 }}>Order Summary</h3>
              {lines.map((line, idx) => (
                <div className="cart-summary-row" key={line.variant?.id ?? line.plant?.id ?? idx}>
                  <span>
                    {line.plant?.name}
                    {line.variant ? ` (${line.variant.tray_size} Plants Tray)` : ""} &times; {line.quantity}
                  </span>
                  <span>&#8377;{lineUnitPrice(line) * line.quantity}</span>
                </div>
              ))}
              <div className="cart-summary-row">
                <span>Total Items</span>
                <span>{itemCount}</span>
              </div>
              <div className="cart-summary-row cart-summary-total">
                <span>Total</span>
                <span>&#8377;{subtotal}</span>
              </div>
            </div>
          </aside>
        </div>
      </section>
    </>
  );
}
