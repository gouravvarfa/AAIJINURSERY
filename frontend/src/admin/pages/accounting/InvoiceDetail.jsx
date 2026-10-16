import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../../api";
import { Loading } from "../../../components/Loading";
import { invoiceBadgeClass, salesOrderBadgeClass, sourceBadgeClass } from "../../accounting/accountingStatus";
import AuditTrail from "../../accounting/AuditTrail";
import WhatsAppActivity from "../../communications/WhatsAppActivity";
import { printWholePage } from "../../analytics/exportUtils";
import CustomerBalanceCard from "../../accounting/CustomerBalanceCard";

function todayDateInput() {
  return new Date().toISOString().slice(0, 10);
}

export default function InvoiceDetail() {
  const { id } = useParams();
  const [invoice, setInvoice] = useState(null);
  const [payments, setPayments] = useState(null);
  const [error, setError] = useState("");
  const [showPaymentModal, setShowPaymentModal] = useState(false);
  const [paymentForm, setPaymentForm] = useState({ amount: 0, method: "Cash", payment_date: todayDateInput(), reference: "", notes: "" });
  const [saving, setSaving] = useState(false);
  const [voiding, setVoiding] = useState(false);
  const [voidModal, setVoidModal] = useState(null); // { action, method, notes, paid }
  const [position, setPosition] = useState(null);
  const [balanceKey, setBalanceKey] = useState(0);
  const [info, setInfo] = useState("");

  function load() {
    setInvoice(null);
    setError("");
    api
      .get(`/admin/accounting/invoices/${id}`)
      .then(setInvoice)
      .catch((err) => setError(err.message || "Could not load this invoice."));
    api.get("/admin/accounting/payments-in").then((all) =>
      setPayments(all.filter((p) => p.invoice_id === Number(id)))
    );
  }

  useEffect(load, [id]);

  function openPaymentModal() {
    setPaymentForm({
      amount: invoice.balance_due,
      method: "Cash",
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
      await api.post("/admin/accounting/payments-in", {
        invoice_id: invoice.id,
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

  async function handleVoid(payload) {
    setVoiding(true);
    try {
      await api.post(`/admin/accounting/invoices/${id}/void`, payload || {});
      setVoidModal(null);
      setBalanceKey((k) => k + 1);
      load();
    } catch (err) {
      setError(err.message || "Unable to void this invoice.");
    } finally {
      setVoiding(false);
    }
  }

  if (error && !invoice) {
    return <div className="alert alert-error">{error}</div>;
  }
  if (!invoice) return <Loading />;

  function startVoid() {
    const paid = (payments || []).reduce((n, p) => n + p.amount, 0);
    if (paid > 0) {
      setVoidModal({ action: "advance", method: "Cash", notes: "", paid });
      return;
    }
    if (confirm("Void this invoice? It will be kept on record, marked Voided, and can no longer be edited.")) handleVoid();
  }

  async function useAdvance() {
    setError("");
    try {
      const r = await api.post(`/admin/accounting/invoices/${id}/apply-advance`, {});
      setInfo(`Rs ${r.applied.toLocaleString("en-IN")} of the customer's advance was used on this invoice.`);
      setBalanceKey((k) => k + 1);
      load();
    } catch (err) {
      setError(err.message || "Unable to use the advance.");
    }
  }

  const canRecordPayment = invoice.balance_due > 0 && invoice.status !== "Voided" && invoice.status !== "Cancelled";
  const canVoid = invoice.source === "offline" && invoice.status !== "Voided" && invoice.status !== "Cancelled";

  return (
    <div>
      <div className="admin-page-head">
        <div>
          <h1 style={{ marginBottom: 4 }}>Invoice {invoice.invoice_number}</h1>
          <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span className={`badge ${invoiceBadgeClass(invoice.status)}`}>{invoice.status}</span>
            <span className={`badge ${sourceBadgeClass(invoice.source)}`}>
              {invoice.source === "online" ? "Online" : "Offline"}
            </span>
          </span>
        </div>
        <div className="no-print" style={{ display: "flex", gap: 8 }}>
          <button type="button" className="btn btn-sm btn-outline dark" onClick={printWholePage}>
            Print
          </button>
          <a
            className="btn btn-sm btn-outline dark"
            href={`/api/admin/accounting/invoices/${id}/pdf`}
            target="_blank"
            rel="noreferrer"
          >
            Download PDF
          </a>
          <Link className="btn btn-sm btn-outline dark" to="/admin/accounting/invoices">
            &larr; Back to Invoices
          </Link>
        </div>
      </div>

      {error && <div className="alert alert-error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="admin-order-detail-grid">
        <div>
          <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
            <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Line Items</h2>
            {invoice.items.map((item) => (
              <div key={item.id} className="admin-order-item-row">
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600 }}>{item.description}</div>
                  <div style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
                    Qty {item.quantity} &times; &#8377;{item.unit_price}
                  </div>
                </div>
                <div style={{ fontWeight: 700 }}>&#8377;{item.line_total}</div>
              </div>
            ))}
            <div className="cart-summary-row" style={{ marginTop: 12 }}>
              <span>Subtotal</span>
              <span>&#8377;{invoice.subtotal}</span>
            </div>
            <div className="cart-summary-row">
              <span>Tax</span>
              <span>&#8377;{invoice.tax_total}</span>
            </div>
            <div className="cart-summary-row cart-summary-total">
              <span>Total</span>
              <span>&#8377;{invoice.total_amount}</span>
            </div>
            <div className="cart-summary-row">
              <span>Paid</span>
              <span>&#8377;{invoice.amount_paid}</span>
            </div>
            <div className="cart-summary-row">
              <span>Balance Due</span>
              <span>&#8377;{invoice.balance_due}</span>
            </div>
            {invoice.previous_balance != null && (
              <div className="invoice-frozen" aria-label="Balances fixed when this invoice was generated">
                <h3>Fixed when this invoice was generated</h3>
                <div className="cart-summary-row"><span>Previous {invoice.previous_balance < 0 ? "advance credit" : "balance"}</span><span>&#8377;{Math.abs(invoice.previous_balance).toLocaleString("en-IN")}</span></div>
                <div className="cart-summary-row"><span>Received at billing</span><span>&#8377;{(invoice.received_at_issue || 0).toLocaleString("en-IN")}</span></div>
                {invoice.advance_applied_at_issue > 0 && <div className="cart-summary-row"><span>Advance adjusted</span><span>&#8377;{invoice.advance_applied_at_issue.toLocaleString("en-IN")}</span></div>}
                {(() => {
                  const cur = invoice.previous_balance + invoice.total_amount - (invoice.received_at_issue || 0);
                  return <div className="cart-summary-row cart-summary-total"><span>Current {cur < 0 ? "advance credit" : "balance"}</span><span>&#8377;{Math.abs(cur).toLocaleString("en-IN")}</span></div>;
                })()}
                <small className="stock-hint">Money received after billing changes the customer's balance below, not these fixed numbers.</small>
              </div>
            )}
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
                      {p.source === "online" ? " · Auto-synced from website" : ""}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <AuditTrail tableName="accounting_invoices" recordId={invoice.id} />
          <WhatsAppActivity sourceModule="accounting" sourceId={`INV-${invoice.id}`} />
        </div>

        <div>
          <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
            <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Contact</h2>
            <p style={{ margin: 0 }}>{invoice.contact?.name}</p>
            <p style={{ margin: 0, color: "var(--color-text-muted)" }}>{invoice.contact?.email}</p>
            <p style={{ margin: 0, color: "var(--color-text-muted)" }}>{invoice.contact?.phone}</p>
          </div>

          <div className="admin-form-card no-print" style={{ maxWidth: "none", marginBottom: 20 }}>
            <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Customer balance today</h2>
            <CustomerBalanceCard contactId={invoice.contact_id} refreshKey={balanceKey + (invoice.amount_paid || 0)} onLoaded={setPosition} />
            {info && <div className="alert alert-success" role="status" style={{ marginTop: 10 }}>{info}</div>}
            {canRecordPayment && position?.advance > 0 && (
              <button type="button" className="btn btn-sm btn-outline dark" style={{ marginTop: 10 }} onClick={useAdvance}>Use customer's advance on this invoice</button>
            )}
          </div>

          <div className="admin-form-card no-print" style={{ maxWidth: "none", marginBottom: 20 }}>
            <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Related Documents</h2>
            {invoice.sales_order && (
              <p>
                <Link
                  className="btn btn-sm btn-outline dark"
                  to={`/admin/accounting/sales-orders/${invoice.sales_order.id}`}
                >
                  View Sales Order {invoice.sales_order.order_number}
                </Link>{" "}
                <span className={`badge ${salesOrderBadgeClass(invoice.sales_order.status)}`}>
                  {invoice.sales_order.status}
                </span>
              </p>
            )}
            {invoice.source === "online" && (
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
                This invoice was auto-generated from a real website order. To cancel it, cancel the order
                itself from the Orders page.
              </p>
            )}
          </div>

          {canRecordPayment && (
            <div className="admin-form-card no-print" style={{ maxWidth: "none", marginBottom: 20 }}>
              <button type="button" className="btn btn-primary btn-block" onClick={openPaymentModal}>
                Record Payment
              </button>
            </div>
          )}

          {canVoid && (
            <div className="admin-form-card no-print" style={{ maxWidth: "none" }}>
              <button type="button" className="btn btn-danger btn-block" disabled={voiding} onClick={startVoid}>
                {voiding ? "Voiding..." : "Void Invoice"}
              </button>
            </div>
          )}
        </div>
      </div>

      {voidModal && (
        <div className="modal-overlay" onClick={() => !voiding && setVoidModal(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>Void this invoice</h3>
            <p>Rs {voidModal.paid.toLocaleString("en-IN")} was already paid on this invoice. The money is never deleted. Choose what happened to it:</p>
            <label className="sp-check" style={{ display: "flex", margin: "8px 0" }}>
              <input type="radio" name="void-action" checked={voidModal.action === "advance"} onChange={() => setVoidModal({ ...voidModal, action: "advance" })} />
              Keep it as the customer's advance (they can use it on a later bill)
            </label>
            <label className="sp-check" style={{ display: "flex", margin: "8px 0" }}>
              <input type="radio" name="void-action" checked={voidModal.action === "refund"} onChange={() => setVoidModal({ ...voidModal, action: "refund" })} />
              Refund it to the customer (it was handed back)
            </label>
            <div className="form-group">
              <label htmlFor="void_notes">Note (optional)</label>
              <input id="void_notes" className="form-control" value={voidModal.notes} onChange={(e) => setVoidModal({ ...voidModal, notes: e.target.value })} />
            </div>
            <button type="button" className="btn btn-danger" disabled={voiding} onClick={() => handleVoid({ payment_action: voidModal.action, method: voidModal.method, notes: voidModal.notes })}>{voiding ? "Voiding..." : "Void invoice"}</button>{" "}
            <button type="button" className="btn btn-outline dark" disabled={voiding} onClick={() => setVoidModal(null)}>Cancel</button>
          </div>
        </div>
      )}

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
              {Number(paymentForm.amount) > invoice.balance_due && (
                <div className="alert alert-warning">The invoice needs only Rs {invoice.balance_due}. The extra Rs {(Number(paymentForm.amount) - invoice.balance_due).toLocaleString("en-IN")} will be kept as the customer's advance.</div>
              )}
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
