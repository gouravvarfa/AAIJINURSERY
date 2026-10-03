import { useEffect, useState } from "react";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";

const STATUSES = ["new", "contacted", "preparing", "available", "rejected", "closed"];

export default function Inquiries() {
  const [items, setItems] = useState(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [historyFor, setHistoryFor] = useState(null);
  const [history, setHistory] = useState(null);

  function load() {
    setItems(null);
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (status) params.set("status", status);
    const query = params.toString() ? `?${params.toString()}` : "";
    api.get(`/admin/inquiries${query}`).then(setItems);
  }

  useEffect(load, [q, status]);

  async function updateStatus(item, newStatus) {
    await api.put(`/admin/inquiries/${item.id}/status`, { status: newStatus });
    load();
  }

  async function remove(item) {
    if (!confirm(`Delete inquiry from "${item.name}"?`)) return;
    await api.del(`/admin/inquiries/${item.id}`);
    load();
  }

  function openHistory(item) {
    setHistoryFor(item);
    setHistory(null);
    api.get(`/admin/inquiries/${item.id}/history`).then(setHistory);
  }

  return (
    <div>
      <div className="admin-page-head">
        <h1>Inquiries</h1>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <input
          type="text"
          className="form-control"
          style={{ maxWidth: 260 }}
          placeholder="Search enquiry #, name, mobile, product..."
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select className="form-control" style={{ maxWidth: 180 }} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All Statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {!items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>No inquiries found.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Enquiry #</th>
                <th>Name</th>
                <th>Mobile</th>
                <th>Product</th>
                <th>Qty</th>
                <th>Requirement</th>
                <th>Received</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{item.enquiry_number || <span className="badge badge-muted">General</span>}</td>
                  <td>{item.name}</td>
                  <td>{item.mobile}</td>
                  <td>
                    {item.plant ? (
                      <a
                        className="btn btn-sm btn-outline dark"
                        href={`/plants/${item.plant.slug}`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {item.plant_name_snapshot || item.plant.name} &rarr;
                      </a>
                    ) : (
                      <span className="badge badge-muted">General</span>
                    )}
                  </td>
                  <td>{item.quantity ?? "-"}</td>
                  <td style={{ maxWidth: 260 }}>{item.requirement || "-"}</td>
                  <td>{new Date(item.created_at).toLocaleDateString()}</td>
                  <td>
                    <select
                      className="form-control"
                      style={{ padding: "6px 10px", minWidth: 130, width: "auto" }}
                      value={item.status}
                      onChange={(e) => updateStatus(item, e.target.value)}
                    >
                      {STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <div className="row-actions">
                      <button className="btn btn-sm btn-outline dark" onClick={() => openHistory(item)}>
                        History
                      </button>
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

      {historyFor && (
        <div className="modal-overlay" onClick={() => setHistoryFor(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <button type="button" className="modal-close" aria-label="Close" onClick={() => setHistoryFor(null)}>
              &times;
            </button>
            <h3 style={{ marginTop: 0 }}>
              Enquiry History{historyFor.enquiry_number ? ` — ${historyFor.enquiry_number}` : ""}
            </h3>
            {!history ? (
              <Loading />
            ) : history.length === 0 ? (
              <Empty>No history yet.</Empty>
            ) : (
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {history.map((h) => (
                  <li key={h.id} style={{ marginBottom: 10 }}>
                    <div style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>
                      {new Date(h.created_at).toLocaleString()}
                    </div>
                    <div>
                      {h.old_status ? `${h.old_status} → ` : ""}
                      <strong>{h.new_status}</strong>
                      {h.changed_by && ` (by ${h.changed_by})`}
                    </div>
                    {h.note && <div style={{ color: "var(--color-text-muted)" }}>{h.note}</div>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
