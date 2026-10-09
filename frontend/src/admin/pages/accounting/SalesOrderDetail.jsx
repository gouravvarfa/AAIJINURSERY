import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../../api";
import { Loading } from "../../../components/Loading";
import { salesOrderBadgeClass, sourceBadgeClass } from "../../accounting/accountingStatus";
import AuditTrail from "../../accounting/AuditTrail";

export default function SalesOrderDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [order, setOrder] = useState(null);
  const [error, setError] = useState("");
  const [converting, setConverting] = useState(false);
  const [dueDate, setDueDate] = useState("");

  function load() {
    setOrder(null);
    setError("");
    api
      .get(`/admin/accounting/sales-orders/${id}`)
      .then(setOrder)
      .catch((err) => setError(err.message || "Could not load this sales order."));
  }

  useEffect(load, [id]);

  async function handleConvert() {
    setConverting(true);
    setError("");
    try {
      const invoice = await api.post(`/admin/accounting/sales-orders/${id}/convert-to-invoice`, {
        due_date: dueDate || null,
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
        <Link className="btn btn-sm btn-outline dark" to="/admin/accounting/sales-orders">
          &larr; Back to Sales Orders
        </Link>
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
