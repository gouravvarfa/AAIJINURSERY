import { useEffect, useRef, useState } from "react";
import { api } from "../api";

// Customer-facing AI assistant widget. History lives only in this
// component's state (and is gone on refresh) -- never sent anywhere except
// back to /api/ai/chat as context for the next turn, never persisted
// server-side, matching the project's "no raw chat transcript storage"
// convention. Positioned bottom-left specifically so it never collides with
// the WhatsApp button or the mobile bottom tab bar (both bottom-right/
// bottom-fixed on the right side).
export default function AIChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, open]);

  async function send(e) {
    e?.preventDefault();
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setError("");
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setSending(true);
    try {
      const data = await api.post("/ai/chat", { message: text, history });
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
    } catch (err) {
      setError(err.status === 429 ? "Too many messages -- please wait a bit." : "Something went wrong. Please try again.");
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      {open && (
        <div className="ai-chat-panel">
          <div className="ai-chat-header">
            <span>🌿 Aaiji Assistant</span>
            <button type="button" onClick={() => setOpen(false)} aria-label="Close chat">
              &times;
            </button>
          </div>
          <div className="ai-chat-body" ref={scrollRef}>
            {messages.length === 0 && (
              <div className="ai-chat-empty">
                Ask me about plants, prices, stock, delivery, or your order status!
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`ai-chat-msg ai-chat-msg-${m.role}`}>
                {m.content}
              </div>
            ))}
            {sending && <div className="ai-chat-msg ai-chat-msg-assistant ai-chat-typing">Typing...</div>}
          </div>
          {error && <div className="ai-chat-error">{error}</div>}
          <form className="ai-chat-input-row" onSubmit={send}>
            <input
              type="text"
              placeholder="Type your question..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={sending}
            />
            <button type="submit" disabled={sending || !input.trim()}>
              Send
            </button>
          </form>
        </div>
      )}
      <button
        type="button"
        className="ai-chat-fab"
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Close AI assistant" : "Open AI assistant"}
      >
        {open ? "×" : "🌿"}
      </button>
    </>
  );
}
