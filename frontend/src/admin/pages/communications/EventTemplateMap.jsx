import { useEffect, useState } from "react";
import { api } from "../../../api";
import { Loading } from "../../../components/Loading";
import { formatIst } from "../../communications/time";

const STATUS_BADGE = { ACTIVE: "badge-accent", PENDING: "badge-gold", REJECTED: "badge-danger", DISABLED: "badge-muted", NOT_CONFIGURED: "badge-muted" };

// The required "Event | Template | Status | Last Error | Last Updated" admin
// table -- lets an admin enable/disable a mapping or point an event at a
// different template, but can NEVER make the system bypass the template's
// own ACTIVE-status safety gate (enforced centrally in queue_message()).
export default function EventTemplateMap() {
  const [rows, setRows] = useState(null);
  const [saving, setSaving] = useState(null);

  function load() {
    setRows(null);
    api.get("/admin/communications/event-map").then(setRows);
  }

  useEffect(load, []);

  async function toggleEnabled(row) {
    setSaving(row.event_type);
    try {
      await api.put(`/admin/communications/event-map/${row.event_type}`, { enabled: !row.enabled });
      load();
    } finally {
      setSaving(null);
    }
  }

  async function changeTemplate(row, templateName) {
    setSaving(row.event_type);
    try {
      await api.put(`/admin/communications/event-map/${row.event_type}`, { template_name: templateName });
      load();
    } finally {
      setSaving(null);
    }
  }

  return (
    <div>
      <div className="admin-page-head">
        <h1>Event &rarr; Template Mapping</h1>
      </div>
      <p style={{ color: "var(--color-text-muted)", marginTop: -8, marginBottom: 20, fontSize: "0.88rem" }}>
        Every automatic WhatsApp event is resolved to a template here, centrally -- Orders/Delivery/Accounting never pick a template themselves. Disabling a mapping stops that event from ever being queued. Reassigning the template still requires the new template to be ACTIVE before anything actually sends.
      </p>

      {!rows ? (
        <Loading />
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>Template</th>
                <th>Template Status</th>
                <th>Last Error</th>
                <th>Last Updated</th>
                <th>Mapping</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.event_type}>
                  <td>{r.event_type}</td>
                  <td>
                    <input
                      className="form-control"
                      style={{ maxWidth: 220 }}
                      defaultValue={r.template_name}
                      onBlur={(e) => e.target.value !== r.template_name && changeTemplate(r, e.target.value)}
                    />
                  </td>
                  <td><span className={`badge ${STATUS_BADGE[r.template_status] || "badge-muted"}`}>{r.template_status}</span></td>
                  <td style={{ maxWidth: 260, fontSize: "0.8rem", color: "var(--color-text-muted)" }}>{r.last_error || "-"}</td>
                  <td style={{ fontSize: "0.8rem", color: "var(--color-text-muted)" }}>{formatIst(r.updated_at)}</td>
                  <td>
                    <button
                      className={`btn btn-sm ${r.enabled ? "btn-outline dark" : "btn-primary"}`}
                      disabled={saving === r.event_type}
                      onClick={() => toggleEnabled(r)}
                    >
                      {r.enabled ? "Disable" : "Enable"}
                    </button>
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
