import { useEffect, useState } from "react";
import { formatIst } from "../communications/time";
import { api } from "../../api";
import { Loading } from "../../components/Loading";
import { SeverityBadge, StatusBadge } from "./badges";

const STATUS_OPTIONS = ["ACTIVE", "INVESTIGATING", "RESOLVED", "IGNORED"];

// Full error record: identity fields inline, "Technical Details" (stack
// trace / request metadata) behind a native <details> element -- no new UI
// framework needed for the expandable-section requirement.
export default function ErrorDetailPanel({ errorId, onStatusChanged }) {
  const [data, setData] = useState(null);
  const [savingStatus, setSavingStatus] = useState(false);

  useEffect(() => {
    setData(null);
    api.get(`/admin/system-health/errors/${errorId}`).then(setData);
  }, [errorId]);

  async function changeStatus(status) {
    setSavingStatus(true);
    try {
      const updated = await api.post(`/admin/system-health/errors/${errorId}/status`, { status });
      setData((prev) => ({ ...prev, ...updated }));
      onStatusChanged?.(updated);
    } catch {
      // best-effort -- the panel just keeps showing the last-known state
    } finally {
      setSavingStatus(false);
    }
  }

  if (!data) return <Loading />;

  return (
    <div className="admin-form-card" style={{ marginTop: 12 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
        <SeverityBadge severity={data.severity} />
        <StatusBadge status={data.status} />
        <strong>{data.module}{data.sub_module ? ` → ${data.sub_module}` : ""}</strong>
      </div>

      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "160px 1fr",
          rowGap: 8,
          columnGap: 12,
          margin: 0,
        }}
      >
        <dt>Error ID</dt>
        <dd>{data.id}</dd>
        <dt>Request ID</dt>
        <dd>{data.last_request_id || "-"}</dd>
        <dt>Function</dt>
        <dd>{data.function}</dd>
        <dt>Endpoint</dt>
        <dd>{data.method} {data.endpoint}</dd>
        <dt>Error Code</dt>
        <dd>{data.error_code}</dd>
        <dt>Message</dt>
        <dd>{data.message}</dd>
        <dt>First Seen</dt>
        <dd>{data.first_seen ? formatIst(data.first_seen) : "-"}</dd>
        <dt>Last Seen</dt>
        <dd>{data.last_seen ? formatIst(data.last_seen) : "-"}</dd>
        <dt>Occurrences</dt>
        <dd>{data.occurrence_count}</dd>
        {data.status === "RESOLVED" && (
          <>
            <dt>Resolved By</dt>
            <dd>{data.resolved_by} {data.resolved_at ? `on ${formatIst(data.resolved_at)}` : ""}</dd>
          </>
        )}
      </dl>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "14px 0" }}>
        {STATUS_OPTIONS.filter((s) => s !== data.status).map((s) => (
          <button
            key={s}
            type="button"
            className="btn btn-outline dark"
            disabled={savingStatus}
            onClick={() => changeStatus(s)}
          >
            Mark {s}
          </button>
        ))}
      </div>

      <details>
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>Technical Details</summary>
        <div style={{ marginTop: 10 }}>
          <p style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
            Request metadata: {JSON.stringify(data.request_metadata || {})}
          </p>
          <pre
            style={{
              background: "var(--color-bg)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-sm)",
              padding: 12,
              maxHeight: 320,
              overflow: "auto",
              fontSize: "0.8rem",
              whiteSpace: "pre-wrap",
            }}
          >
            {data.technical_details || "No stack trace captured for this error."}
          </pre>
          {data.recent_occurrences?.length > 0 && (
            <>
              <p style={{ fontWeight: 600, marginTop: 10 }}>Recent Occurrences</p>
              <ul>
                {data.recent_occurrences.map((occ, idx) => (
                  <li key={idx}>
                    {occ.request_id || "(no request id)"} &mdash; {formatIst(occ.at)}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </details>
    </div>
  );
}
