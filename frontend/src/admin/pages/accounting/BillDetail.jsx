import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../../api";
import { Loading } from "../../../components/Loading";
import { billBadgeClass } from "../../accounting/accountingStatus";
import AuditTrail from "../../accounting/AuditTrail";
import { printWholePage } from "../../analytics/exportUtils";

function todayDateInput() {
  return new Date().toISOString().slice(0, 10);
}

export default function BillDetail() {
  const { id } = useParams();
  const [bill, setBill] = useState(null);
  const [payments, setPayments] = useState(null);
  const [error, setError] = useState("");
  const [showPaymentModal, setShowPaymentModal] = useState(false);
  const [paymentForm, setPaymentForm] = useState({ amount: 0, method: "Bank", payment_date: todayDateInput(), reference: "", notes: "" });
  const [saving, setSaving] = useState(false);

  function load() {
    setBill(null);
    setError("");
    api
      .get(`/admin/accounting/bills/${id}`)
      .then(setBill)
      .catch((err) => setError(err.message || "Could not load this bill."));
    api.get(`/admin/accounting/payments-out?purchase_id=${id}`).then(setPayments);
  }

  useEffect(load, [id]);

  function openPaymentModal() {
    setPaymentForm({
      amount: bill.balance_due,
      method: "Bank",
      payment_date: todayDateInput(),
      reference: "",
      notes: "",
    });
    setError("");
    setShowPaymentModal(true);
  }

  async function handleRecordPayment(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.post("/admin/accounting/payments-out", {
        purchase_id: bill.id,
        amount: paymentForm.amount,
        method: paymentForm.method,
        payment_date: paymentForm.payment_date,
        reference: paymentForm.reference,
        notes: paymentForm.notes,
      });
      setShowPaymentModal(false);
      load();
    } catch (err) {
      setError(err.message || "Unable to record this payment.");
    } finally {
      setSaving(false);
    }
  }

  if (error && !bill) {
    return <div className="alert alert-error">{error}</div>;
  }
  if (!bill) return <Loading />;

  const canRecordPayment = bill.balance_due > 0 && bill.status !== "Voided" && bill.status !== "Cancelled";

  return (
    <div>
      <div className="admin-page-head">
        <div>
          <h1 style={{ marginBottom: 4 }}>Bill {bill.invoice_number || `#${bill.id}`}</h1>
          <span className={`badge ${billBadgeClass(bill.status)}`}>{bill.status}</span>
        </div>
        <div className="no-print" style={{ display: "flex", gap: 8 }}>
          <button type="button" className="btn btn-sm btn-outline dark" onClick={printWholePage}>
            Print
          </button>
          <a
            className="btn btn-sm btn-outline dark"
            href={`/api/admin/accounting/bills/${id}/pdf`}
            target="_blank"
            rel="noreferrer"
          >
            Download PDF
          </a>
          <Link className="btn btn-sm btn-outline dark" to="/admin/accounting/bills">
            &larr; Back to Bills
          </Link>
        </div>
      </div>

      {error && <div className="alert alert-error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="admin-order-detail-grid">
        <div>
          <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
            <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Line Items</h2>
            {bill.duplicate_override_reason && (
              <div className="alert alert-warning">Same supplier bill number entered again on purpose by {bill.duplicate_override_by}: {bill.duplicate_override_reason}</div>
            )}
            {(bill.supply_lines || []).map((l) => (
              <div key={`s-${l.id}`} className="admin-order-item-row">
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600 }}>{l.item_name}</div>
                  <div style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
                    {l.quantity} {l.unit} &times; &#8377;{l.unit_cost}
                    {l.company ? ` · ${l.company}` : ""}
                    {l.lot_number ? ` · Lot ${l.lot_number}` : ""}
                    {l.expiry_date ? ` · Expires ${new Date(l.expiry_date + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}` : ""}
                  </div>
                </div>
                <div style={{ fontWeight: 700 }}>&#8377;{l.total_cost}</div>
              </div>
            ))}
            {bill.items.map((item) => (
              <div key={item.id} className="admin-order-item-row">
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600 }}>{item.plant_name}</div>
                  <div style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
                    Qty {item.quantity} &times; &#8377;{item.unit_cost}
                  </div>
                </div>
                <div style={{ fontWeight: 700 }}>&#8377;{item.total_cost}</div>
              </div>
            ))}
            <div className="cart-summary-row cart-summary-total" style={{ marginTop: 12 }}>
              <span>Total</span>
              <span>&#8377;{bill.total_cost}</span>
            </div>
            <div className="cart-summary-row">
              <span>Paid</span>
              <span>&#8377;{bill.amount_paid}</span>
            </div>
            <div className="cart-summary-row">
              <span>Balance Due</span>
              <span>&#8377;{bill.balance_due}</span>
            </div>
          </div>

          <div className="admin-form-card" style={{ maxWidth: "none" }}>
            <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Payments</h2>
            {!payments ? (
              <Loading />
            ) : payments.length === 0 ? (
              <p style={{ color: "var(--color-text-muted)", margin: 0 }}>No payments recorded yet.</p>
            ) : (
              <div className="admin-order-status-history">
                {payments.map((p) => (
                  <div key={p.id} className="admin-order-status-history-item">
                    <strong>₹{p.amount.toLocaleString()} via {p.method}</strong>
                    <div className="meta">
                      {new Date(p.payment_date).toLocaleDateString()}
                      {p.reference ? ` · Ref: ${p.reference}` : ""}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <AuditTrail tableName="purchases" recordId={bill.id} />
        </div>

        <div>
          <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
            <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Supplier</h2>
            <p style={{ margin: 0 }}>{bill.contact?.name || bill.supplier || "-"}</p>
            {bill.contact && (
              <>
                <p style={{ margin: 0, color: "var(--color-text-muted)" }}>{bill.contact.email}</p>
                <p style={{ margin: 0, color: "var(--color-text-muted)" }}>{bill.contact.phone}</p>
              </>
            )}
          </div>

          {bill.purchase_order_id && (
            <div className="admin-form-card no-print" style={{ maxWidth: "none", marginBottom: 20 }}>
              <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Related Documents</h2>
              <Link
                className="btn btn-sm btn-outline dark"
                to={`/admin/accounting/purchase-orders/${bill.purchase_order_id}`}
              >
                View Purchase Order
              </Link>
            </div>
          )}

          {canRecordPayment && (
            <div className="admin-form-card no-print" style={{ maxWidth: "none" }}>
              <button type="button" className="btn btn-primary btn-block" onClick={openPaymentModal}>
                Record Payment
              </button>
            </div>
          )}
        </div>
      </div>

      {showPaymentModal && (
        <div className="modal-overlay" onClick={() => !saving && setShowPaymentModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            {!saving && (
              <button
                type="button"
                className="modal-close"
                aria-label="Close"
                onClick={() => setShowPaymentModal(false)}
              >
                &times;
              </button>
            )}
            <h3 style={{ marginTop: 0 }}>Record Payment</h3>
            {error && <div className="alert alert-error">{error}</div>}
            <form onSubmit={handleRecordPayment}>
              <div className="form-group">
                <label htmlFor="amount">Amount (₹)</label>
                <input
                  id="amount"
                  type="number"
                  step="any"
                  className="form-control"
                  required
                  value={paymentForm.amount}
                  onChange={(e) => setPaymentForm((f) => ({ ...f, amount: e.target.valueAsNumber || 0 }))}
                />
              </div>
              <div className="form-group">
                <label htmlFor="method">Method</label>
                <select
                  id="method"
                  className="form-control"
                  value={paymentForm.method}
                  onChange={(e) => setPaymentForm((f) => ({ ...f, method: e.target.value }))}
                >
                  {["Cash", "Bank", "UPI", "Card", "Online", "Other"].map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label htmlFor="payment_date">Payment Date</label>
                <input
                  id="payment_date"
                  type="date"
                  className="form-control"
                  required
                  value={paymentForm.payment_date}
                  onChange={(e) => setPaymentForm((f) => ({ ...f, payment_date: e.target.value }))}
                />
              </div>
              <div className="form-group">
                <label htmlFor="reference">Reference (optional)</label>
                <input
                  id="reference"
                  type="text"
                  className="form-control"
                  value={paymentForm.reference}
                  onChange={(e) => setPaymentForm((f) => ({ ...f, reference: e.target.value }))}
                />
              </div>
              <button className="btn btn-primary btn-block" disabled={saving}>
                {saving ? "Saving..." : "Save Payment"}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
