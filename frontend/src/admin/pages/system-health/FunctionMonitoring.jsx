import { useEffect, useState } from "react";
import { formatIst } from "../../communications/time";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";

export default function SystemHealthFunctionMonitoring() {
  const [module, setModule] = useState("");
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");

  function load() {
    setError("");
    setItems(null);
    const params = module ? `?module=${encodeURIComponent(module)}` : "";
    api.get(`/admin/system-health/functions${params}`).then(setItems).catch((err) => setError(err.message));
  }

  useEffect(load, [module]);

  return (
    <div>
      <div className="admin-page-head">
        <h1>Function Monitoring</h1>
      </div>

      <div className="form-group" style={{ maxWidth: 260, marginBottom: 16 }}>
        <label>Module</label>
        <input className="form-control" placeholder="e.g. Accounting" value={module} onChange={(e) => setModule(e.target.value)} />
      </div>

      {error ? (
        <div className="alert alert-error">
          Could not load function stats. <button className="btn btn-outline dark" onClick={load}>Retry</button>
        </div>
      ) : !items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>No request data collected yet for this filter.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Module</th>
                <th>Function</th>
                <th>Endpoint</th>
                <th>Success</th>
                <th>Failure</th>
                <th>Failure Rate</th>
                <th>Avg Response</th>
                <th>Last Failure</th>
                <th>Last Success</th>
              </tr>
            </thead>
            <tbody>
              {items.map((f, idx) => (
                <tr key={idx}>
                  <td>{f.module}{f.sub_module ? ` / ${f.sub_module}` : ""}</td>
                  <td>{f.function}</td>
                  <td>{f.method} {f.endpoint}</td>
                  <td>{f.success_count}</td>
                  <td>{f.failure_count}</td>
                  <td>{(f.failure_rate * 100).toFixed(1)}%</td>
                  <td>{f.avg_response_ms != null ? `${f.avg_response_ms} ms` : "-"}</td>
                  <td>{f.last_failure_at ? formatIst(f.last_failure_at) : "-"}</td>
                  <td>{f.last_success_at ? formatIst(f.last_success_at) : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
