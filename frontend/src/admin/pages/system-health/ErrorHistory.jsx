import { Fragment, useEffect, useState } from "react";
import { formatIst, formatIstDate } from "../../communications/time";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import { SeverityBadge, StatusBadge } from "../../system-health/badges";
import ErrorDetailPanel from "../../system-health/ErrorDetailPanel";

const SEVERITIES = ["", "CRITICAL", "HIGH", "MEDIUM", "WARNING", "INFO"];
const STATUSES = ["", "ACTIVE", "INVESTIGATING", "RESOLVED", "IGNORED"];
const EMPTY_FILTERS = { module: "", function: "", severity: "", status: "", q: "", date_from: "", date_to: "" };

export default function SystemHealthErrorHistory() {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState(null);

  function load() {
    setError("");
    setResult(null);
    const params = new URLSearchParams({ page: String(page), limit: "25" });
    Object.entries(filters).forEach(([k, v]) => v && params.set(k, v));
    api
      .getPaged(`/admin/system-health/errors/history?${params}`)
      .then(setResult)
      .catch((err) => setError(err.message));
  }

  useEffect(load, [filters, page]);

  function updateFilter(key, value) {
    setPage(1);
    setFilters((f) => ({ ...f, [key]: value }));
  }

  return (
    <div>
      <div className="admin-page-head">
        <h1>Error History</h1>
      </div>

      <div className="form-row">
        <div className="form-group">
          <label>Search</label>
          <input className="form-control" value={filters.q} onChange={(e) => updateFilter("q", e.target.value)} placeholder="Message contains..." />
        </div>
        <div className="form-group">
          <label>Module</label>
          <input className="form-control" value={filters.module} onChange={(e) => updateFilter("module", e.target.value)} />
        </div>
        <div className="form-group">
          <label>Function</label>
          <input className="form-control" value={filters.function} onChange={(e) => updateFilter("function", e.target.value)} />
        </div>
      </div>
      <div className="form-row">
        <div className="form-group">
          <label>Severity</label>
          <select className="form-control" value={filters.severity} onChange={(e) => updateFilter("severity", e.target.value)}>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>{s || "All"}</option>
            ))}
          </select>
        </div>
        <div className="form-group">
          <label>Status</label>
          <select className="form-control" value={filters.status} onChange={(e) => updateFilter("status", e.target.value)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{s || "All"}</option>
            ))}
          </select>
        </div>
        <div className="form-group">
          <label>From</label>
          <input type="date" className="form-control" value={filters.date_from} onChange={(e) => updateFilter("date_from", e.target.value)} />
        </div>
        <div className="form-group">
          <label>To</label>
          <input type="date" className="form-control" value={filters.date_to} onChange={(e) => updateFilter("date_to", e.target.value)} />
        </div>
        <div className="form-group" style={{ alignSelf: "flex-end" }}>
          <button type="button" className="btn btn-outline dark" onClick={() => { setPage(1); setFilters(EMPTY_FILTERS); }}>
            Clear Filters
          </button>
        </div>
      </div>

      {error ? (
        <div className="alert alert-error">
          Could not load error history. <button className="btn btn-outline dark" onClick={load}>Retry</button>
        </div>
      ) : !result ? (
        <Loading />
      ) : result.items.length === 0 ? (
        <Empty>No errors match these filters.</Empty>
      ) : (
        <>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Module</th>
                  <th>Function</th>
                  <th>Message</th>
                  <th>Occurrences</th>
                  <th>First Seen</th>
                  <th>Last Seen</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((item) => (
                  <Fragment key={item.id}>
                    <tr>
                      <td><SeverityBadge severity={item.severity} /></td>
                      <td>{item.module}{item.sub_module ? ` / ${item.sub_module}` : ""}</td>
                      <td>{item.function}</td>
                      <td style={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {item.message}
                      </td>
                      <td>{item.occurrence_count}</td>
                      <td>{formatIstDate(item.first_seen)}</td>
                      <td>{formatIst(item.last_seen)}</td>
                      <td><StatusBadge status={item.status} /></td>
                      <td>
                        <button type="button" className="btn btn-outline dark" onClick={() => setExpandedId(expandedId === item.id ? null : item.id)}>
                          {expandedId === item.id ? "Hide" : "View"}
                        </button>
                      </td>
                    </tr>
                    {expandedId === item.id && (
                      <tr>
                        <td colSpan={9}>
                          <ErrorDetailPanel errorId={item.id} onStatusChanged={load} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
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
