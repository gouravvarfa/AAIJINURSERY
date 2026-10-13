import { useEffect, useState } from "react";
import { formatIstDate } from "../communications/time";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";
import { statusBadgeClass } from "../../utils/orderStatus";
import WhatsAppActivity from "../communications/WhatsAppActivity";

export default function CustomerDetail() {
  const { id } = useParams();
  const [customer, setCustomer] = useState(null);
  const [error, setError] = useState("");
  const [previewItem, setPreviewItem] = useState(null);

  useEffect(() => {
    setCustomer(null);
    setError("");
    api
      .get(`/admin/customers/${id}`)
      .then(setCustomer)
      .catch((err) => setError(err.message || "Could not load customer."));
  }, [id]);

  return (
    <div>
      <div className="admin-page-head">
        <h1>Customer Details</h1>
        <Link className="btn btn-sm btn-outline dark" to="/admin/customers">
          &larr; Back to Customers
        </Link>
      </div>

      {error ? (
        <div className="alert alert-error">{error}</div>
      ) : !customer ? (
        <Loading />
      ) : (
        <>
          <div className="admin-form-card" style={{ marginBottom: 24 }}>
            <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Profile</h2>
            <div className="form-group">
              <label>Customer ID</label>
              <div>#{customer.id}</div>
            </div>
            <div className="form-group">
              <label>Name</label>
              <div>{customer.name}</div>
            </div>
            <div className="form-group">
              <label>Email</label>
              <div>{customer.email}</div>
            </div>
            <div className="form-group">
              <label>Phone</label>
              <div>{customer.mobile || "-"}</div>
            </div>
            <div className="form-group">
              <label>Registered</label>
              <div>
                {customer.created_at ? formatIstDate(customer.created_at) : "-"}
              </div>
            </div>
          </div>

          <div className="stat-cards">
            <div className="stat-card">
              <div className="num">{customer.total_orders}</div>
              <div className="label">Total Orders</div>
            </div>
            <div className="stat-card">
              <div className="num">&#8377;{customer.total_spent}</div>
              <div className="label">Total Order Value</div>
            </div>
            <div className="stat-card">
              <div className="num">&#8377;{customer.avg_order_value}</div>
              <div className="label">Avg Order Value</div>
            </div>
            <div className="stat-card">
              <div className="num" style={{ fontSize: "1.1rem" }}>
                {customer.last_order_date ? new Date(customer.last_order_date).toLocaleDateString() : "-"}
              </div>
              <div className="label">Last Order Date</div>
            </div>
            <div className="stat-card">
              <div className="num">
                <span className={`badge ${customer.status === "active" ? "badge-accent" : "badge-muted"}`}>
                  {customer.status === "active" ? "Active" : "Inactive"}
                </span>
              </div>
              <div className="label">Customer Status</div>
            </div>
          </div>

          <h2 style={{ fontSize: "1.15rem" }}>Order History</h2>
          {customer.orders.length === 0 ? (
            <Empty>No orders placed yet.</Empty>
          ) : (
            <div className="admin-table-wrap" style={{ marginBottom: 24 }}>
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Order</th>
                    <th>Placed</th>
                    <th>Products</th>
                    <th>Status</th>
                    <th>Payment</th>
                    <th>Total</th>
                  </tr>
                </thead>
                <tbody>
                  {customer.orders.map((o) => (
                    <tr key={o.id}>
                      <td>#{o.id}</td>
                      <td>{formatIstDate(o.created_at)}</td>
                      <td>
                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                          {o.items.map((item) => (
                            <div key={item.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <span>
                                {item.plant_name}
                                {item.tray_size ? ` (${item.tray_size} Plants Tray)` : ""} &times; {item.quantity}
                              </span>
                              <button
                                type="button"
                                className="btn btn-sm btn-outline dark"
                                onClick={() => setPreviewItem(item)}
                              >
                                View
                              </button>
                            </div>
                          ))}
                        </div>
                      </td>
                      <td>
                        <span className={`badge ${statusBadgeClass(o.status)}`}>{o.status}</span>
                      </td>
                      <td>
                        <span className="badge badge-muted">{o.payment_status}</span>
                      </td>
                      <td>&#8377;{o.total_amount}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h2 style={{ fontSize: "1.15rem" }}>Purchase Timeline</h2>
          {customer.orders.length === 0 ? (
            <Empty>No orders placed yet.</Empty>
          ) : (
            <ul className="customer-timeline" style={{ marginBottom: 24 }}>
              {customer.orders.map((o) => (
                <li key={o.id} className="customer-timeline-item">
                  <div className="customer-timeline-date">{formatIstDate(o.created_at)}</div>
                  <div className="customer-timeline-body">
                    <div>
                      Ordered {o.items.map((i) => `${i.quantity}× ${i.plant_name}`).join(", ")}
                    </div>
                    <div className="customer-timeline-meta">
                      &#8377;{o.total_amount} &middot;{" "}
                      <span className={`badge ${statusBadgeClass(o.status)}`}>{o.status}</span>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <h2 style={{ fontSize: "1.15rem" }}>Cart, Wishlist &amp; Addresses</h2>
          <Empty>Not available yet &mdash; will appear here once these features are added.</Empty>

          <WhatsAppActivity customerId={customer.id} title="WhatsApp History" />
        </>
      )}

      {previewItem && (
        <div className="modal-overlay" onClick={() => setPreviewItem(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className="modal-close"
              aria-label="Close"
              onClick={() => setPreviewItem(null)}
            >
              &times;
            </button>
            {previewItem.plant_image_url && (
              <img
                className="modal-product-img"
                src={previewItem.plant_image_url}
                alt={previewItem.plant_name}
              />
            )}
            <h3 style={{ marginTop: 0 }}>{previewItem.plant_name}</h3>
            <div className="modal-product-meta">
              <div>
                <span>Quantity</span>
                <strong>{previewItem.quantity}</strong>
              </div>
              <div>
                <span>Unit Price</span>
                <strong>&#8377;{previewItem.unit_price}</strong>
              </div>
              <div>
                <span>Line Total</span>
                <strong>&#8377;{previewItem.line_total}</strong>
              </div>
            </div>
            {previewItem.plant_slug ? (
              <a
                className="btn btn-primary"
                href={`/plants/${previewItem.plant_slug}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open Full Product Page &rarr;
              </a>
            ) : (
              <span className="badge badge-muted">Product page unavailable</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
