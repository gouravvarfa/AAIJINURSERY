import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import SearchBox from "../../accounting/SearchBox";

const POLL_MS = 10000;
const TICKS = { SENT: "✓", DELIVERED: "✓✓", READ: "✓✓", FAILED: "!" };

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(`${iso}Z`); // backend stores naive UTC
  const today = new Date();
  return d.toDateString() === today.toDateString()
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString([], { day: "numeric", month: "short" });
}

export default function Inbox() {
  const [convos, setConvos] = useState(null);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(null); // mobile
  const [thread, setThread] = useState(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef(null);

  const loadConvos = useCallback(() => {
    api.get(`/admin/communications/inbox/conversations?q=${encodeURIComponent(q)}`).then(setConvos).catch(() => {});
  }, [q]);

  const loadThread = useCallback((mobile) => {
    if (!mobile) return;
    api.get(`/admin/communications/inbox/messages?mobile=${encodeURIComponent(mobile)}`).then(setThread).catch(() => {});
  }, []);

  useEffect(() => {
    loadConvos();
    const t = setInterval(loadConvos, POLL_MS);
    return () => clearInterval(t);
  }, [loadConvos]);

  useEffect(() => {
    if (!active) return undefined;
    setThread(null);
    setError("");
    loadThread(active);
    api.post("/admin/communications/inbox/read", { mobile: active }).then(loadConvos).catch(() => {});
    const t = setInterval(() => loadThread(active), POLL_MS);
    return () => clearInterval(t);
  }, [active, loadThread, loadConvos]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [thread?.items?.length]);

  async function send(e) {
    e.preventDefault();
    const body = text.trim();
    if (!body || sending) return;
    setSending(true);
    setError("");
    try {
      await api.post("/admin/communications/inbox/reply", { mobile: active, text: body });
      setText("");
      loadThread(active);
      loadConvos();
    } catch (err) {
      setError(err.message || "Could not send the reply.");
    } finally {
      setSending(false);
    }
  }

  const activeConvo = convos?.items.find((c) => c.mobile === active);

  return (
    <div>
      <div className="admin-page-head">
        <h1>Inbox{convos?.total_unread ? ` (${convos.total_unread} unread)` : ""}</h1>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(240px, 340px) 1fr", gap: 16, alignItems: "start" }}>
        <div className="admin-table-wrap" style={{ maxHeight: "70vh", overflowY: "auto" }}>
          <div style={{ padding: 8 }}>
            <SearchBox value={q} onChange={setQ} placeholder="Name, mobile or message..." />
          </div>
          {!convos ? (
            <Loading />
          ) : convos.items.length === 0 ? (
            <Empty>No customer replies yet.</Empty>
          ) : (
            convos.items.map((c) => (
              <button
                key={c.mobile}
                type="button"
                onClick={() => setActive(c.mobile)}
                style={{
                  display: "block", width: "100%", textAlign: "left", padding: "10px 12px", cursor: "pointer",
                  border: 0, borderBottom: "1px solid rgba(0,0,0,0.08)", font: "inherit", color: "inherit",
                  background: c.mobile === active ? "var(--color-bg-soft, #f6f7f5)" : "transparent",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <strong>{c.name || c.mobile}</strong>
                  <span style={{ fontSize: "0.75rem", opacity: 0.7 }}>{fmtTime(c.last_at)}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: "0.85rem", opacity: 0.8 }}>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {c.last_direction === "OUT" ? "You: " : ""}{c.last_message}
                  </span>
                  {c.unread > 0 && <span className="badge badge-accent">{c.unread}</span>}
                </div>
              </button>
            ))
          )}
        </div>

        <div className="admin-table-wrap" style={{ display: "flex", flexDirection: "column", minHeight: 360, maxHeight: "70vh" }}>
          {!active ? (
            <Empty>Select a conversation.</Empty>
          ) : (
            <>
              <div style={{ padding: "10px 12px", borderBottom: "1px solid rgba(0,0,0,0.08)" }}>
                <strong>{activeConvo?.name || active}</strong>
                {activeConvo?.name && <span style={{ marginLeft: 8, opacity: 0.7 }}>{active}</span>}
              </div>

              <div style={{ flex: 1, overflowY: "auto", padding: 12, display: "flex", flexDirection: "column", gap: 8 }}>
                {!thread ? (
                  <Loading />
                ) : (
                  thread.items.map((m) => (
                    <div
                      key={m.id}
                      style={{
                        alignSelf: m.direction === "OUT" ? "flex-end" : "flex-start", maxWidth: "75%",
                        padding: "8px 10px", borderRadius: 10, whiteSpace: "pre-wrap", wordBreak: "break-word",
                        background: m.direction === "OUT" ? "var(--color-accent-soft, #dcf3e1)" : "var(--color-bg-soft, #f1f2f0)",
                      }}
                    >
                      <div>{m.body || `[${m.message_type}]`}</div>
                      <div style={{ fontSize: "0.7rem", opacity: 0.7, textAlign: "right", marginTop: 2 }}>
                        {fmtTime(m.created_at)}
                        {m.direction === "OUT" && (
                          <span style={{ marginLeft: 4, color: m.status === "READ" ? "#2a7de1" : m.status === "FAILED" ? "#c0392b" : "inherit" }}>
                            {TICKS[m.status] || ""}
                          </span>
                        )}
                      </div>
                      {m.status === "FAILED" && m.error_message && (
                        <div style={{ fontSize: "0.7rem", color: "#c0392b" }}>{m.error_message}</div>
                      )}
                    </div>
                  ))
                )}
                <div ref={bottomRef} />
              </div>

              <form onSubmit={send} style={{ padding: 12, borderTop: "1px solid rgba(0,0,0,0.08)" }}>
                {thread && !thread.window_open ? (
                  <div style={{ fontSize: "0.85rem", opacity: 0.8 }}>
                    The 24-hour reply window has closed. You can reply again once the customer messages first, or send an approved template from Send Message.
                  </div>
                ) : (
                  <>
                    {error && <div style={{ color: "#c0392b", fontSize: "0.85rem", marginBottom: 6 }}>{error}</div>}
                    <div style={{ display: "flex", gap: 8 }}>
                      <textarea
                        className="form-control"
                        rows={2}
                        style={{ flex: 1 }}
                        value={text}
                        maxLength={4000}
                        placeholder="Type a reply..."
                        onChange={(e) => setText(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) send(e); }}
                      />
                      <button className="btn btn-primary" type="submit" disabled={sending || !text.trim()}>
                        {sending ? "Sending..." : "Send"}
                      </button>
                    </div>
                  </>
                )}
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
