import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../../api";
import { Loading } from "../../../components/Loading";
import { salesOrderBadgeClass, sourceBadgeClass } from "../../accounting/accountingStatus";
import AuditTrail from "../../accounting/AuditTrail";
import DeliveryPanel from "../../accounting/DeliveryPanel";
import FulfilmentPanel from "../../inventory/FulfilmentPanel";
import CustomerBalanceCard from "../../accounting/CustomerBalanceCard";

export default function SalesOrderDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [order, setOrder] = useState(null);
  const [error, setError] = useState("");
  const [converting, setConverting] = useState(false);
  const [dueDate, setDueDate] = useState("");
  const [received, setReceived] = useState("");
  const [method, setMethod] = useState("Cash");
  const [useAdvance, setUseAdvance] = useState(false);
  const [position, setPosition] = useState(null);
  const [advAmount, setAdvAmount] = useState("");
  const [advMethod, setAdvMethod] = useState("Cash");
  const [advRef, setAdvRef] = useState("");
  const [advBusy, setAdvBusy] = useState(false);
  const [advKey, setAdvKey] = useState(() => `adv-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`);

  function load() {
    setOrder(null);
    setError("");
    api
      .get(`/admin/accounting/sales-orders/${id}`)
      .then(setOrder)
      .catch((err) => setError(err.message || "Could not load this sales order."));
  }

  useEffect(load, [id]);

  async function saveAdvance(e) {
    e.preventDefault();
    if (advBusy) return;
    setAdvBusy(true);
    setError("");
    try {
      const updated = await api.post(`/admin/accounting/sales-orders/${id}/advance`, { amount: Number(advAmount), method: advMethod, reference: advRef, request_id: advKey });
      setOrder(updated);
      setAdvAmount("");
      setAdvRef("");
      setAdvKey(`adv-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`);
    } catch (err) {
      setError(err.message || "Could not record the advance.");
    } finally {
      setAdvBusy(false);
    }
  }

  async function reverseAdvance(receiptId) {
    if (!window.confirm("Remove this advance? Use this only if it was entered by mistake.")) return;
    setError("");
    try {
      await api.post(`/admin/accounting/receipts/${receiptId}/reverse`, {});
      load();
    } catch (err) {
      setError(err.message || "Could not remove the advance.");
    }
  }

  async function handleConvert() {
    setConverting(true);
    setError("");
    try {
      const invoice = await api.post(`/admin/accounting/sales-orders/${id}/convert-to-invoice`, {
        due_date: dueDate || null,
        received_amount: Number(received || 0),
        received_method: method,
        use_advance: useAdvance,
      });
      navigate(`/admin/accounting/invoices/${invoice.id}`);
    } catch (err) {
      setError(err.message || "Unable to convert this sales order to an invoice.");
      setConverting(false);
    }
  }

  if (error && !order) {
    return <div className="alert alert-error">{error}</div>;
  }
  if (!order) return <Loading />;

  const hasInvoice = !!order.invoices?.length;
  const canConvert = !hasInvoice && order.status !== "Cancelled" && order.status !== "Voided";

  return (
    <div>
      <div className="admin-page-head">
        <div>
          <h1 style={{ marginBottom: 4 }}>Sales Order {order.order_number}</h1>
          <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span className={`badge ${salesOrderBadgeClass(order.status)}`}>{order.status}</span>
            <span className={`badge ${sourceBadgeClass(order.source)}`}>
              {order.source === "online" ? "Online" : "Offline"}
            </span>
          </span>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {order.source === "offline" && order.status === "Draft" && !hasInvoice && (
            <Link className="btn btn-sm btn-primary" to={`/admin/accounting/sales-orders?edit=${order.id}`}>
              Edit
            </Link>
          )}
          <Link className="btn btn-sm btn-outline dark" to="/admin/accounting/sales-orders">
            &larr; Back to Sales Orders
          </Link>
        </div>
      </div>

      {error && <div className="alert alert-error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="admin-order-detail-grid">
        <div>
          <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
            <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Line Items</h2>
            {order.items.map((item) => (
              <div key={item.id} className="admin-order-item-row">
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600 }}>{item.description}</div>
                  <div style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
                    {item.tray_size ? `${item.quantity} trays of ${item.tray_size}` : `Qty ${item.quantity}`} &times; &#8377;{item.unit_price}
                    {item.tray_size ? "/tray" : ""}
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
              <span>Tax</span>
              <span>&#8377;{order.tax_total}</span>
            </div>
            <div className="cart-summary-row cart-summary-total">
              <span>Total</span>
              <span>&#8377;{order.total_amount}</span>
            </div>
          </div>

          {order.notes && (
            <div className="admin-form-card" style={{ maxWidth: "none" }}>
              <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Notes</h2>
              <p style={{ margin: 0 }}>{order.notes}</p>
            </div>
          )}

          <AuditTrail tableName="accounting_sales_orders" recordId={order.id} />
        </div>

        <div>
          <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
            <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Contact</h2>
            <p style={{ margin: 0 }}>{order.contact?.name}</p>
            <p style={{ margin: 0, color: "var(--color-text-muted)" }}>{order.contact?.email}</p>
            <p style={{ margin: 0, color: "var(--color-text-muted)" }}>{order.contact?.phone}</p>
            <p style={{ margin: "10px 0 0" }}>
              Delivery date:{" "}
              <strong>
                {order.delivery_date
                  ? new Date(order.delivery_date).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
                  : "not set"}
              </strong>
            </p>
          </div>

          <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
            <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Related Documents</h2>
            {order.source === "online" && order.order_ref_id && (
              <p>
                <Link className="btn btn-sm btn-outline dark" to={`/admin/orders/${order.order_ref_id}`}>
                  View Website Order #{order.order_ref_id}
                </Link>
              </p>
            )}
            {hasInvoice ? (
              <p>
                <Link
                  className="btn btn-sm btn-outline dark"
                  to={`/admin/accounting/invoices/${order.invoices[0].id}`}
                >
                  View Invoice {order.invoices[0].invoice_number}
                </Link>
              </p>
            ) : (
              <p style={{ color: "var(--color-text-muted)", margin: 0 }}>No invoice yet.</p>
            )}
          </div>

          {order.source === "offline" && (
            <FulfilmentPanel
              kind="sales_order"
              items={order.items}
              open={["Draft", "Confirmed", "Invoiced"].includes(order.status)}
              onChanged={load}
            />
          )}

          {order.source === "offline" && <DeliveryPanel salesOrder={order} />}

          {(canConvert || order.advances?.length > 0) && (
            <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
              <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Advance Payment</h2>
              <div className="sp-kpis" style={{ marginBottom: 10 }}>
                <div><span>₹{order.total_amount.toLocaleString("en-IN")}</span>Order total</div>
                <div><span>₹{order.advance_received.toLocaleString("en-IN")}</span>Advance received</div>
                <div className={order.balance_after_advance > 0 ? "warn" : ""}><span>₹{order.balance_after_advance.toLocaleString("en-IN")}</span>Balance to pay</div>
              </div>
              {order.advances.map((a) => (
                <p key={a.id} style={{ margin: "4px 0", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  <strong>₹{a.amount.toLocaleString("en-IN")}</strong> · {a.method} · {new Date(a.payment_date).toLocaleDateString("en-IN")}{a.reference ? ` · ${a.reference}` : ""}
                  {a.status === "Reversed" ? <span className="badge badge-muted">Removed</span> : a.remaining < a.amount ? <span className="badge badge-muted">Used on invoice</span> : canConvert ? (
                    <button type="button" className="btn btn-sm btn-outline dark" onClick={() => reverseAdvance(a.id)}>Remove</button>
                  ) : null}
                </p>
              ))}
              {canConvert && (
                <form onSubmit={saveAdvance} style={{ marginTop: 10 }}>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <input className="form-control" style={{ flex: "1 1 120px" }} inputMode="decimal" placeholder="Advance amount (₹)" aria-label="Advance amount" value={advAmount} onChange={(e) => setAdvAmount(e.target.value.replace(/[^0-9.]/g, ""))} />
                    <select className="form-control" style={{ flex: "0 1 120px" }} value={advMethod} onChange={(e) => setAdvMethod(e.target.value)} aria-label="Advance payment method">
                      {["Cash", "Bank", "UPI", "Card", "Online", "Other"].map((m) => <option key={m}>{m}</option>)}
                    </select>
                    <input className="form-control" style={{ flex: "1 1 140px" }} maxLength={120} placeholder="Reference (optional)" aria-label="Advance reference" value={advRef} onChange={(e) => setAdvRef(e.target.value)} />
                    <button className="btn btn-primary" disabled={advBusy || !(Number(advAmount) > 0)}>{advBusy ? "Saving..." : "Record Advance"}</button>
                  </div>
                  <small className="stock-hint">It lowers what the customer owes at once and is adjusted automatically on the invoice when you convert this order.</small>
                </form>
              )}
            </div>
          )}

          {canConvert && (
            <div className="admin-form-card" style={{ maxWidth: "none" }}>
              <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Convert to Invoice</h2>
              <div className="form-group">
                <label htmlFor="due_date">Due Date (optional)</label>
                <input
                  id="due_date"
                  type="date"
                  className="form-control"
                  value={dueDate}
                  onChange={(e) => setDueDate(e.target.value)}
                />
              </div>
              <CustomerBalanceCard key={order.advance_received} contactId={order.contact_id} onLoaded={setPosition} />
              {position?.advance - (order.advance_remaining || 0) > 0.004 && (
                <label className="sp-check" style={{ margin: "8px 0" }}>
                  <input type="checkbox" checked={useAdvance} onChange={(e) => setUseAdvance(e.target.checked)} />
                  Use the customer's other advance (₹{Math.max(position.advance - (order.advance_remaining || 0), 0).toLocaleString("en-IN")}) on this bill
                </label>
              )}
              <div className="form-group">
                <label htmlFor="received_now">Money received now (optional)</label>
                <div style={{ display: "flex", gap: 8 }}>
                  <input id="received_now" className="form-control" inputMode="decimal" placeholder="0" value={received} onChange={(e) => setReceived(e.target.value.replace(/[^0-9.]/g, ""))} />
                  <select className="form-control" style={{ maxWidth: 120 }} value={method} onChange={(e) => setMethod(e.target.value)} aria-label="Payment method">
                    {["Cash", "Bank", "UPI", "Card", "Online", "Other"].map((m) => <option key={m}>{m}</option>)}
                  </select>
                </div>
                <small className="stock-hint">Shown on the invoice as Received and fixed there. If it is more than the bill, the extra is kept as the customer's advance.</small>
              </div>
              <button
                type="button"
                className="btn btn-primary btn-block"
                disabled={converting}
                onClick={handleConvert}
              >
                {converting ? "Converting..." : "Convert to Invoice"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
