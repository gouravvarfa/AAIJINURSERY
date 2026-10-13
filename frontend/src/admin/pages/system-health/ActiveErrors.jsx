import { Fragment, useEffect, useState } from "react";
import { formatIst } from "../../communications/time";
import { useSearchParams } from "react-router-dom";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import { SeverityBadge, StatusBadge } from "../../system-health/badges";
import ErrorDetailPanel from "../../system-health/ErrorDetailPanel";

const SEVERITIES = ["", "CRITICAL", "HIGH", "MEDIUM", "WARNING", "INFO"];

export default function SystemHealthActiveErrors() {
  const [searchParams, setSearchParams] = useSearchParams();
  const module = searchParams.get("module") || "";
  const severity = searchParams.get("severity") || "";

  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState(null);

  function load() {
    setError("");
    setItems(null);
    const params = new URLSearchParams();
    if (module) params.set("module", module);
    if (severity) params.set("severity", severity);
    api
      .get(`/admin/system-health/errors/active${params.toString() ? `?${params}` : ""}`)
      .then(setItems)
      .catch((err) => setError(err.message));
  }

  useEffect(load, [module, severity]);

  return (
    <div>
      <div className="admin-page-head">
        <h1>Active Errors</h1>
      </div>

      <div className="form-row" style={{ marginBottom: 16 }}>
        <div className="form-group">
          <label>Module</label>
          <input
            className="form-control"
            placeholder="e.g. Accounting"
            value={module}
            onChange={(e) => setSearchParams((p) => ({ ...Object.fromEntries(p), module: e.target.value }))}
          />
        </div>
        <div className="form-group">
          <label>Severity</label>
          <select
            className="form-control"
            value={severity}
            onChange={(e) => setSearchParams((p) => ({ ...Object.fromEntries(p), severity: e.target.value }))}
          >
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s || "All"}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error ? (
        <div className="alert alert-error">
          Could not load active errors. <button className="btn btn-outline dark" onClick={load}>Retry</button>
        </div>
      ) : !items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>No active errors right now.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Severity</th>
                <th>Module</th>
                <th>Function</th>
                <th>Message</th>
                <th>Occurrences</th>
                <th>Last Seen</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <Fragment key={item.id}>
                  <tr>
                    <td><SeverityBadge severity={item.severity} /></td>
                    <td>{item.module}{item.sub_module ? ` / ${item.sub_module}` : ""}</td>
                    <td>{item.function}</td>
                    <td style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {item.message}
                    </td>
                    <td>{item.occurrence_count}</td>
                    <td>{formatIst(item.last_seen)}</td>
                    <td><StatusBadge status={item.status} /></td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-outline dark"
                        onClick={() => setExpandedId(expandedId === item.id ? null : item.id)}
                      >
                        {expandedId === item.id ? "Hide" : "View Details"}
                      </button>
                    </td>
                  </tr>
                  {expandedId === item.id && (
                    <tr>
                      <td colSpan={8}>
                        <ErrorDetailPanel errorId={item.id} onStatusChanged={load} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
