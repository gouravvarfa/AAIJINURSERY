import { useEffect, useState } from "react";
import { formatIst } from "../../communications/time";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import { LogLevelBadge } from "../../system-health/badges";

const LEVELS = ["", "WARNING", "ERROR", "CRITICAL"];

export default function SystemHealthSystemLogs() {
  const [level, setLevel] = useState("");
  const [module, setModule] = useState("");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [settings, setSettings] = useState(null);
  const [retentionInput, setRetentionInput] = useState("");
  const [savingRetention, setSavingRetention] = useState(false);

  function load() {
    setError("");
    setResult(null);
    const params = new URLSearchParams({ page: String(page), limit: "50" });
    if (level) params.set("level", level);
    if (module) params.set("module", module);
    api.getPaged(`/admin/system-health/logs?${params}`).then(setResult).catch((err) => setError(err.message));
  }

  useEffect(load, [level, module, page]);

  useEffect(() => {
    api.get("/admin/system-health/settings").then((s) => {
      setSettings(s);
      setRetentionInput(String(s.retention_days));
    });
  }, []);

  async function saveRetention(e) {
    e.preventDefault();
    setSavingRetention(true);
    try {
      const updated = await api.put("/admin/system-health/settings", { retention_days: Number(retentionInput) });
      setSettings(updated);
    } catch {
      // best-effort
    } finally {
      setSavingRetention(false);
    }
  }

  return (
    <div>
      <div className="admin-page-head">
        <h1>System Logs</h1>
      </div>

      {settings && (
        <div className="admin-form-card" style={{ marginBottom: 20 }}>
          <p style={{ marginTop: 0, color: "var(--color-text-muted)", fontSize: "0.88rem" }}>{settings.note}</p>
          <form onSubmit={saveRetention} style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label>Log Retention (days)</label>
              <input
                type="number"
                min="1"
                max="365"
                className="form-control"
                value={retentionInput}
                onChange={(e) => setRetentionInput(e.target.value)}
              />
            </div>
            <button type="submit" className="btn btn-primary" disabled={savingRetention}>
              Save
            </button>
          </form>
        </div>
      )}

      <div className="form-row">
        <div className="form-group">
          <label>Level</label>
          <select className="form-control" value={level} onChange={(e) => { setPage(1); setLevel(e.target.value); }}>
            {LEVELS.map((l) => (
              <option key={l} value={l}>{l || "All"}</option>
            ))}
          </select>
        </div>
        <div className="form-group">
          <label>Module</label>
          <input className="form-control" value={module} onChange={(e) => { setPage(1); setModule(e.target.value); }} />
        </div>
      </div>

      {error ? (
        <div className="alert alert-error">
          Could not load system logs. <button className="btn btn-outline dark" onClick={load}>Retry</button>
        </div>
      ) : !result ? (
        <Loading />
      ) : result.items.length === 0 ? (
        <Empty>No logs match these filters.</Empty>
      ) : (
        <>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Level</th>
                  <th>Module</th>
                  <th>Endpoint</th>
                  <th>Status</th>
                  <th>Time</th>
                  <th>Message</th>
                  <th>Request ID</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((l) => (
                  <tr key={l.id}>
                    <td>{formatIst(l.created_at)}</td>
                    <td><LogLevelBadge level={l.level} /></td>
                    <td>{l.module || "-"}</td>
                    <td>{l.method ? `${l.method} ${l.endpoint}` : "-"}</td>
                    <td>{l.status_code ?? "-"}</td>
                    <td>{l.execution_ms != null ? `${Math.round(l.execution_ms)} ms` : "-"}</td>
                    <td style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.message}</td>
                    <td>{l.request_id || "-"}</td>
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
