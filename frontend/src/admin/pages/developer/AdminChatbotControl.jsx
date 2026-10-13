import { useEffect, useState } from "react";
import { api } from "../../../api";
import { Loading } from "../../../components/Loading";

function formatWhen(iso) {
  if (!iso) return "never changed";
  return new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" });
}

// Developer-only ON/OFF switch for the Admin Assistant chatbot. The state
// lives in the database, so it is the same after a refresh, on another
// device, and after a server restart.
export default function AdminChatbotControl() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get("/admin/admin-chatbot-control").then(setStatus).catch((err) => setError(err.message || "Could not load the Admin Chatbot status."));
  }, []);

  async function change(enabled) {
    if (!enabled && !window.confirm("Switch the Admin Chatbot OFF? Admins lose access to it immediately.")) return;
    setSaving(true);
    setError("");
    try {
      setStatus(await api.put("/admin/admin-chatbot-control", { enabled }));
    } catch (err) {
      setError(err.message || "Could not change the setting.");
    } finally {
      setSaving(false);
    }
  }

  if (!status && !error) return <Loading />;

  const on = status?.enabled;
  return (
    <div>
      <div className="admin-page-head">
        <h1>Admin Chatbot</h1>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {status && (
        <div className="admin-form-card" style={{ maxWidth: 640 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 16 }}>
            <span
              aria-hidden="true"
              style={{ width: 16, height: 16, borderRadius: "50%", background: on ? "#2e9e5b" : "#c0392b", boxShadow: `0 0 0 5px ${on ? "#2e9e5b33" : "#c0392b33"}` }}
            />
            <div>
              <div style={{ fontSize: "1.4rem", fontWeight: 700, color: on ? "#1f7a45" : "#a52a1d" }}>{on ? "ACTIVE" : "INACTIVE"}</div>
              <div style={{ color: "var(--color-text-muted)" }}>
                {on ? "Admins can open and use the Admin Assistant." : "The Admin Assistant is hidden and blocked for all admins."}
              </div>
            </div>
          </div>

          <button type="button" className={`btn ${on ? "btn-danger" : "btn-primary"}`} disabled={saving} onClick={() => change(!on)}>
            {saving ? "Saving..." : on ? "Switch Admin Chatbot OFF" : "Switch Admin Chatbot ON"}
          </button>

          <p style={{ color: "var(--color-text-muted)", fontSize: "0.88rem", marginTop: 18, marginBottom: 0 }}>
            Last changed by <strong>{status.changed_by || "nobody yet (default OFF)"}</strong> &middot; {formatWhen(status.changed_at)}
          </p>
          <p style={{ color: "var(--color-text-muted)", fontSize: "0.82rem", marginTop: 14, marginBottom: 0 }}>
            Affects only the Admin Assistant. The customer chatbot and Ask AAIJI are not changed by this switch. Enforced on the server for every
            request and tool call; takes effect immediately, no redeploy needed.
          </p>
        </div>
      )}
    </div>
  );
}
