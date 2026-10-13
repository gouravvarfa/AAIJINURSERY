import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";
import OrderTracker from "../../components/OrderTracker";
import CancelOrderModal from "../../components/CancelOrderModal";
import { useOrderAlerts } from "../OrderAlertContext";
import WhatsAppActivity from "../communications/WhatsAppActivity";
import { formatIst } from "../communications/time";
import {
  CANCELLABLE_STATUSES,
  TEAM_CONFIRMATION_LABELS,
  TRACKER_STEPS,
  paymentBadgeClass,
  statusBadgeClass,
  teamConfirmationBadgeClass,
} from "../../utils/orderStatus";

const FEASIBILITY_OPTIONS = ["APPROVED", "NOT_AVAILABLE", "NEEDS_REVIEW"];
const COST_MODES = ["MANUAL", "AUTO", "FREE"];
const REJECTION_REASONS = ["Too far", "No delivery route", "Vehicle unavailable", "Quantity too large", "Temporary restriction", "Other"];
const CALL_STATUSES = ["PENDING", "CALLED", "NO_ANSWER", "CALL_BACK", "CONFIRMED"];
const CALL_STATUS_LABELS = {
  PENDING: "Pending", CALLED: "Called", NO_ANSWER: "No Answer", CALL_BACK: "Call Back Later", CONFIRMED: "Confirmed",
};

