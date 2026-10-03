import { useEffect, useRef, useState } from "react";
import { api } from "../api";

const QUICK_ACTIONS = [
  { icon: "🌱", label: "Find a Plant", text: "Help me find a plant" },
  { icon: "📦", label: "Check Stock", text: "Is this plant in stock?" },
  { icon: "🚚", label: "Delivery Info", text: "What are your delivery charges and timelines?" },
  { icon: "📋", label: "Track Order", text: "What's the status of my order?" },
];

const SUGGESTION_CHIPS = [
  "Which plants are available?",
  "Do you deliver to my area?",
  "Track my order",
];

function LeafIcon({ size = 20 }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M11 20A7 7 0 0 1 4 13c0-4 3-8 10-10 1 6-1 10-3 13" />
      <path d="M11 20c2-1 4-3 5-6" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m5 12 14-7-7 14-2-5-5-2z" />
    </svg>
  );
}

// Customer-facing AI assistant widget -- calls the existing POST /api/ai/chat
// gateway (Groq/Gemini/OpenRouter chain, tool-calling, rate limiting all
// unchanged, see app/ai/gateway.py). History lives only in this component's
// state (gone on refresh), never persisted server-side. Bottom-right,
// stacked directly above the existing WhatsApp button -- see the
// --ai-fab-bottom custom property in index.css, computed from WhatsApp's
// own position so the two can never collide.
export default function AIChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState(null); // null = unknown yet, "online" | "offline" once a real response has come back
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const panelRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, open, sending]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function handleKey(e) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);

  async function sendText(text) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;
    setInput("");
    setError("");
    // Excludes any earlier "AI not available"/error fallback reply (provider
    // "none") from what gets sent back as context -- otherwise a stale
    // outage message keeps steering every later answer in the same
    // conversation, even after the provider is working again.
    const history = messages.filter((m) => m.provider !== "none").map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setSending(true);
    try {
      const data = await api.post("/ai/chat", { message: trimmed, history });
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply, provider: data.provider }]);
      setStatus(data.provider !== "none" ? "online" : "offline");
    } catch (err) {
      setError(err.status === 429 ? "Too many messages -- please wait a bit." : "Something went wrong. Please try again.");
      setStatus("offline");
    } finally {
      setSending(false);
    }
  }

  function handleSubmit(e) {
    e.preventDefault();
    sendText(input);
  }

  return (
    <>
      {open && (
        <div className="ai-chat-panel" ref={panelRef} role="dialog" aria-label="AAIJI Assistant chat">
          <div className="ai-chat-header">
            <div className="ai-chat-header-avatar" aria-hidden="true">
              <LeafIcon size={20} />
            </div>
            <div className="ai-chat-header-info">
              <div className="ai-chat-header-title">AAIJI Assistant</div>
              {status === null ? (
                <div className="ai-chat-header-subtitle">Plant, stock, delivery &amp; order help</div>
              ) : (
                <div className="ai-chat-header-status">
                  <span className={`ai-chat-status-dot${status === "offline" ? " offline" : ""}`} />
                  {status === "online" ? "Online" : "Temporarily unavailable"}
                </div>
              )}
            </div>
            <div className="ai-chat-header-actions">
              <button type="button" onClick={() => setOpen(false)} aria-label="Minimize AAIJI Assistant" title="Minimize">
                &minus;
              </button>
              <button type="button" onClick={() => setOpen(false)} aria-label="Close AAIJI Assistant" title="Close">
                &times;
              </button>
            </div>
          </div>

          <div className="ai-chat-body" ref={scrollRef}>
            {messages.length === 0 && (
              <>
                <div className="ai-chat-welcome">
                  <div className="ai-chat-welcome-avatar" aria-hidden="true">
                    👋
                  </div>
                  <div className="ai-chat-welcome-bubble">
                    <strong>Hello! I'm the AAIJI Assistant.</strong>
                    I can help you with plants, availability, prices, delivery and order status.
                  </div>
                </div>
                <div className="ai-chat-quick-actions">
                  {QUICK_ACTIONS.map((a) => (
                    <button key={a.label} type="button" className="ai-chat-quick-action" onClick={() => sendText(a.text)}>
                      <span aria-hidden="true">{a.icon}</span> {a.label}
                    </button>
                  ))}
                </div>
                <div className="ai-chat-chips">
                  {SUGGESTION_CHIPS.map((c) => (
                    <button key={c} type="button" className="ai-chat-chip" onClick={() => sendText(c)}>
                      {c}
                    </button>
                  ))}
                </div>
              </>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`ai-chat-msg ai-chat-msg-${m.role}`}>
                {m.content}
              </div>
            ))}
            {sending && (
              <div className="ai-chat-msg ai-chat-msg-assistant" aria-label="AAIJI Assistant is typing">
                <span className="ai-chat-typing-dots">
                  <span />
                  <span />
                  <span />
                </span>
              </div>
            )}
          </div>

          {error && <div className="ai-chat-error">{error}</div>}

          <form className="ai-chat-input-row" onSubmit={handleSubmit}>
            <input
              ref={inputRef}
              type="text"
              placeholder="Ask about plants, delivery or your order..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={sending}
              aria-label="Type your question"
            />
            <button type="submit" className="ai-chat-send-btn" disabled={sending || !input.trim()} aria-label="Send message">
              <SendIcon />
            </button>
          </form>
        </div>
      )}
      <button
        type="button"
        className="ai-chat-fab"
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Close AAIJI Assistant" : "AAIJI Assistant"}
        title="AAIJI Assistant"
      >
        {open ? <span style={{ fontSize: "1.6rem", lineHeight: 1 }}>&times;</span> : <LeafIcon size={26} />}
      </button>
    </>
  );
}
