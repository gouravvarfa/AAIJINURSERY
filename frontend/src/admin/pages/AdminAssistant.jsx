import { useEffect, useRef, useState } from "react";
import { api } from "../../api";

const SUGGESTED_QUESTIONS = [
  "Pending orders",
  "Low stock plants",
  "Pending deliveries",
  "Recent customers",
  "Latest inquiries",
  "Product categories",
];

// Restricted operations chatbot for the Admin Panel. Calls the dedicated
// POST /api/admin/assistant/chat route (app/ai/admin_assistant_gateway.py),
// separate from Ask AAIJI. What it can see is decided entirely on the
// backend (developer ON/OFF switch + tool whitelist + per-module RBAC); this
// page only reflects that. The conversation lives in this page's state and
// is never stored server-side.
export default function AdminAssistant() {
  const [enabled, setEnabled] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [lastFailedText, setLastFailedText] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    api.get("/admin/assistant/status").then((s) => setEnabled(Boolean(s.enabled))).catch(() => setEnabled(false));
  }, []);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, sending]);

  async function sendText(text) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    setInput("");
    setError("");
    setLastFailedText(null);
    const history = messages.filter((m) => m.provider !== "none" && m.provider !== "policy").map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setSending(true);
    try {
      const data = await api.post("/admin/assistant/chat", { message: trimmed, history });
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply || "No answer was returned. Please try again.", provider: data.provider }]);
    } catch (err) {
      setLastFailedText(trimmed);
      setMessages((prev) => prev.slice(0, -1));
      if (err.status === 403) {
        setEnabled(false);
        setError(err.message || "The Admin Assistant is currently switched off.");
      } else if (err.status === 429) {
        setError("Too many messages -- please wait a few minutes and try again.");
      } else if (err.status === 401) {
        setError("Your session has expired. Please log in again.");
      } else {
        setError("The assistant is temporarily unavailable. Please try again.");
      }
    } finally {
      setSending(false);
    }
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

  if (enabled === false) {
    return (
      <div className="ask-aaiji-page">
        <div className="admin-page-head">
          <h1>Admin Assistant</h1>
        </div>
        <div className="alert alert-error">The Admin Assistant is currently switched off by the developer.</div>
      </div>
    );
  }

  return (
    <div className="ask-aaiji-page">
      <div className="admin-page-head">
        <div>
          <h1>🤖 Admin Assistant</h1>
          <p style={{ color: "var(--color-text-muted)", margin: "4px 0 0", fontSize: "0.88rem" }}>
            Orders, customers, stock, deliveries and website content
          </p>
        </div>
        {messages.length > 0 && (
          <button type="button" className="btn btn-sm btn-outline dark" onClick={clearConversation}>
            Clear conversation
          </button>
        )}
      </div>

      <div className="ask-aaiji-panel">
        <div className="ask-aaiji-body" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="ask-aaiji-empty">
              <div className="ask-aaiji-empty-icon">🤖</div>
              <strong>Ask me about day-to-day operations</strong>
              <p>Orders, customers, plants and stock, deliveries -- in English or Hinglish. Business-wide reports are not available here.</p>
              <div className="ask-aaiji-suggestions">
                {SUGGESTED_QUESTIONS.map((q) => (
                  <button key={q} type="button" className="ai-chat-chip" onClick={() => sendText(q)} disabled={enabled === null}>
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
            <div className="ai-chat-msg ask-aaiji-msg ai-chat-msg-assistant" aria-label="Admin Assistant is thinking">
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

        <form
          className="ai-chat-input-row ask-aaiji-input-row"
          onSubmit={(e) => {
            e.preventDefault();
            sendText(input);
          }}
        >
          <textarea
            rows={1}
            placeholder="Ask about orders, stock, customers..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={sending || enabled === null}
            aria-label="Admin Assistant"
            maxLength={1000}
          />
          <button type="submit" className="ai-chat-send-btn" disabled={sending || enabled === null || !input.trim()} aria-label="Send">
            ➤
          </button>
        </form>
      </div>
    </div>
  );
}
