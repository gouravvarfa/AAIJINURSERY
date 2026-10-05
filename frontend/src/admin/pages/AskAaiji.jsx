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

const QUICK_ACTIONS = [
  { title: "Today's sales", desc: "Revenue, orders & comparison", question: "Today's sales", icon: "sales" },
  { title: "Pending orders", desc: "Open orders & status", question: "Pending orders", icon: "orders" },
  { title: "Inventory risks", desc: "Low stock & alerts", question: "Low stock plants", icon: "inventory" },
  { title: "Top products", desc: "Best selling plants", question: "Top selling plants", icon: "products" },
  { title: "Customer activity", desc: "New, returning & total", question: "Recent customers", icon: "customers" },
  { title: "Online vs offline", desc: "Sales channel comparison", question: "Online vs offline sales", icon: "channel" },
  { title: "Pending deliveries", desc: "Today's dispatches", question: "Pending deliveries", icon: "delivery" },
  { title: "Business summary", desc: "Key metrics & insights", question: "Business summary", icon: "summary" },
];

const CONTEXT_MODULES = ["Orders", "Sales & Analytics", "Inventory", "Customers", "Deliveries", "Products & Plants"];

const CHIP_QUESTIONS = ["Show today's sales", "Which plants are low in stock?", "Pending orders status", "Top selling plants"];

const ACTION_PATHS = {
  sales: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  orders: "M9 4h6l1 3H8l1-3zM6 7h12v13H6zM9 12h6",
  inventory: "M12 3 3 7.5v9L12 21l9-4.5v-9L12 3zM3 7.5 12 12l9-4.5M12 12v9",
  products: "M5 19c0-7 5-12 14-13-1 9-6 14-13 14M5 19l6-6",
  customers: "M9 11.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.5 20c.6-3.3 3.2-5 6.5-5s5.9 1.7 6.5 5M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20c-.3-2-1.5-3.6-3.5-4.4",
  channel: "M3 12a9 9 0 0 1 18 0M6.5 15.5a5 5 0 0 1 11 0M12 19h.01",
  delivery: "M3 6h11v10H3zM14 10h4l3 3v3h-7M7 18a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM17 18a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  summary: "M6 3h9l4 4v14H6zM9 13h7M9 17h5M9 9h3",
  ai: "M4 7h16v12H4zM12 3v4M9 13h.01M15 13h.01M9 17h6",
};

function ActionIcon({ name }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ACTION_PATHS[name]} />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0" />
      <path d="M12 19v3M8 22h8" />
    </svg>
  );
}

// Same browser-native speech-to-text as the customer widget (AIChatWidget.jsx)
// -- no API key, no backend involvement. Feature-detected: the mic button
// simply doesn't render on browsers without support (mainly Safari/Firefox).
const SpeechRecognitionCtor =
  typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);

// Admin-only business-intelligence assistant. Calls the dedicated
// POST /api/admin/ai/chat gateway (app/ai/admin_gateway.py) -- a completely
// separate backend route/rate-limit from the customer-facing AI widget,
// reusing the same Groq/Gemini/OpenRouter provider chain. Every answer is
// scoped by the logged-in admin's real RBAC permissions on the backend,
// never decided here. Conversation lives only in this page's state for the
// current session -- gone on refresh/navigation, never persisted server-side.
function SpeakerIcon({ muted }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M11 5 6 9H2v6h4l5 4V5z" />
      {muted ? <path d="m23 9-6 6M17 9l6 6" /> : <path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14" />}
    </svg>
  );
}

const canSpeak = typeof window !== "undefined" && "speechSynthesis" in window;

// Browser's built-in text-to-speech -- free, no API key. Prefers a Hindi
// voice (reads Hinglish naturally), then Indian English, then the default.
function speak(text) {
  if (!canSpeak || !text) return;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text.replace(/₹\s?/g, "rupees ").replace(/--/g, ", "));
  const voices = window.speechSynthesis.getVoices();
  const voice =
    voices.find((v) => v.lang === "hi-IN") || voices.find((v) => v.lang === "en-IN") || voices.find((v) => v.lang.startsWith("en"));
  if (voice) {
    utter.voice = voice;
    utter.lang = voice.lang;
  }
  window.speechSynthesis.speak(utter);
}

function readSpeakPref() {
  try {
    return localStorage.getItem("askAaijiSpeak") === "1";
  } catch {
    return false;
  }
}

