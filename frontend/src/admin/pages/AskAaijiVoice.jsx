import { useEffect, useRef, useState } from "react";

const SpeechRecognitionCtor =
  typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);

export const voiceModeSupported =
  Boolean(SpeechRecognitionCtor) && typeof window !== "undefined" && "speechSynthesis" in window;

const SILENCE_MS = 5000;
const MIN_CONFIDENCE = 0.3;
const IS_PHONE = typeof navigator !== "undefined" && /Android|iPhone|iPad/i.test(navigator.userAgent);

const STATUS_TEXT = {
  idle: "Ready when you are",
  listening: "Listening...",
  thinking: "Thinking...",
  speaking: "AAIJI is speaking...",
  muted: "Microphone muted",
  denied: "Microphone access is required",
};

const SUB_TEXT = {
  idle: "",
  listening: "Speak now",
  thinking: "Processing your request",
  speaking: "You can interrupt anytime",
  muted: "Unmute to continue",
  denied: "Allow microphone access to use AAIJI Voice.",
};

function MicIcon({ muted }) {
  return (
    <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0" />
      <path d="M12 19v3M8 22h8" />
      {muted && <path d="M3 3l18 18" />}
    </svg>
  );
}

function EndIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

// Full-screen voice conversation for Ask AAIJI. Owns only the voice loop
// (listen -> ask -> speak -> listen) and its visuals; the actual question is
// answered by the page's existing sendText via `onAsk`, so the conversation
// history, permissions and backend behaviour are exactly the same as typing.
export default function AskAaijiVoice({ onAsk, onClose }) {
  const [state, setState] = useState("idle");
  const [muted, setMuted] = useState(false);
  const [heard, setHeard] = useState("");
  const orbRef = useRef(null);
  const endRef = useRef(null);
  const onAskRef = useRef(onAsk);
  onAskRef.current = onAsk;
  const stateRef = useRef(state);
  stateRef.current = state;
  // Everything the loop touches outside React state, so callbacks never
  // act on a stale closure and cleanup can reach all of it.
  const r = useRef({ closed: false, muted: false, denied: false, rec: null, transcript: "", buffer: "", silence: 0, timers: [], raf: 0, stream: null, ctx: null, analyser: null, level: 0 });

  function setLevel(v) {
    r.current.level = v;
    if (orbRef.current) orbRef.current.style.setProperty("--level", v.toFixed(3));
  }

  function later(fn, ms) {
    const id = setTimeout(fn, ms);
    r.current.timers.push(id);
    return id;
  }

  // The question is sent only after SILENCE_MS with no new recognised words.
  // "Speech" here means the recogniser actually produced words -- mic volume
  // is never used for this, so a fan, AC or keyboard can't start or reset the
  // timer, and nothing is sent until the admin has really said something.
  function armSilenceTimer() {
    const s = r.current;
    clearTimeout(s.silence);
    s.silence = later(() => {
      const text = `${s.buffer} ${s.transcript}`.trim();
      s.buffer = "";
      s.transcript = "";
      if (s.rec) {
        s.rec.onend = null;
        s.rec.onresult = null;
        try {
          s.rec.stop();
        } catch {
          // already stopped
        }
      }
      setLevel(0);
      if (s.closed || s.muted) return;
      if (text) ask(text);
      else listen();
    }, SILENCE_MS);
  }

  // `keep` continues the same question after the recogniser ended on its own
  // (it gives up after a short pause, well before our 5 seconds).
  function listen(keep = false) {
    const s = r.current;
    if (s.closed || s.muted) return;
    if (!keep) {
      clearTimeout(s.silence);
      s.buffer = "";
      setHeard("");
    }
    s.transcript = "";
    setState("listening");
    const rec = new SpeechRecognitionCtor();
    rec.lang = "en-IN";
    rec.interimResults = true;
    rec.continuous = !IS_PHONE; // phones repeat results in continuous mode
    rec.onresult = (e) => {
      let t = "";
      for (let i = 0; i < e.results.length; i++) {
        const alt = e.results[i][0];
        // A final result the recogniser itself barely believes is noise it
        // tried to read as words. (0 means "no score given" -- keep those.)
        if (e.results[i].isFinal && alt.confidence > 0 && alt.confidence < MIN_CONFIDENCE) continue;
        t += alt.transcript;
      }
      if (t.trim() === s.transcript.trim()) return;
      s.transcript = t;
      setHeard(`${s.buffer} ${t}`.trim());
      if (t.trim()) armSilenceTimer();
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") s.denied = true;
    };
    rec.onend = () => {
      if (s.closed) return;
      setLevel(0);
      if (s.denied) {
        s.muted = true;
        setMuted(true);
        setState("denied");
        return;
      }
      if (s.muted) {
        clearTimeout(s.silence);
        s.buffer = "";
        setState("muted");
        return;
      }
      s.buffer = `${s.buffer} ${s.transcript}`.trim();
      s.transcript = "";
      later(() => listen(true), 250); // keep listening; the silence timer decides when to send
    };
    s.rec = rec;
    try {
      rec.start();
    } catch {
      later(() => listen(true), 600);
    }
  }

  async function ask(text) {
    const s = r.current;
    setState("thinking");
    let result = null;
    try {
      result = await onAskRef.current(text);
    } catch {
      result = null;
    }
    if (s.closed) return;
    say((result && (result.reply || result.error)) || "Sorry, I could not get an answer. Please try again.");
  }

  function say(text) {
    const s = r.current;
    setState("speaking");
    setHeard("");
    const utter = new SpeechSynthesisUtterance(text.replace(/₹\s?/g, "rupees ").replace(/--/g, ", "));
    const voices = window.speechSynthesis.getVoices();
    const voice =
      voices.find((v) => v.lang === "hi-IN") || voices.find((v) => v.lang === "en-IN") || voices.find((v) => v.lang.startsWith("en"));
    if (voice) {
      utter.voice = voice;
      utter.lang = voice.lang;
    }
    let finished = false;
    const done = () => {
      if (finished || s.closed) return;
      finished = true;
      window.speechSynthesis.cancel();
      setLevel(0);
      if (s.muted) setState("muted");
      else listen();
    };
    utter.onend = done;
    utter.onerror = done;
    // The browser gives no audio stream for its own speech, so the orb is
    // nudged on each spoken word instead -- close to, not exactly, in sync.
    utter.onboundary = () => {
      setLevel(0.55);
      later(() => stateRef.current === "speaking" && setLevel(0.15), 140);
    };
    // Some browsers never fire onend for long text; don't get stuck.
    later(done, Math.min(90000, 4000 + text.length * 95));
    // Held on the ref so the browser can't garbage-collect it mid-speech, and
    // spoken a beat after any cancel() -- Chrome drops a speak() that follows
    // a cancel() too closely, and stays silent if the engine was left paused.
    s.utter = utter;
    s.spokeAt = Date.now();
    window.speechSynthesis.cancel();
    later(() => {
      if (s.closed || finished) return;
      window.speechSynthesis.resume();
      window.speechSynthesis.speak(utter);
    }, 120);
  }

  // Cut AAIJI off mid-sentence and go straight back to listening.
  function interrupt() {
    const s = r.current;
    if (stateRef.current !== "speaking") return;
    s.timers.forEach(clearTimeout);
    s.timers = [];
    window.speechSynthesis.cancel();
    setLevel(0);
    if (s.muted) setState("muted");
    else listen();
  }

  function tryAgain() {
    const s = r.current;
    s.denied = false;
    s.muted = false;
    setMuted(false);
    navigator.mediaDevices
      ?.getUserMedia({ audio: true })
      .then((stream) => {
        stream.getTracks().forEach((t) => t.stop());
        listen();
      })
      .catch(() => {
        s.denied = true;
        s.muted = true;
        setMuted(true);
        setState("denied");
      });
  }

  function toggleMute() {
    const s = r.current;
    if (s.muted) {
      s.muted = false;
      s.denied = false;
      setMuted(false);
      if (stateRef.current === "muted" || stateRef.current === "denied" || stateRef.current === "idle") listen();
    } else {
      s.muted = true;
      setMuted(true);
      s.transcript = "";
      s.buffer = "";
      clearTimeout(s.silence);
      setHeard("");
      if (stateRef.current === "listening") {
        try {
          s.rec?.stop();
        } catch {
          // already stopped
        }
        setState("muted");
      } else if (stateRef.current === "idle") setState("muted");
    }
  }

  useEffect(() => {
    const s = r.current;
    s.closed = false;
    endRef.current?.focus();
    // Unlock speech while the tap that opened this is still fresh: phones
    // refuse a first speak() that arrives seconds later, after the answer.
    try {
      const prime = new SpeechSynthesisUtterance(" ");
      prime.volume = 0;
      window.speechSynthesis.speak(prime);
      window.speechSynthesis.getVoices();
    } catch {
      // speech just stays locked; the text answer still shows in the chat
    }

    // Real microphone level for the listening animation. Optional: if the
    // browser refuses a second mic consumer, the orb just breathes instead.
    if (!IS_PHONE &&navigator.mediaDevices?.getUserMedia) {
      navigator.mediaDevices
        .getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
        .then((stream) => {
          if (s.closed) {
            stream.getTracks().forEach((t) => t.stop());
            return;
          }
          const Ctx = window.AudioContext || window.webkitAudioContext;
          const ctx = new Ctx();
          const analyser = ctx.createAnalyser();
          analyser.fftSize = 512;
          ctx.createMediaStreamSource(stream).connect(analyser);
          s.stream = stream;
          s.ctx = ctx;
          s.analyser = analyser;
          const buf = new Uint8Array(analyser.fftSize);
          let loudFrames = 0;
          let noiseFloor = 0.02;
          const tick = () => {
            if (s.closed) return;
            // Barge-in: sustained loud speech while AAIJI is talking stops it.
            // Needs a clear voice well above speaker bleed, so it can miss
            // quiet interruptions -- tapping the orb always works.
            // Only once AAIJI has been audible for a moment, and only on a very
            // loud voice: its own speaker output reaches the mic too, and a
            // lower bar made it cut itself off before a word was heard.
            if (stateRef.current === "speaking" && !s.muted && Date.now() - s.spokeAt > 1500) {
              analyser.getByteTimeDomainData(buf);
              let sum = 0;
              for (let i = 0; i < buf.length; i++) {
                const d = (buf[i] - 128) / 128;
                sum += d * d;
              }
              loudFrames = Math.sqrt(sum / buf.length) > 0.3 ? loudFrames + 1 : 0;
              if (loudFrames > 40) {
                loudFrames = 0;
                interrupt();
              }
            } else {
              loudFrames = 0;
            }
            if (stateRef.current === "listening") {
              analyser.getByteTimeDomainData(buf);
              let sum = 0;
              for (let i = 0; i < buf.length; i++) {
                const d = (buf[i] - 128) / 128;
                sum += d * d;
              }
              // Subtract the room's steady hum (tracked as a slow-rising,
              // fast-falling floor) so the orb moves for a voice, not a fan.
              const raw = Math.sqrt(sum / buf.length);
              noiseFloor = raw < noiseFloor ? raw : noiseFloor * 0.995 + raw * 0.005;
              const rms = Math.min(1, Math.max(0, raw - noiseFloor * 1.8 - 0.01) * 5);
              setLevel(s.level * 0.75 + rms * 0.25);
            }
            s.raf = requestAnimationFrame(tick);
          };
          s.raf = requestAnimationFrame(tick);
        })
        .catch((e) => {
          if (e && (e.name === "NotAllowedError" || e.name === "SecurityError")) {
            s.denied = true;
            s.muted = true;
            setMuted(true);
            setState("denied");
          }
        });
    }

    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    later(() => listen(), 700);

    return () => {
      s.closed = true;
      s.timers.forEach(clearTimeout);
      s.timers = [];
      cancelAnimationFrame(s.raf);
      if (s.rec) {
        s.rec.onend = null;
        s.rec.onresult = null;
        try {
          s.rec.stop();
        } catch {
          // already stopped
        }
      }
      window.speechSynthesis.cancel();
      s.stream?.getTracks().forEach((t) => t.stop());
      s.ctx?.close().catch(() => {});
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, []);

  return (
    <div className="aaiji-voice" data-state={state} role="dialog" aria-modal="true" aria-label="AAIJI voice conversation">
      <button type="button" className="aaiji-voice-close" onClick={onClose} aria-label="Exit voice mode" title="Exit voice mode">
        <EndIcon />
      </button>
      <div className="aaiji-voice-stage">
        <div className="aaiji-orb" ref={orbRef} onClick={interrupt} aria-hidden="true">
          <span className="aaiji-orb-ring r3" />
          <span className="aaiji-orb-ring r2" />
          <span className="aaiji-orb-ring r1" />
          <span className="aaiji-orb-arc" />
          <span className="aaiji-orb-core" />
        </div>
        <div className="aaiji-voice-name">AAIJI</div>
        <div className="aaiji-voice-sub">Business Intelligence Assistant</div>
        <div className="aaiji-voice-status" aria-live="polite">
          {STATUS_TEXT[state]}
        </div>
        <div className="aaiji-voice-secondary">{SUB_TEXT[state]}</div>
        {state === "denied" && (
          <button type="button" className="aaiji-voice-retry" onClick={tryAgain}>
            Try Again
          </button>
        )}
        <div className="aaiji-voice-heard">{state === "listening" ? heard : ""}</div>
      </div>

      <div className="aaiji-voice-controls">
        <button
          type="button"
          className={`aaiji-voice-mic${muted ? " muted" : ""}`}
          onClick={toggleMute}
          aria-pressed={muted}
          aria-label={muted ? "Unmute microphone" : "Mute microphone"}
          title={muted ? "Unmute microphone" : "Mute microphone"}
        >
          <MicIcon muted={muted} />
        </button>
        <button
          type="button"
          ref={endRef}
          className="aaiji-voice-end"
          onClick={onClose}
          aria-label="End voice conversation"
          title="End voice conversation"
        >
          <EndIcon />
          <span>End</span>
        </button>
      </div>
    </div>
  );
}
