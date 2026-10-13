import { useEffect, useState } from "react";
import { formatIst } from "../communications/time";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";

export default function LoginAttempts() {
  const [identifier, setIdentifier] = useState("");
  const [success, setSuccess] = useState("");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  function load() {
    setError("");
    setResult(null);
    const params = new URLSearchParams({ page: String(page), limit: "50" });
    if (identifier) params.set("identifier", identifier);
    if (success) params.set("success", success);
    api.getPaged(`/admin/rbac/login-attempts?${params}`).then(setResult).catch((err) => setError(err.message));
  }

  useEffect(load, [identifier, success, page]);

  return (
    <div>
      <div className="admin-page-head">
        <h1>Login Attempts</h1>
      </div>

      <div className="form-row">
        <div className="form-group">
          <label>Identifier</label>
          <input
            className="form-control"
            placeholder="username or email"
            value={identifier}
            onChange={(e) => { setPage(1); setIdentifier(e.target.value); }}
          />
        </div>
        <div className="form-group">
          <label>Result</label>
          <select className="form-control" value={success} onChange={(e) => { setPage(1); setSuccess(e.target.value); }}>
            <option value="">All</option>
            <option value="true">Success</option>
            <option value="false">Failed</option>
          </select>
        </div>
      </div>

      {error ? (
        <div className="alert alert-error">
          Could not load login attempts. <button className="btn btn-outline dark" onClick={load}>Retry</button>
        </div>
      ) : !result ? (
        <Loading />
      ) : result.items.length === 0 ? (
        <Empty>No login attempts match these filters.</Empty>
      ) : (
        <>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Identifier</th>
                  <th>Result</th>
                  <th>Reason</th>
                  <th>IP Address</th>
                  <th>Device / User Agent</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((a) => (
                  <tr key={a.id}>
                    <td>{formatIst(a.created_at)}</td>
                    <td>{a.identifier}</td>
                    <td>
                      <span className={a.success ? "badge badge-accent" : "badge badge-danger"}>
                        {a.success ? "Success" : "Failed"}
                      </span>
                    </td>
                    <td>{a.reason || "—"}</td>
                    <td>{a.ip_address || "—"}</td>
                    <td style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {a.user_agent || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 14 }}>
            <button type="button" className="btn btn-outline dark" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </button>
            <span>Page {result.page} of {result.pages} ({result.total} total)</span>
            <button type="button" className="btn btn-outline dark" disabled={page >= result.pages} onClick={() => setPage((p) => p + 1)}>
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}
