import { Fragment, useEffect, useState } from "react";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import SearchBox from "../../accounting/SearchBox";
import { formatIst } from "../../communications/time";

const STATUS_BADGE = {
  SENT: "badge-accent", DELIVERED: "badge-accent", READ: "badge-accent",
  QUEUED: "badge-gold", PROCESSING: "badge-gold",
  FAILED: "badge-danger", CANCELLED: "badge-muted",
};

const STATUSES = ["QUEUED", "PROCESSING", "SENT", "DELIVERED", "READ", "FAILED", "CANCELLED"];
const MODULES = ["orders", "accounting", "delivery", "website", "manual", "test", "campaign"];

export default function MessageHistory() {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [sourceModule, setSourceModule] = useState("");
  const [recipientType, setRecipientType] = useState("");
  const [retrying, setRetrying] = useState(null);
  const [expanded, setExpanded] = useState(null);

  function load() {
    setData(null);
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (status) params.set("status", status);
    if (sourceModule) params.set("source_module", sourceModule);
    if (recipientType) params.set("recipient_type", recipientType);
    params.set("limit", "100");
    api.get(`/admin/communications/messages?${params.toString()}`).then(setData);
  }

  useEffect(load, [q, status, sourceModule, recipientType]);

  async function handleRetry(id) {
    setRetrying(id);
    try {
      await api.post(`/admin/communications/messages/${id}/retry`, {});
      load();
    } catch (err) {
      alert(err.message || "Retry failed.");
    } finally {
      setRetrying(null);
    }
  }

  return (
    <div>
      <div className="admin-page-head">
        <h1>Message History</h1>
      </div>

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16, alignItems: "center" }}>
        <SearchBox value={q} onChange={setQ} placeholder="Customer, mobile or source ID..." />
        <select className="form-control" style={{ maxWidth: 180 }} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="form-control" style={{ maxWidth: 180 }} value={sourceModule} onChange={(e) => setSourceModule(e.target.value)}>
          <option value="">All modules</option>
          {MODULES.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <select className="form-control" style={{ maxWidth: 160 }} value={recipientType} onChange={(e) => setRecipientType(e.target.value)}>
          <option value="">Customer + Driver</option>
          <option value="CUSTOMER">Customer only</option>
          <option value="DRIVER">Driver only</option>
        </select>
      </div>

      {!data ? (
        <Loading />
      ) : data.items.length === 0 ? (
        <Empty>No messages match these filters.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Date/Time</th>
                <th>Recipient</th>
                <th>Mobile</th>
                <th>Module</th>
                <th>Event</th>
                <th>Template</th>
                <th>Type</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((m) => (
                <Fragment key={m.id}>
                  <tr>
                    <td>{formatIst(m.created_at)}</td>
                    <td>
                      {m.recipient_type === "DRIVER" ? "🚚 " : "👤 "}
                      {m.customer_name || "-"}
                    </td>
                    <td>{m.mobile}</td>
                    <td>{m.source_module}</td>
                    <td>{m.event_type}</td>
                    <td>{m.template_name || "-"}</td>
                    <td>{m.message_type === "document" ? `📄 ${m.document_name || "PDF"}` : "Text"}</td>
                    <td><span className={`badge ${STATUS_BADGE[m.status] || "badge-muted"}`}>{m.status}</span></td>
                    <td>
                      <div className="row-actions">
                        <button className="btn btn-sm btn-outline dark" onClick={() => setExpanded(expanded === m.id ? null : m.id)}>
                          {expanded === m.id ? "Hide" : "View"}
                        </button>
                        {m.status === "FAILED" && (
                          <button className="btn btn-sm btn-outline dark" disabled={retrying === m.id} onClick={() => handleRetry(m.id)}>
                            {retrying === m.id ? "Retrying..." : "Retry"}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                  {expanded === m.id && (
                    <tr>
                      <td colSpan={9} style={{ background: "var(--color-bg-soft, #f6f7f5)" }}>
                        <div style={{ padding: 8, fontSize: "0.85rem", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                          <div><strong>Source ID:</strong> {m.source_id}</div>
                          <div><strong>Provider Message ID:</strong> {m.provider_message_id || "-"}</div>
                          <div><strong>Params:</strong> {m.template_params.join(", ")}</div>
                          <div><strong>Retry Count:</strong> {m.retry_count}</div>
                          <div><strong>Sent At:</strong> {formatIst(m.sent_at)}</div>
                          <div><strong>Failed At:</strong> {formatIst(m.failed_at)}</div>
                          {m.error_code && (
                            <div style={{ gridColumn: "1 / -1" }}>
                              <strong>Error:</strong> {m.error_code} -- {m.error_message}
                            </div>
                          )}
                        </div>
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