export default function AdminOrderDetail() {
  const { id } = useParams();
  const [order, setOrder] = useState(null);
  const [error, setError] = useState("");
  const [selectedStatus, setSelectedStatus] = useState("");
  const [confirmingStatus, setConfirmingStatus] = useState(null); // status pending confirmation
  const [updating, setUpdating] = useState(false);
  const [showCancelModal, setShowCancelModal] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [actionError, setActionError] = useState("");
  const [toast, setToast] = useState("");
  const statusSubmittingRef = useRef(false);
  const cancelSubmittingRef = useRef(false);

  // Feature 2: delivery review form state
  const [feasibility, setFeasibility] = useState("");
  const [distanceKm, setDistanceKm] = useState("");
  const [costMode, setCostMode] = useState("MANUAL");
  const [finalCost, setFinalCost] = useState("");
  const [reviewNotes, setReviewNotes] = useState("");
  const [savingReview, setSavingReview] = useState(false);
  const [confirmingOrder, setConfirmingOrder] = useState(false);
  const [rejectingDelivery, setRejectingDelivery] = useState(false);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectReason, setRejectReason] = useState(REJECTION_REASONS[0]);
  const [rejectDetail, setRejectDetail] = useState("");
  const [reviewError, setReviewError] = useState("");

  // New Order Alert + Call Management
  const { dismissAlert } = useOrderAlerts();
  const [admins, setAdmins] = useState([]);
  const [updatingCallStatus, setUpdatingCallStatus] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [callError, setCallError] = useState("");
  const [drivers, setDrivers] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [driverId, setDriverId] = useState("");
  const [vehicleId, setVehicleId] = useState("");
  const [savingDriver, setSavingDriver] = useState(false);
  const [driverMsg, setDriverMsg] = useState("");

  function load() {
    setOrder(null);
    setError("");
    api
      .get(`/admin/orders/${id}`)
      .then((data) => {
        setOrder(data);
        setSelectedStatus(data.status);
        setDriverId(data.driver_id ? String(data.driver_id) : "");
        setVehicleId(data.vehicle_id ? String(data.vehicle_id) : "");
        setFeasibility(data.delivery_feasibility === "PENDING" ? "" : data.delivery_feasibility);
        setDistanceKm(data.delivery_distance_km ?? "");
        setCostMode(data.delivery_cost_mode || "MANUAL");
        setFinalCost(data.shipping_fee || "");
        // Opening the order counts as the team having seen the new-order
        // alert (section 7), regardless of whether they got here via the
        // bell/dashboard or just browsed the Orders list directly.
        if (!data.order_acknowledged) {
          api.post(`/admin/orders/${id}/acknowledge`).catch(() => {});
        }
        dismissAlert(Number(id));
      })
      .catch((err) => setError(err.message || "Could not load this order."));
  }

  useEffect(load, [id]);

  useEffect(() => {
    api.get("/admin/admins").then(setAdmins).catch(() => {});
    // Staff without Delivery access just don't get the driver picker.
    api.get("/admin/delivery/drivers").then(setDrivers).catch(() => {});
    api.get("/admin/delivery/vehicles").then(setVehicles).catch(() => {});
  }, []);

  function pickDriver(value) {
    setDriverId(value);
    setDriverMsg("");
    const d = drivers.find((x) => String(x.id) === value);
    if (d && d.assigned_vehicle_id) setVehicleId(String(d.assigned_vehicle_id));
    if (!value) setVehicleId("");
  }

  async function saveDriver() {
    setSavingDriver(true);
    setDriverMsg("");
    try {
      await api.put(`/admin/orders/${id}/driver`, {
        driver_id: driverId ? Number(driverId) : null,
        vehicle_id: vehicleId ? Number(vehicleId) : null,
      });
      setDriverMsg("Saved.");
      load();
    } catch (err) {
      setDriverMsg(err.message || "Could not save the driver.");
    } finally {
      setSavingDriver(false);
    }
  }

  async function updateCallStatus(newStatus) {
    setUpdatingCallStatus(true);
    setCallError("");
    try {
      await api.put(`/admin/orders/${id}/call-status`, { call_status: newStatus });
      load();
    } catch (err) {
      setCallError(err.message || "Could not update call status.");
    } finally {
      setUpdatingCallStatus(false);
    }
  }

  async function assignTo(username) {
    setAssigning(true);
    setCallError("");
    try {
      await api.post(`/admin/orders/${id}/assign`, { assigned_to: username || null });
      load();
    } catch (err) {
      setCallError(err.message || "Could not assign this order.");
    } finally {
      setAssigning(false);
    }
  }

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3000);
    return () => clearTimeout(timer);
  }, [toast]);

  async function confirmStatusUpdate() {
    if (statusSubmittingRef.current) return;
    statusSubmittingRef.current = true;
    setUpdating(true);
    setActionError("");
    try {
      await api.put(`/admin/orders/${id}/status`, { status: confirmingStatus });
      setConfirmingStatus(null);
      setToast(`Order status updated to ${confirmingStatus}`);
      load();
    } catch (err) {
      setActionError(err.message || "Unable to update order status. Please try again.");
    } finally {
      statusSubmittingRef.current = false;
      setUpdating(false);
    }
  }

  async function saveDeliveryReview(e) {
    e.preventDefault();
    setSavingReview(true);
    setReviewError("");
    try {
      await api.put(`/admin/orders/${id}/delivery-review`, {
        delivery_feasibility: feasibility,
        distance_km: distanceKm === "" ? null : Number(distanceKm),
        cost_mode: costMode,
        final_delivery_cost: costMode === "FREE" ? 0 : finalCost === "" ? null : Number(finalCost),
        notes: reviewNotes,
      });
      setToast("Delivery review saved");
      load();
    } catch (err) {
      setReviewError(err.message || "Could not save delivery review.");
    } finally {
      setSavingReview(false);
    }
  }

  async function handleConfirmOrder() {
    if (!confirm("Confirm this order? The customer will be able to pay once confirmed.")) return;
    setConfirmingOrder(true);
    setReviewError("");
    try {
      await api.post(`/admin/orders/${id}/confirm`, {});
      setToast("Order confirmed -- payment enabled for the customer");
      load();
    } catch (err) {
      setReviewError(err.message || "Could not confirm this order.");
    } finally {
      setConfirmingOrder(false);
    }
  }

  async function handleRejectDelivery() {
    setRejectingDelivery(true);
    setReviewError("");
    try {
      await api.post(`/admin/orders/${id}/reject-delivery`, { reason: rejectReason, detail: rejectDetail });
      setShowRejectModal(false);
      setToast("Delivery marked unavailable -- customer notified");
      load();
    } catch (err) {
      setReviewError(err.message || "Could not reject delivery for this order.");
    } finally {
      setRejectingDelivery(false);
    }
  }

  async function handleCancel(remarks) {
    if (cancelSubmittingRef.current) return;
    cancelSubmittingRef.current = true;
    setCancelling(true);
    setActionError("");
    try {
      await api.post(`/admin/orders/${id}/cancel`, { remarks });
      setShowCancelModal(false);
      setToast("Order cancelled");
      load();
    } catch (err) {
      setActionError(err.message || "Unable to cancel this order. Please try again.");
    } finally {
      cancelSubmittingRef.current = false;
      setCancelling(false);
    }
  }

  const currentIndex = order ? TRACKER_STEPS.indexOf(order.status) : -1;
  const availableStatuses = TRACKER_STEPS.filter((s, i) => order && i > currentIndex);

  return (
    <div>
      <div className="admin-page-head">
        <div>
          <h1 style={{ marginBottom: 4 }}>Order {order ? `#${order.id}` : ""}</h1>
          {order && (
            <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span className={`badge ${statusBadgeClass(order.status)}`}>{order.status}</span>
              <span style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
                Placed {formatIst(order.created_at)}
              </span>
            </span>
          )}
        </div>
        <Link className="btn btn-sm btn-outline dark" to="/admin/orders">
          &larr; Back to Orders
        </Link>
      </div>

      {toast && (
        <div className="alert alert-success" style={{ marginBottom: 16 }}>
          {toast}
        </div>
      )}

      {error ? (
        <div className="alert alert-error">{error}</div>
      ) : !order ? (
        <Loading />
      ) : (
        <div className="admin-order-detail-grid">
          {/* Left / main column */}
          <div>
            <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
              <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Ordered Products</h2>
              {order.items.map((item) => (
                <div key={item.id} className="admin-order-item-row">
                  {item.plant_image_url ? (
                    <img className="admin-order-item-thumb" src={item.plant_image_url} alt={item.plant_name} />
                  ) : (
                    <div className="admin-order-item-thumb" />
                  )}
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600 }}>
                      {item.plant_name}
                      {item.tray_size ? ` (${item.tray_size} Plants Tray)` : ""}
                    </div>
                    <div style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
                      Qty {item.quantity} &times; &#8377;{item.unit_price}
                    </div>
                  </div>
                  <div style={{ fontWeight: 700 }}>&#8377;{item.line_total}</div>
                </div>
              ))}

              <div className="cart-summary-row" style={{ marginTop: 12 }}>
                <span>Subtotal</span>
                <span>&#8377;{order.subtotal}</span>
              </div>
              <div className="cart-summary-row">
                <span>Shipping</span>
                <span>&#8377;{order.shipping_fee}</span>
              </div>
              <div className="cart-summary-row cart-summary-total">
                <span>Grand Total</span>
                <span>&#8377;{order.total_amount}</span>
              </div>
            </div>

            <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
              <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Status Timeline</h2>
              <OrderTracker status={order.status} />
            </div>

            <div className="admin-form-card" style={{ maxWidth: "none" }}>
              <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Status History</h2>
              {order.history.length === 0 ? (
                <Empty>No status history yet.</Empty>
              ) : (
                <div className="admin-order-status-history">
                  {order.history.map((h) => (
                    <div key={h.id} className="admin-order-status-history-item">
                      <strong>{h.new_status}</strong>
                      <div className="meta">
                        {formatIst(h.created_at)} &middot; Updated by {h.updated_by || "system"}
                      </div>
                      {h.remarks && <div className="meta">{h.remarks}</div>}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <WhatsAppActivity sourceModule="orders" sourceId={order.id} />
          </div>

          {/* Right / sidebar column */}
          <div>
            <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
              <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Delivery Review</h2>

              <span className={`badge ${teamConfirmationBadgeClass(order.team_confirmation_status)}`} style={{ marginBottom: 14, display: "inline-block" }}>
                {TEAM_CONFIRMATION_LABELS[order.team_confirmation_status] || order.team_confirmation_status}
              </span>

              {reviewError && (
                <div className="alert alert-error" style={{ marginBottom: 14 }}>
                  {reviewError}
                </div>
              )}

              {order.team_confirmation_status === "DELIVERY_UNAVAILABLE" && (
                <p style={{ color: "var(--color-text-muted)" }}>
                  Internal reason: <strong>{order.delivery_rejection_reason || "-"}</strong>
                </p>
              )}

              {order.team_confirmation_status === "CONFIRMED" ? (
                <p style={{ color: "var(--color-text-muted)", margin: 0 }}>
                  Confirmed by {order.team_confirmed_by || "-"} on{" "}
                  {order.team_confirmed_at ? formatIst(order.team_confirmed_at) : "-"}. Delivery
                  charge: &#8377;{order.shipping_fee}.
                </p>
              ) : order.team_confirmation_status === "PENDING" ? (
                <form onSubmit={saveDeliveryReview}>
                  <div className="form-group">
                    <label>Delivery Feasibility</label>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      {FEASIBILITY_OPTIONS.map((opt) => (
                        <button
                          key={opt}
                          type="button"
                          className={`btn btn-sm ${feasibility === opt ? "btn-primary" : "btn-outline dark"}`}
                          onClick={() => setFeasibility(opt)}
                        >
                          {opt.replace("_", " ")}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="form-group">
                    <label htmlFor="distance-km">Distance (km, optional)</label>
                    <input
                      id="distance-km"
                      type="number"
                      min="0"
                      className="form-control"
                      value={distanceKm}
                      onChange={(e) => setDistanceKm(e.target.value)}
                    />
                  </div>

                  <div className="form-group">
                    <label htmlFor="cost-mode">Delivery Cost Mode</label>
                    <select
                      id="cost-mode"
                      className="form-control"
                      value={costMode}
                      onChange={(e) => setCostMode(e.target.value)}
                    >
                      {COST_MODES.map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </select>
                  </div>

                  {costMode === "AUTO" && order.delivery_cost_calculated != null && (
                    <p style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
                      Calculated (₹50 base + ₹15/km): &#8377;{order.delivery_cost_calculated}
                    </p>
                  )}

                  {costMode !== "FREE" && (
                    <div className="form-group">
                      <label htmlFor="final-cost">Final Delivery Cost (&#8377;)</label>
                      <input
                        id="final-cost"
                        type="number"
                        min="0"
                        step="0.01"
                        className="form-control"
                        required
                        value={finalCost}
                        onChange={(e) => setFinalCost(e.target.value)}
                      />
                    </div>
                  )}

                  <div className="form-group">
                    <label htmlFor="review-notes">Delivery Notes (internal)</label>
                    <textarea
                      id="review-notes"
                      className="form-control"
                      rows={2}
                      value={reviewNotes}
                      onChange={(e) => setReviewNotes(e.target.value)}
                    />
                  </div>

                  <button type="submit" className="btn btn-outline dark btn-block" disabled={savingReview || !feasibility}>
                    {savingReview ? "Saving..." : "Save Delivery Review"}
                  </button>

                  <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                    <button
                      type="button"
                      className="btn btn-primary"
                      style={{ flex: 1 }}
                      disabled={confirmingOrder || order.delivery_feasibility !== "APPROVED"}
                      onClick={handleConfirmOrder}
                    >
                      {confirmingOrder ? "Confirming..." : "Confirm Order"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-danger"
                      style={{ flex: 1 }}
                      onClick={() => setShowRejectModal(true)}
                    >
                      Reject Order
                    </button>
                  </div>
                  {order.delivery_feasibility !== "APPROVED" && (
                    <p style={{ color: "var(--color-text-muted)", fontSize: "0.8rem", marginTop: 8 }}>
                      Save the review with feasibility APPROVED before confirming.
                    </p>
                  )}
                </form>
              ) : null}
            </div>

            <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
              <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Call Workflow</h2>

              {callError && (
                <div className="alert alert-error" style={{ marginBottom: 14 }}>
                  {callError}
                </div>
              )}

              <div className="form-group">
                <label>Call Status</label>
                <div>
                  <span className={`badge ${order.call_status === "CONFIRMED" ? "badge-accent" : order.call_status === "PENDING" ? "badge-gold" : "badge-muted"}`}>
                    {CALL_STATUS_LABELS[order.call_status] || order.call_status}
                  </span>
                </div>
              </div>

              {order.delivery_mobile && (
                <a
                  href={`tel:${order.delivery_mobile}`}
                  className="btn btn-primary btn-block"
                  style={{ marginBottom: 12 }}
                  onClick={() => { if (order.call_status === "PENDING") updateCallStatus("CALLED"); }}
                >
                  📞 Call Customer ({order.delivery_mobile})
                </a>
              )}

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {CALL_STATUSES.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={`btn btn-sm ${order.call_status === s ? "btn-primary" : "btn-outline dark"}`}
                    disabled={updatingCallStatus || order.call_status === s}
                    onClick={() => updateCallStatus(s)}
                  >
                    {CALL_STATUS_LABELS[s]}
                  </button>
                ))}
              </div>

              <div className="form-group" style={{ marginTop: 16, marginBottom: 0 }}>
                <label htmlFor="assign-select">Assigned To</label>
                <select
                  id="assign-select"
                  className="form-control"
                  value={order.assigned_to || ""}
                  disabled={assigning}
                  onChange={(e) => assignTo(e.target.value)}
                >
                  <option value="">Unassigned</option>
                  {admins.map((a) => (
                    <option key={a.id} value={a.username}>{a.username}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
              <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Customer Information</h2>
              <div className="form-group">
                <label>Name</label>
                <div>{order.delivery_name || order.customer?.name || "-"}</div>
                {order.delivery_name && order.customer?.name && order.delivery_name.trim().toLowerCase() !== order.customer.name.trim().toLowerCase() && (
                  <div style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>Account name: {order.customer.name}</div>
                )}
              </div>
              <div className="form-group">
                <label>Email</label>
                <div>{order.customer?.email || "-"}</div>
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Phone</label>
                <div>{order.delivery_mobile || order.customer?.mobile || "-"}</div>
                {order.delivery_mobile && order.customer?.mobile && order.delivery_mobile !== order.customer.mobile && (
                  <div style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>Account number: {order.customer.mobile}</div>
                )}
              </div>
            </div>

            <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
              <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Delivery Address</h2>
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

            <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
              <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Payment</h2>
              <p style={{ margin: "0 0 8px" }}>
                Method: <strong>{order.payment_method}</strong>
              </p>
              <span className={`badge ${paymentBadgeClass(order.payment_status)}`}>
                {order.payment_status}
              </span>
            </div>

            {drivers.length > 0 && (
              <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
                <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Driver &amp; Vehicle</h2>
                <div className="form-group">
                  <label htmlFor="order-driver">Driver</label>
                  <select id="order-driver" className="form-control" value={driverId} onChange={(e) => pickDriver(e.target.value)}>
                    <option value="">No driver</option>
                    {drivers.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}{d.phone ? ` - ${d.phone}` : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label htmlFor="order-vehicle">Vehicle</label>
                  <select id="order-vehicle" className="form-control" value={vehicleId} disabled={!driverId} onChange={(e) => setVehicleId(e.target.value)}>
                    <option value="">No vehicle</option>
                    {vehicles.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.name_model ? `${v.name_model} (${v.registration_number})` : v.registration_number}
                      </option>
                    ))}
                  </select>
                </div>
                <button type="button" className="btn btn-primary btn-block" disabled={savingDriver} onClick={saveDriver}>
                  {savingDriver ? "Saving..." : "Save driver"}
                </button>
                {driverMsg && <p style={{ margin: "10px 0 0", fontSize: "0.9rem" }}>{driverMsg}</p>}
                <p style={{ margin: "10px 0 0", fontSize: "0.82rem", color: "var(--color-text-muted)" }}>
                  When this order is marked <strong>Packed</strong> or <strong>Out For Delivery</strong>, the customer's WhatsApp
                  includes the driver&apos;s name, phone number and vehicle. Set this before changing the status.
                </p>
              </div>
            )}

            <div className="admin-form-card" style={{ maxWidth: "none" }}>
              <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Order Status Management</h2>

              {actionError && (
                <div className="alert alert-error" style={{ marginBottom: 14 }}>
                  {actionError}
                </div>
              )}

              <p style={{ margin: "0 0 14px" }}>
                Current Status: <strong>{order.status}</strong>
              </p>

              {order.team_confirmation_status !== "CONFIRMED" ? (
                <Empty>Confirm delivery in the Delivery Review panel before progressing this order's status.</Empty>
              ) : availableStatuses.length > 0 ? (
                <>
                  <div className="form-group">
                    <label htmlFor="status-select">Update Status</label>
                    <select
                      id="status-select"
                      className="form-control"
                      value={selectedStatus}
                      onChange={(e) => setSelectedStatus(e.target.value)}
                    >
                      <option value={order.status}>{order.status} (current)</option>
                      {availableStatuses.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </div>
                  <button
                    type="button"
                    className="btn btn-primary btn-block"
                    disabled={selectedStatus === order.status}
                    onClick={() => {
                      setActionError("");
                      setConfirmingStatus(selectedStatus);
                    }}
                  >
                    Update Status
                  </button>
                </>
              ) : (
                <Empty>This order's status can no longer be changed.</Empty>
              )}

              {CANCELLABLE_STATUSES.includes(order.status) && (
                <button
                  type="button"
                  className="btn btn-danger btn-block"
                  style={{ marginTop: 12 }}
                  onClick={() => {
                    setActionError("");
                    setShowCancelModal(true);
                  }}
                >
                  Cancel Order
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {confirmingStatus && (
        <div className="modal-overlay" onClick={() => !updating && setConfirmingStatus(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            {!updating && (
              <button
                type="button"
                className="modal-close"
                aria-label="Close"
                onClick={() => setConfirmingStatus(null)}
              >
                &times;
              </button>
            )}
            <h3 style={{ marginTop: 0 }}>Update Order Status?</h3>
            <p>
              Are you sure you want to change this order from <strong>{order.status}</strong> to{" "}
              <strong>{confirmingStatus}</strong>?
            </p>
            <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
              <button
                type="button"
                className="btn btn-outline dark"
                style={{ flex: 1 }}
                disabled={updating}
                onClick={() => setConfirmingStatus(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                style={{ flex: 1 }}
                disabled={updating}
                onClick={confirmStatusUpdate}
              >
                {updating ? "Updating status..." : "Confirm Update"}
              </button>
            </div>
          </div>
        </div>
      )}

      {showCancelModal && (
        <CancelOrderModal
          orderId={order?.id}
          submitting={cancelling}
          error={actionError}
          onClose={() => {
            setShowCancelModal(false);
            setActionError("");
          }}
          onConfirm={handleCancel}
        />
      )}

      {showRejectModal && (
        <div className="modal-overlay" onClick={() => !rejectingDelivery && setShowRejectModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            {!rejectingDelivery && (
              <button type="button" className="modal-close" aria-label="Close" onClick={() => setShowRejectModal(false)}>
                &times;
              </button>
            )}
            <h3 style={{ marginTop: 0 }}>Reject Delivery for Order #{order?.id}?</h3>
            <p style={{ color: "var(--color-text-muted)" }}>
              The customer will see a generic "delivery unavailable" message -- this internal reason is never shown
              to them.
            </p>
            <div className="form-group">
              <label htmlFor="reject-reason">Internal Reason</label>
              <select
                id="reject-reason"
                className="form-control"
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
              >
                {REJECTION_REASONS.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>
            {rejectReason === "Other" && (
              <div className="form-group">
                <label htmlFor="reject-detail">Please specify</label>
                <input
                  id="reject-detail"
                  className="form-control"
                  value={rejectDetail}
                  onChange={(e) => setRejectDetail(e.target.value)}
                />
              </div>
            )}
            <div style={{ display: "flex", gap: 10, marginTop: 20 }}>
              <button
                type="button"
                className="btn btn-outline dark"
                style={{ flex: 1 }}
                disabled={rejectingDelivery}
                onClick={() => setShowRejectModal(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-danger"
                style={{ flex: 1 }}
                disabled={rejectingDelivery}
                onClick={handleRejectDelivery}
              >
                {rejectingDelivery ? "Rejecting..." : "Confirm Reject"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
