import { useEffect, useState } from "react";
import { api } from "../../../api";
import { Loading } from "../../../components/Loading";

function formatWhen(iso) {
  if (!iso) return "never changed";
  return new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" });
}

// Developer-only global switch for every outgoing WhatsApp message. The
// state lives on the server, so it is the same after a refresh, on another
// device, and after a restart.
export default function MessagingControl() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  function load() {
    api.get("/admin/messaging-control").then(setStatus).catch((err) => setError(err.message || "Could not load the messaging status."));
  }

  useEffect(load, []);
  // While OFF, keep the "stopped" counter live.
  useEffect(() => {
    if (!status || status.enabled) return undefined;
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [status]);

  async function change(enabled) {
    if (!enabled && !window.confirm("Switch messaging OFF? Every WhatsApp message (order updates, delivery alerts, manual sends, inbox replies) stops immediately.")) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      setStatus(await api.put("/admin/messaging-control", { enabled }));
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
        <h1>Messaging</h1>
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
                {on ? "WhatsApp messages are sending normally." : "All outgoing WhatsApp messages are stopped."}
              </div>
            </div>
          </div>

          <button
            type="button"
            className={`btn ${on ? "btn-danger" : "btn-primary"}`}
            disabled={saving}
            onClick={() => change(!on)}
          >
            {saving ? "Saving..." : on ? "Switch messaging OFF" : "Switch messaging ON"}
          </button>

          <p style={{ color: "var(--color-text-muted)", fontSize: "0.88rem", marginTop: 18, marginBottom: 0 }}>
            Last changed by <strong>{status.changed_by || "nobody yet (default ON)"}</strong> &middot; {formatWhen(status.changed_at)}
          </p>
          {!on && (
            <p style={{ marginTop: 10, marginBottom: 0 }}>
              Stopped since it was switched off: <strong>{status.blocked_while_off}</strong> message(s). Nothing is queued while OFF, so
              nothing goes out by surprise when you switch it back on. Messages already waiting in the queue are marked Failed
              ("Messaging is switched off") and can be retried from Message History.
            </p>
          )}
          <p style={{ color: "var(--color-text-muted)", fontSize: "0.82rem", marginTop: 14, marginBottom: 0 }}>
            Applies to every module &mdash; orders, accounting, delivery, website, manual sends, test sends, documents and Inbox replies.
            Takes effect on the very next message; no redeploy needed.
          </p>
        </div>
      )}
    </div>
  );
}