export default function AskAaiji() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState(null);
  const [lastFailedText, setLastFailedText] = useState(null);
  const [listening, setListening] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(readSpeakPref);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const recognitionRef = useRef(null);
  const transcriptRef = useRef("");
  const speakRepliesRef = useRef(speakReplies);
  speakRepliesRef.current = speakReplies;

  useEffect(() => () => canSpeak && window.speechSynthesis.cancel(), []);

  function toggleSpeakReplies() {
    const next = !speakReplies;
    setSpeakReplies(next);
    if (!next && canSpeak) window.speechSynthesis.cancel();
    try {
      localStorage.setItem("askAaijiSpeak", next ? "1" : "0");
    } catch {
      // preference just won't persist
    }
  }

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, sending]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    return () => {
      transcriptRef.current = "";
      if (recognitionRef.current) recognitionRef.current.onend = null;
      recognitionRef.current?.stop();
    };
  }, []);

  function toggleListening() {
    if (!SpeechRecognitionCtor) return;
    if (listening) {
      recognitionRef.current?.stop();
      return;
    }
    // Don't let the bot's own voice get picked up as the next question.
    if (canSpeak) window.speechSynthesis.cancel();
    transcriptRef.current = "";
    const recognition = new SpeechRecognitionCtor();
    recognition.lang = "en-IN";
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.onresult = (e) => {
      let transcript = "";
      for (let i = 0; i < e.results.length; i++) transcript += e.results[i][0].transcript;
      transcriptRef.current = transcript;
      setInput(transcript);
    };
    // Voice-to-voice: when the admin stops talking, send what was heard
    // straight away and read the answer back -- no typing or tapping Send.
    recognition.onend = () => {
      setListening(false);
      const heard = transcriptRef.current.trim();
      transcriptRef.current = "";
      if (heard) sendText(heard, true);
    };
    recognition.onerror = () => {
      transcriptRef.current = "";
      setListening(false);
    };
    recognitionRef.current = recognition;
    setListening(true);
    recognition.start();
  }

  async function sendText(text, viaVoice = false) {
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
      if (viaVoice || speakRepliesRef.current) speak(data.reply);
      setStatus(data.provider !== "none" ? "online" : "offline");
    } catch (err) {
      setLastFailedText(trimmed);
      if (err.status === 429) {
        setError("Too many messages -- please wait a few minutes and try again.");
      } else if (err.status === 403) {
        setError(err.message || "You don't have access to Ask AAIJI.");
      } else if (err.status === 401) {
        setError("Your session has expired. Please log in again.");
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

  const today = new Date().toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  const isEmpty = messages.length === 0;

  return (
    <div className="ask-aaiji-page">
      <header className="ask-aaiji-head">
        <div className="ask-aaiji-title">
          <span className="ask-aaiji-logo">
            <ActionIcon name="ai" />
          </span>
          <div>
            <div className="ask-aaiji-title-row">
              <h1>Ask AAIJI</h1>
              <span className={`ask-aaiji-badge${status === "offline" ? " offline" : ""}`}>
                <span className="ask-aaiji-badge-dot" />
                {status === "offline" ? "Temporarily unavailable" : "AI Online"}
              </span>
            </div>
            <p className="ask-aaiji-subtitle">Business Intelligence Assistant</p>
            <p className="ask-aaiji-tagline">Your intelligent interface for understanding AAIJI business data.</p>
          </div>
        </div>
        <div className="ask-aaiji-header-right">
          {canSpeak && (
            <button
              type="button"
              className="btn btn-sm btn-outline dark"
              onClick={toggleSpeakReplies}
              aria-pressed={speakReplies}
              title={speakReplies ? "Voice replies on -- click to mute" : "Read replies aloud"}
              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
            >
              <SpeakerIcon muted={!speakReplies} />
              {speakReplies ? "Voice on" : "Voice off"}
            </button>
          )}
          {!isEmpty && (
            <button type="button" className="btn btn-sm btn-outline dark" onClick={clearConversation}>
              Clear conversation
            </button>
          )}
        </div>
      </header>

      <div className="ask-aaiji-layout">
        <div className="ask-aaiji-main">
          <div className="ask-aaiji-panel">
            <div className="ask-aaiji-body" ref={scrollRef}>
              {isEmpty && (
                <div className="ask-aaiji-welcome">
                  <span className="ask-aaiji-eyebrow">Welcome back</span>
                  <h2>Hello Admin</h2>
                  <p className="ask-aaiji-question">How can I help you today?</p>
                  <p className="ask-aaiji-lead">
                    Ask about sales, orders, inventory, customers, deliveries and business performance.
                  </p>
                  <div className="ask-aaiji-actions">
                    {QUICK_ACTIONS.map((a) => (
                      <button
                        key={a.title}
                        type="button"
                        className="ask-aaiji-action"
                        onClick={() => sendText(a.question)}
                        disabled={sending}
                      >
                        <span className="ask-aaiji-action-icon">
                          <ActionIcon name={a.icon} />
                        </span>
                        <span className="ask-aaiji-action-text">
                          <strong>{a.title}</strong>
                          <small>{a.desc}</small>
                        </span>
                        <span className="ask-aaiji-action-arrow" aria-hidden="true">&rsaquo;</span>
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
              {SpeechRecognitionCtor && (
                <button
                  type="button"
                  className={`ai-chat-mic-btn${listening ? " listening" : ""}`}
                  onClick={toggleListening}
                  disabled={sending}
                  aria-label={listening ? "Stop voice input" : "Speak your question"}
                  title={listening ? "Listening... tap to stop" : "Speak"}
                >
                  <MicIcon />
                </button>
              )}
              <button type="submit" className="ai-chat-send-btn" disabled={sending || !input.trim()} aria-label="Send">
                ➤
              </button>
            </form>
          </div>

          <div className="ask-aaiji-chips">
            {CHIP_QUESTIONS.map((q) => (
              <button key={q} type="button" className="ai-chat-chip" onClick={() => sendText(q)} disabled={sending}>
                {q}
              </button>
            ))}
          </div>
          <div className="ask-aaiji-footnote">
            <span>Read-only business insights</span>
            <span>Uses live business data</span>
          </div>
        </div>

        <aside className="ask-aaiji-side">
          <div className="ask-aaiji-context">
            <h3>Business Context</h3>
            <div className="ask-aaiji-context-row">
              <span className="ask-aaiji-context-label">Date</span>
              <span className="ask-aaiji-context-value">{today}</span>
            </div>
            <div className="ask-aaiji-context-row">
              <span className="ask-aaiji-context-label">Data source</span>
              <span className="ask-aaiji-context-value live">
                <span className="ask-aaiji-badge-dot" /> Live database
              </span>
            </div>
            <div className="ask-aaiji-context-sub">Available modules</div>
            <ul className="ask-aaiji-modules">
              {CONTEXT_MODULES.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
            <div className="ask-aaiji-insights">
              <strong>AI Powered Insights</strong>
              <p>Get instant answers and actionable insights based on your real business data.</p>
              <span className="ask-aaiji-live">
                <span className="ask-aaiji-badge-dot" /> Uses live business data
              </span>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
