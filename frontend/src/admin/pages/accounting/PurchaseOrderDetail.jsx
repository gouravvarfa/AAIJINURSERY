import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../../api";
import { Loading } from "../../../components/Loading";
import { purchaseOrderBadgeClass, billBadgeClass } from "../../accounting/accountingStatus";
import AuditTrail from "../../accounting/AuditTrail";

export default function PurchaseOrderDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [order, setOrder] = useState(null);
  const [error, setError] = useState("");
  const [converting, setConverting] = useState(false);
  const [dueDate, setDueDate] = useState("");
  const [billNo, setBillNo] = useState("");
  const [dup, setDup] = useState(""); // set when the supplier already has this bill number
  const [dupReason, setDupReason] = useState("");

  function load() {
    setOrder(null);
    setError("");
    api
      .get(`/admin/accounting/purchase-orders/${id}`)
      .then(setOrder)
      .catch((err) => setError(err.message || "Could not load this purchase order."));
  }

  useEffect(load, [id]);

  async function handleConvert() {
    setConverting(true);
    setError("");
    try {
      const bill = await api.post(`/admin/accounting/purchase-orders/${id}/convert-to-bill`, {
        due_date: dueDate || null,
        supplier_bill_number: billNo,
        allow_duplicate_bill: Boolean(dup),
        duplicate_reason: dup ? dupReason : "",
      });
      navigate(`/admin/accounting/bills/${bill.id}`);
    } catch (err) {
      if (err.status === 409 && String(err.message).startsWith("DUPLICATE_BILL")) {
        setDup(String(err.message).replace("DUPLICATE_BILL: ", ""));
        setError("");
      } else {
        setError(err.message || "Unable to convert this purchase order to a bill.");
      }
      setConverting(false);
    }
  }

  if (error && !order) {
    return <div className="alert alert-error">{error}</div>;
  }
  if (!order) return <Loading />;

  const canConvert = !order.bill && order.status !== "Cancelled" && order.status !== "Voided";

  return (
    <div>
      <div className="admin-page-head">
        <div>
          <h1 style={{ marginBottom: 4 }}>Purchase Order {order.order_number}</h1>
          <span className={`badge ${purchaseOrderBadgeClass(order.status)}`}>{order.status}</span>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {order.status === "Draft" && !order.bill && (
            <Link className="btn btn-sm btn-primary" to={`/admin/accounting/purchase-orders?edit=${order.id}`}>
              Edit
            </Link>
          )}
          <Link className="btn btn-sm btn-outline dark" to="/admin/accounting/purchase-orders">
            &larr; Back to Purchase Orders
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
                    {item.tray_size ? `${item.quantity} trays of ${item.tray_size}` : `Qty ${item.quantity}${item.unit ? " " + item.unit : ""}`} &times; &#8377;{item.unit_price}
                    {item.tray_size ? "/tray" : ""}
                  </div>
                  {item.item_kind && item.item_kind !== "plant" && (
                    <div style={{ color: "var(--color-text-muted)", fontSize: "0.8rem" }}>
                      {{ seed_packet: "Seed packet", medicine: "Medicine", fertilizer: "Fertilizer", supply: "Other supply" }[item.item_kind]}
                      {item.company ? ` · ${item.company}` : ""}
                      {item.lot_number ? ` · Lot ${item.lot_number}` : ""}
                      {item.expiry_date ? ` · Expires ${new Date(item.expiry_date + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}` : ""}
                    </div>
                  )}
                </div>
                <div style={{ fontWeight: 700 }}>&#8377;{item.line_total}</div>
              </div>
            ))}
            <div className="cart-summary-row cart-summary-total" style={{ marginTop: 12 }}>
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

          <AuditTrail tableName="accounting_purchase_orders" recordId={order.id} />
        </div>

        <div>
          <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
            <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Supplier</h2>
            <p style={{ margin: 0 }}>{order.contact?.name}</p>
            <p style={{ margin: 0, color: "var(--color-text-muted)" }}>{order.contact?.email}</p>
            <p style={{ margin: 0, color: "var(--color-text-muted)" }}>{order.contact?.phone}</p>
          </div>

          <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
            <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Related Documents</h2>
            {order.bill ? (
              <p>
                <Link className="btn btn-sm btn-outline dark" to={`/admin/accounting/bills/${order.bill.id}`}>
                  View Bill {order.bill.invoice_number}
                </Link>{" "}
                <span className={`badge ${billBadgeClass(order.bill.status)}`}>{order.bill.status}</span>
              </p>
            ) : (
              <p style={{ color: "var(--color-text-muted)", margin: 0 }}>No bill yet.</p>
            )}
          </div>

          {canConvert && (
            <div className="admin-form-card" style={{ maxWidth: "none" }}>
              <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Convert to Bill</h2>
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
                Making the bill receives every line into its lot in Seed Packet Stock (packet and supply stock, with the lot and expiry above). It does not add ready plant stock. The bill stays Unpaid until you record a payment in Payments Out.
              </p>
              <div className="form-group">
                <label htmlFor="supplier_bill_no">Supplier's bill / invoice number (optional)</label>
                <input id="supplier_bill_no" className="form-control" maxLength={80} value={billNo} onChange={(e) => { setBillNo(e.target.value); setDup(""); }} placeholder="Leave empty if the supplier has not given a bill yet" />
              </div>
              {dup && (
                <div className="alert alert-warning" role="alert">
                  <p style={{ margin: "0 0 8px" }}>{dup}</p>
                  <input className="form-control" placeholder="Why is this a second bill with the same number? (required)" value={dupReason} onChange={(e) => setDupReason(e.target.value)} aria-label="Reason for the duplicate bill number" />
                </div>
              )}
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
                disabled={converting || (dup && dupReason.trim().length < 5)}
                onClick={handleConvert}
              >
                {converting ? "Converting..." : dup ? "Convert anyway" : "Convert to Bill"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
