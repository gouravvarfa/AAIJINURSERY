import { useEffect, useState } from "react";
import { formatIst } from "../communications/time";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";

export default function Sessions() {
  const [items, setItems] = useState(null);
  const [activeOnly, setActiveOnly] = useState(true);
  const [error, setError] = useState("");

  function load() {
    setItems(null);
    api.get(`/admin/rbac/sessions?active_only=${activeOnly}`).then(setItems).catch((err) => setError(err.message));
  }

  useEffect(load, [activeOnly]);

  async function handleRevoke(session) {
    if (!confirm(`Sign out "${session.username}"'s session on this device?`)) return;
    try {
      await api.post(`/admin/rbac/sessions/${session.id}/revoke`);
      load();
    } catch (err) {
      alert(err.message || "Could not revoke session.");
    }
  }

  return (
    <div>
      <div className="admin-page-head">
        <h1>Sessions</h1>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.88rem" }}>
          <input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} />
          Active only
        </label>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {!items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>No sessions found.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Username</th>
                <th>IP Address</th>
                <th>Device / User Agent</th>
                <th>Created</th>
                <th>Last Active</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.id}>
                  <td>
                    {s.username}
                    {s.is_current && (
                      <span className="badge badge-accent" style={{ marginLeft: 8 }}>
                        This device
                      </span>
                    )}
                  </td>
                  <td>{s.ip_address || "—"}</td>
                  <td style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {s.user_agent || "—"}
                  </td>
                  <td>{formatIst(s.created_at)}</td>
                  <td>{formatIst(s.last_seen_at)}</td>
                  <td>
                    <span className={s.revoked_at ? "badge badge-muted" : "badge badge-accent"}>
                      {s.revoked_at ? "Revoked" : "Active"}
                    </span>
                  </td>
                  <td>
                    {!s.revoked_at && (
                      <button className="btn btn-sm btn-danger" onClick={() => handleRevoke(s)}>
                        Revoke
                      </button>
                    )}
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
