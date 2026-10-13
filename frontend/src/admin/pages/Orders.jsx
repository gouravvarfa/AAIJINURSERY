import { useEffect, useState } from "react";
import { formatIstDate } from "../communications/time";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";
import { ALL_ORDER_STATUS_OPTIONS, paymentBadgeClass, statusBadgeClass } from "../../utils/orderStatus";

const SEARCH_DEBOUNCE_MS = 400;
const PAGE_SIZE = 20;

export default function AdminOrders() {
  const [urlParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [status, setStatus] = useState(urlParams.get("status") || "");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, status]);

  useEffect(() => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams();
    if (debouncedSearch) params.set("search", debouncedSearch);
    if (status) params.set("status", status);
    params.set("page", String(page));
    params.set("limit", String(PAGE_SIZE));

    let cancelled = false;
    api
      .getPaged(`/admin/orders?${params.toString()}`)
      .then((data) => {
        if (!cancelled) setResult(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || "Could not load orders.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedSearch, status, page]);

  return (
    <div>
      <div className="admin-page-head">
        <h1>Orders</h1>
      </div>

      <div className="admin-form-card" style={{ marginBottom: 20 }}>
        <div className="form-row">
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label htmlFor="order-search">Search</label>
            <input
              id="order-search"
              className="form-control"
              placeholder="Search by Order Number, Customer Name, Phone..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label htmlFor="order-status-filter">Status</label>
            <select
              id="order-status-filter"
              className="form-control"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="">All</option>
              {ALL_ORDER_STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {error ? (
        <div className="alert alert-error">{error}</div>
      ) : loading ? (
        <Loading />
      ) : !result || result.items.length === 0 ? (
        <Empty>
          {debouncedSearch ? `No order found for "${debouncedSearch}".` : "No orders found."}
        </Empty>
      ) : (
        <>
          <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>
            {result.total} order{result.total !== 1 ? "s" : ""} found
          </p>
          <div className="admin-table-wrap admin-orders-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Customer</th>
                  <th>Contact</th>
                  <th>Placed</th>
                  <th>Total</th>
                  <th>Status</th>
                  <th>Payment</th>
                  <th>Call</th>
                  <th>Assigned</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((o) => (
                  <tr key={o.id}>
                    <td>#{o.id}</td>
                    <td>
                      <div>{o.delivery_name || o.customer?.name || "-"}</div>
                      {o.delivery_name && o.customer?.name && o.delivery_name.trim().toLowerCase() !== o.customer.name.trim().toLowerCase() && (
                        <div style={{ color: "var(--color-text-muted)", fontSize: "0.8rem" }}>Account: {o.customer.name}</div>
                      )}
                    </td>
                    <td>
                      <div>{o.customer?.email || "-"}</div>
                      <div style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
                        {o.delivery_mobile || o.customer?.mobile || "-"}
                      </div>
                    </td>
                    <td>{formatIstDate(o.created_at)}</td>
                    <td>&#8377;{o.total_amount}</td>
                    <td>
                      <span className={`badge ${statusBadgeClass(o.status)}`}>{o.status}</span>
                    </td>
                    <td>
                      <span className={`badge ${paymentBadgeClass(o.payment_status)}`}>
                        {o.payment_status}
                      </span>
                    </td>
                    <td>
                      <span className={`badge ${o.call_status === "CONFIRMED" ? "badge-accent" : o.call_status === "PENDING" ? "badge-gold" : "badge-muted"}`}>
                        {o.call_status}
                      </span>
                    </td>
                    <td>{o.assigned_to || <span style={{ color: "var(--color-text-muted)" }}>Unassigned</span>}</td>
                    <td>
                      <div className="row-actions">
                        <Link className="btn btn-sm btn-outline dark" to={`/admin/orders/${o.id}`}>
                          View
                        </Link>
                        {o.delivery_mobile && (
                          <a className="btn btn-sm btn-outline dark" href={`tel:${o.delivery_mobile}`}>
                            📞 Call
                          </a>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Below 700px this replaces the table — a wide multi-column table
              can only be made to fit a phone screen by scrolling, which
              hides most of the data by default; stacked cards keep every
              field visible without horizontal scrolling. */}
          <div className="admin-order-cards">
            {result.items.map((o) => (
              <div key={o.id} className="admin-order-card">
                <div className="admin-order-card-head">
                  <span className="admin-order-card-id">Order #{o.id}</span>
                  <span className={`badge ${statusBadgeClass(o.status)}`}>{o.status}</span>
                </div>
                <div className="admin-order-card-row">
                  <span className="label">Customer</span>
                  <span className="value">{o.delivery_name || o.customer?.name || "-"}</span>
                </div>
                <div className="admin-order-card-row">
                  <span className="label">Contact</span>
                  <span className="value">
                    {o.customer?.email || "-"}
                    {o.delivery_mobile || o.customer?.mobile ? <><br />{o.delivery_mobile || o.customer?.mobile}</> : null}
                  </span>
                </div>
                <div className="admin-order-card-row">
                  <span className="label">Placed</span>
                  <span className="value">{formatIstDate(o.created_at)}</span>
                </div>
                <div className="admin-order-card-row">
                  <span className="label">Total</span>
                  <span className="value">&#8377;{o.total_amount}</span>
                </div>
                <div className="admin-order-card-row">
                  <span className="label">Payment</span>
                  <span className="value">
                    <span className={`badge ${paymentBadgeClass(o.payment_status)}`}>
                      {o.payment_status}
                    </span>
                  </span>
                </div>
                <Link className="btn btn-primary btn-block btn-sm" to={`/admin/orders/${o.id}`}>
                  View Order
                </Link>
              </div>
            ))}
          </div>

          {result.pages > 1 && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 18,
                marginTop: 24,
                fontSize: "0.9rem",
                color: "var(--color-text-muted)",
              }}
            >
              <button
                type="button"
                className="btn btn-outline dark btn-sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Prev
              </button>
              <span>
                Page {result.page} of {result.pages}
              </span>
              <button
                type="button"
                className="btn btn-outline dark btn-sm"
                disabled={page >= result.pages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
