import { useEffect, useRef, useState } from "react";
import { api } from "../../api";

const SUGGESTED_QUESTIONS = [
  "Today's sales",
  "Pending orders",
  "Top selling plants",
  "Low stock plants",
  "Recent customers",
  "Online vs offline sales",
  "Pending deliveries",
];

// Admin-only business-intelligence assistant. Calls the dedicated
// POST /api/admin/ai/chat gateway (app/ai/admin_gateway.py) -- a completely
// separate backend route/rate-limit from the customer-facing AI widget,
// reusing the same Groq/Gemini/OpenRouter provider chain. Every answer is
// scoped by the logged-in admin's real RBAC permissions on the backend,
// never decided here. Conversation lives only in this page's state for the
// current session -- gone on refresh/navigation, never persisted server-side.
export default function AskAaiji() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState(null);
  const [lastFailedText, setLastFailedText] = useState(null);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, sending]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function sendText(text) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    setInput("");
    setError("");
    setLastFailedText(null);
    const history = messages.filter((m) => m.provider !== "none").map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setSending(true);
    try {
      const data = await api.post("/admin/ai/chat", { message: trimmed, history });
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply, provider: data.provider }]);
      setStatus(data.provider !== "none" ? "online" : "offline");
    } catch (err) {
      setLastFailedText(trimmed);
      if (err.status === 429) {
        setError("Too many messages -- please wait a few minutes and try again.");
      } else if (err.status === 401 || err.status === 403) {
        setError("Your session has expired or you don't have access. Please log in again.");
      } else {
        setError("AI service is temporarily unavailable. Please try again.");
        setStatus("offline");
      }
      // Remove the optimistically-added user message so Retry can re-send
      // it cleanly instead of duplicating it.
      setMessages((prev) => prev.slice(0, -1));
    } finally {
      setSending(false);
    }
  }

  function handleSubmit(e) {
    e.preventDefault();
    sendText(input);
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendText(input);
    }
  }

  function clearConversation() {
    if (messages.length > 0 && !confirm("Clear this conversation?")) return;
    setMessages([]);
    setError("");
    setLastFailedText(null);
  }

  return (
    <div className="ask-aaiji-page">
      <div className="admin-page-head">
        <div>
          <h1>🤖 Ask AAIJI</h1>
          <p style={{ color: "var(--color-text-muted)", margin: "4px 0 0", fontSize: "0.88rem" }}>
            Business Intelligence Assistant
          </p>
        </div>
        <div className="ask-aaiji-header-right">
          {status !== null && (
            <span className="ai-chat-header-status" style={{ color: "var(--color-text-muted)" }}>
              <span className={`ai-chat-status-dot${status === "offline" ? " offline" : ""}`} style={{ background: status === "online" ? "var(--color-accent)" : undefined }} />
              {status === "online" ? "Online" : "Temporarily unavailable"}
            </span>
          )}
          {messages.length > 0 && (
            <button type="button" className="btn btn-sm btn-outline dark" onClick={clearConversation}>
              Clear conversation
            </button>
          )}
        </div>
      </div>

      <div className="ask-aaiji-panel">
        <div className="ask-aaiji-body" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="ask-aaiji-empty">
              <div className="ask-aaiji-empty-icon">🤖</div>
              <strong>Ask me anything about your business</strong>
              <p>Sales, orders, customers, inventory, deliveries -- in English or Hinglish.</p>
              <div className="ask-aaiji-suggestions">
                {SUGGESTED_QUESTIONS.map((q) => (
                  <button key={q} type="button" className="ai-chat-chip" onClick={() => sendText(q)}>
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`ai-chat-msg ask-aaiji-msg ai-chat-msg-${m.role}`}>
              {m.content}
            </div>
          ))}
          {sending && (
            <div className="ai-chat-msg ask-aaiji-msg ai-chat-msg-assistant" aria-label="Ask AAIJI is thinking">
              <span className="ai-chat-typing-dots">
                <span />
                <span />
                <span />
              </span>
            </div>
          )}
        </div>

        {error && (
          <div className="ai-chat-error" style={{ display: "flex", alignItems: "center", gap: 10, justifyContent: "space-between" }}>
            <span>{error}</span>
            {lastFailedText && (
              <button type="button" className="btn btn-sm btn-outline dark" onClick={() => sendText(lastFailedText)}>
                Retry
              </button>
            )}
          </div>
        )}

        <form className="ai-chat-input-row ask-aaiji-input-row" onSubmit={handleSubmit}>
          <textarea
            ref={inputRef}
            rows={1}
            placeholder="Ask anything about your business..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={sending}
            aria-label="Ask AAIJI"
          />
          <button type="submit" className="ai-chat-send-btn" disabled={sending || !input.trim()} aria-label="Send">
            ➤
          </button>
        </form>
      </div>
    </div>
  );
}
