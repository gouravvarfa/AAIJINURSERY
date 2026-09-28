import { useEffect, useState } from "react";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";

const STATUSES = ["PENDING", "PUBLISHED", "REJECTED"];

export default function Reviews() {
  const [items, setItems] = useState(null);
  const [status, setStatus] = useState("");

  function load() {
    setItems(null);
    const query = status ? `?status=${status}` : "";
    api.get(`/admin/reviews${query}`).then(setItems);
  }

  useEffect(load, [status]);

  async function moderate(item, newStatus) {
    await api.patch(`/admin/reviews/${item.id}`, { status: newStatus });
    load();
  }

  async function remove(item) {
    if (!confirm(`Delete ${item.customer_name}'s review of "${item.plant_name}"?`)) return;
    await api.del(`/admin/reviews/${item.id}`);
    load();
  }

  return (
    <div>
      <div className="admin-page-head">
        <h1>Reviews</h1>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        <button
          className={`btn btn-sm ${status === "" ? "btn-primary" : "btn-outline dark"}`}
          onClick={() => setStatus("")}
        >
          All
        </button>
        {STATUSES.map((s) => (
          <button
            key={s}
            className={`btn btn-sm ${status === s ? "btn-primary" : "btn-outline dark"}`}
            onClick={() => setStatus(s)}
          >
            {s.charAt(0) + s.slice(1).toLowerCase()}
          </button>
        ))}
      </div>

      {!items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>No reviews found.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Customer</th>
                <th>Product</th>
                <th>Rating</th>
                <th>Comment</th>
                <th>Order</th>
                <th>Date</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{item.customer_name}</td>
                  <td>{item.plant_name}</td>
                  <td>{"★".repeat(item.rating)}{"☆".repeat(5 - item.rating)}</td>
                  <td style={{ maxWidth: 280 }}>{item.comment || "-"}</td>
                  <td>#{item.order_id}</td>
                  <td>{new Date(item.created_at).toLocaleDateString()}</td>
                  <td>
                    <span
                      className={`badge ${
                        item.status === "PUBLISHED"
                          ? "badge-accent"
                          : item.status === "REJECTED"
                          ? "badge-danger"
                          : "badge-gold"
                      }`}
                    >
                      {item.status}
                    </span>
                  </td>
                  <td>
                    <div className="row-actions">
                      {item.status !== "PUBLISHED" && (
                        <button className="btn btn-sm btn-outline dark" onClick={() => moderate(item, "PUBLISHED")}>
                          Publish
                        </button>
                      )}
                      {item.status !== "REJECTED" && (
                        <button className="btn btn-sm btn-outline dark" onClick={() => moderate(item, "REJECTED")}>
                          Reject
                        </button>
                      )}
                      <button className="btn btn-sm btn-danger" onClick={() => remove(item)}>
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
