import { useEffect, useRef, useState } from "react";

const SpeechRecognitionCtor =
  typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);

const IS_PHONE = typeof navigator !== "undefined" && /Android|iPhone|iPad/i.test(navigator.userAgent);

const RECORDER_MIME =
  typeof window !== "undefined" && window.MediaRecorder
    ? ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find((m) => MediaRecorder.isTypeSupported(m)) || ""
    : null;

export const voiceModeSupported =
  typeof window !== "undefined" &&
  "speechSynthesis" in window &&
  RECORDER_MIME !== null &&
  Boolean(navigator.mediaDevices?.getUserMedia) &&
  Boolean(window.AudioContext || window.webkitAudioContext);

// --- Voice activity detection tuning --------------------------------------
const SILENCE_MS = 3000; // quiet time after real speech before the question is sent
const ONSET_MS = 250; // voice must last this long to count -- a click or cough doesn't
const SUSTAIN_MS = 120; // ...and this long to reset the silence timer mid-pause
const MAX_UTTERANCE_MS = 45000;
const DEAD_AIR_MS = 15000; // recording restarts after this much pre-speech silence
const MIN_RMS = 0.008; // absolute floor for "voice", in the speech band
const BARGE_RMS = 0.18; // much louder bar while AAIJI talks: its own voice reaches the mic
const BARGE_MS = 450;
const TICK_MS = 30;

const SORRY_REPEAT = "Sorry, I didn't catch that. Could you please repeat?";
const SORRY_STT = "Sorry, voice recognition is not available right now. Please type your question.";

// Picks the most natural *Indian* voice this device has. Order matters:
// neural/"Natural" Indian voices first, then any Indian voice, and a generic
// (Western-accented) English voice only when the device has nothing Indian.
// Hinglish is read by a Hindi voice -- an English voice mangles Hindi words.
function pickIndianVoice(text) {
  const voices = window.speechSynthesis.getVoices();
  const hinglish = /[ऀ-ॿ]/.test(text) || HINGLISH_WORDS.test(text);
  const order = hinglish ? ["hi-IN", "en-IN"] : ["en-IN", "hi-IN"];
  const norm = (v) => v.lang.replace("_", "-");
  for (const lang of order) {
    const pool = voices.filter((v) => norm(v) === lang);
    const best = pool.find((v) => /natural|neural|online/i.test(v.name)) || pool.find((v) => /google/i.test(v.name)) || pool[0];
    if (best) return best;
  }
  return voices.find((v) => /india/i.test(v.name)) || voices.find((v) => v.lang.startsWith("en")) || null;
}

const HINGLISH_WORDS =
  /\b(hai|hain|nahi|nhi|kya|aaj|kal|kitna|kitne|kitni|ka|ki|ke|ko|mein|se|aur|tha|thi|hua|hui|raha|rahi|rahe|kiya|abhi|sab|koi|yeh|woh|aapka|aapke|baare|liye)\b/i;

// Test-only switch: localStorage askAaijiSttLang = "hi" asks the server to
// transcribe in Hindi. Production never sets it, so it stays English.
function sttLangQuery() {
  try {
    return localStorage.getItem("askAaijiSttLang") === "hi" ? "?lang=hi" : "";
  } catch {
    return "";
  }
}

// One place for how AAIJI sounds: Indian voice, unhurried pace, and text
// reshaped so it is said the way a person would say it.
export function buildUtterance(text) {
  const spoken = text
    .replace(/₹\s?([\d,]+(?:\.\d+)?)/g, "$1 rupees")
    .replace(/₹/g, "rupees ")
    .replace(/Rs\.?\s?([\d,]+(?:\.\d+)?)/g, "$1 rupees")
    .replace(/--|\s[-–—]\s/g, ", ")
    .replace(/[*_#`]/g, "")
    .replace(/\s*\n+\s*/g, ". ")
    .replace(/\.\s*\./g, ".");
  const utter = new SpeechSynthesisUtterance(spoken);
  const voice = pickIndianVoice(text);
  if (voice) {
    utter.voice = voice;
    utter.lang = voice.lang.replace("_", "-");
  } else {
    utter.lang = "en-IN";
  }
  utter.rate = 0.94;
  utter.pitch = 1;
  return utter;
}

const STATUS_TEXT = {
  idle: "Starting...",
  ready: "Ready",
  listening: "Listening...",
  thinking: "Processing...",
  speaking: "AAIJI is speaking...",
  muted: "Microphone muted",
  denied: "Microphone access is required",
};

const SUB_TEXT = {
  idle: "",
  ready: "Start speaking whenever you like",
  listening: "I'll answer when you pause",
  thinking: "Working on your request",
  speaking: "Tap the orb or speak up to interrupt",
  muted: "Unmute to continue",
  denied: "Allow microphone access to use AAIJI Voice.",
};

// What the microphone is doing right now, stated plainly. "Listening" only
// while a voice is actually being captured -- never for room noise.
const MIC_TEXT = {
  idle: "○ Not listening",
  ready: "○ Waiting for your voice",
  listening: "● Listening",
  thinking: "○ Not listening",
  speaking: "○ Not listening",
  muted: "○ Microphone off",
  denied: "○ Microphone off",
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

// Full-screen voice conversation for Ask AAIJI.
//
// Pipeline: microphone -> speech-band filter -> voice activity detection ->
// recording -> server transcription (Whisper, /admin/ai/transcribe) -> the
// page's own sendText via `onAsk` -> spoken reply -> back to waiting.
//
// Only the voice loop lives here. The question is answered exactly as a typed
// one would be, so history, permissions and backend behaviour are unchanged.
export default function AskAaijiVoice({ onAsk, onClose }) {
  const [state, setState] = useState("idle");
  const [muted, setMuted] = useState(false);
  const [heard, setHeard] = useState("");
  const orbRef = useRef(null);
  const endRef = useRef(null);
  const onAskRef = useRef(onAsk);
  onAskRef.current = onAsk;
  // Everything the loop touches outside React state, so callbacks never act
  // on a stale closure and cleanup can reach all of it.
  // mode: "off" | "listen" | "think" | "speak"
  const r = useRef({
    closed: false, muted: false, mode: "off", timers: [], interval: 0, level: 0,
    stream: null, ctx: null, analyser: null, buf: null,
    recorder: null, recStart: 0, caption: null, captionText: "", captionOff: false,
    floor: 0.004, avg: 0, run: 0, started: false, startedAt: 0, lastVoice: 0, lastTick: 0, barge: 0,
    utter: null, spokeAt: 0, turn: 0,
  });

  function setLevel(v) {
    r.current.level = v;
    if (orbRef.current) orbRef.current.style.setProperty("--level", v.toFixed(3));
  }

  function later(fn, ms) {
    const id = setTimeout(fn, ms);
    r.current.timers.push(id);
    return id;
  }

  // --- recording ----------------------------------------------------------

  function startRecorder() {
    const s = r.current;
    if (!s.stream) return;
    const chunks = [];
    let rec;
    try {
      rec = new MediaRecorder(s.stream, RECORDER_MIME ? { mimeType: RECORDER_MIME, audioBitsPerSecond: 32000 } : { audioBitsPerSecond: 32000 });
    } catch {
      return;
    }
    rec.ondataavailable = (e) => e.data && e.data.size && chunks.push(e.data);
    rec.chunks = chunks;
    rec.start();
    s.recorder = rec;
    s.recStart = performance.now();
  }

  // Resolves with the recorded audio, or null when `keep` is false.
  function stopRecorder(keep) {
    const s = r.current;
    const rec = s.recorder;
    s.recorder = null;
    if (!rec || rec.state === "inactive") return Promise.resolve(null);
    return new Promise((resolve) => {
      rec.onstop = () => resolve(keep && rec.chunks.length ? new Blob(rec.chunks, { type: rec.mimeType || RECORDER_MIME || "audio/webm" }) : null);
      try {
        rec.stop();
      } catch {
        resolve(null);
      }
    });
  }

  // --- live caption -------------------------------------------------------
  // The browser's own recogniser runs alongside purely to show words as they
  // are spoken (and as a fallback if the server transcription fails). It never
  // decides when a turn starts or ends. Phones can't share the mic with it.

  function startCaption() {
    const s = r.current;
    if (!SpeechRecognitionCtor || IS_PHONE || s.captionOff || s.caption) return;
    const rec = new SpeechRecognitionCtor();
    // Hindi-first, matching the server transcription: Hindi comes out in Devanagari.
    rec.lang = "hi-IN";
    rec.interimResults = true;
    rec.continuous = true;
    let base = s.captionText;
    rec.onresult = (e) => {
      let t = "";
      for (let i = 0; i < e.results.length; i++) t += e.results[i][0].transcript;
      s.captionText = `${base} ${t}`.trim();
      if (s.mode === "listen") setHeard(s.captionText);
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed" || e.error === "audio-capture") s.captionOff = true;
    };
    rec.onend = () => {
      if (s.caption !== rec) return;
      s.caption = null;
      base = s.captionText;
      if (!s.closed && s.mode === "listen") later(startCaption, 300);
    };
    s.caption = rec;
    try {
      rec.start();
    } catch {
      s.caption = null;
    }
  }

  function stopCaption() {
    const s = r.current;
    const rec = s.caption;
    s.caption = null;
    if (!rec) return;
    rec.onend = null;
    rec.onresult = null;
    try {
      rec.abort();
    } catch {
      // already stopped
    }
  }

  // --- turn-taking --------------------------------------------------------

  function beginListening() {
    const s = r.current;
    if (s.closed || s.muted || !s.stream) return;
    s.turn += 1;
    s.mode = "listen";
    s.started = false;
    s.run = 0;
    s.barge = 0;
    s.captionText = "";
    setHeard("");
    setLevel(0);
    setState("ready");
    stopRecorder(false);
    startRecorder();
    startCaption();
  }

  // Runs every TICK_MS. Voice is judged on loudness *in the speech band*
  // (the filter in front of the analyser has already removed fan/AC rumble
  // and hiss) relative to a noise floor that tracks the room, and it must
  // persist -- so steady noise and short knocks never count as speech.
  function tick() {
    const s = r.current;
    const now = performance.now();
    const dt = Math.min(200, now - (s.lastTick || now));
    s.lastTick = now;
    if (s.closed || s.muted || !s.analyser || (s.mode !== "listen" && s.mode !== "speak")) return;

    s.analyser.getFloatTimeDomainData(s.buf);
    let sum = 0;
    for (let i = 0; i < s.buf.length; i++) sum += s.buf[i] * s.buf[i];
    const rms = Math.sqrt(sum / s.buf.length);

    if (s.mode === "speak") {
      // Barge-in. AAIJI's own voice comes back through the mic, so only a
      // clearly louder, sustained voice interrupts -- and not in the first
      // moment. Tapping the orb always works.
      if (now - s.spokeAt < 800) return;
      s.barge = rms > Math.max(BARGE_RMS, s.floor * 8) ? s.barge + dt : Math.max(0, s.barge - dt);
      if (s.barge >= BARGE_MS) interrupt();
      return;
    }

    const voice = rms > Math.max(MIN_RMS, s.floor * 3);
    s.avg = s.avg * 0.98 + rms * 0.02;
    if (voice) {
      s.run = Math.min(600, s.run + dt);
      s.floor = s.floor * 0.9998 + rms * 0.0002;
    } else {
      s.run = Math.max(0, s.run - dt);
      s.floor = rms < s.floor ? s.floor * 0.7 + rms * 0.3 : s.floor * 0.95 + rms * 0.05;
    }

    if (!s.started) {
      if (s.run >= ONSET_MS) {
        s.started = true;
        s.startedAt = now;
        s.lastVoice = now;
        setState("listening");
        if (s.captionText) setHeard(s.captionText);
      } else if (s.run === 0 && now - s.recStart > DEAD_AIR_MS) {
        // Nothing said yet: drop the silent recording instead of letting it grow.
        stopRecorder(false);
        startRecorder();
      }
      return;
    }

    if (voice && s.run >= SUSTAIN_MS) s.lastVoice = now;
    setLevel(s.level * 0.7 + Math.min(1, Math.max(0, rms - s.floor * 2) * 6) * 0.3);
    if (now - s.lastVoice >= SILENCE_MS || now - s.startedAt >= MAX_UTTERANCE_MS) finishTurn();
  }

  async function finishTurn() {
    const s = r.current;
    const turn = s.turn;
    const stale = () => s.closed || s.turn !== turn || s.mode !== "think";
    s.mode = "think";
    setLevel(0);
    setState("thinking");
    const caption = s.captionText.trim();
    stopCaption();
    const audio = await stopRecorder(true);
    if (stale()) return;

    let text = "";
    let status = "failed";
    if (audio) {
      try {
        const res = await fetch(`/api/admin/ai/transcribe${sttLangQuery()}`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": (audio.type || "audio/webm").split(";")[0] },
          body: audio,
        });
        if (res.status === 401) {
          window.location.href = "/admin/login";
          return;
        }
        if (res.ok) {
          const data = await res.json();
          text = (data.text || "").trim();
          status = data.status;
        }
      } catch {
        status = "failed";
      }
    }
    if (stale()) return;

    if (status === "failed") {
      // Server transcription unavailable: fall back to what the browser heard.
      if (caption) text = caption;
      else return say(SORRY_STT);
    } else if (status === "unclear") {
      return say(SORRY_REPEAT);
    } else if (!text) {
      // It was noise after all. Treat this level as the room's normal and go
      // back to waiting, without saying anything.
      s.floor = Math.max(s.floor, s.avg * 0.8);
      return beginListening();
    }

    setHeard(text);
    let result = null;
    try {
      result = await onAskRef.current(text);
    } catch {
      result = null;
    }
    if (stale()) return;
    say((result && (result.reply || result.error)) || "Sorry, I could not get an answer. Please try again.");
  }

  function say(text) {
    const s = r.current;
    const turn = s.turn;
    s.mode = "speak";
    s.barge = 0;
    setState("speaking");
    setHeard("");
    const utter = buildUtterance(text);
    let finished = false;
    const done = () => {
      if (finished || s.closed || s.turn !== turn) return;
      finished = true;
      window.speechSynthesis.cancel();
      setLevel(0);
      if (s.muted) {
        s.mode = "off";
        setState("muted");
      } else beginListening();
    };
    utter.onend = done;
    utter.onerror = done;
    // The browser gives no audio stream for its own speech, so the orb is
    // nudged on each spoken word instead -- close to, not exactly, in sync.
    utter.onboundary = () => {
      if (s.mode !== "speak") return;
      setLevel(0.55);
      later(() => s.mode === "speak" && setLevel(0.15), 140);
    };
    // Some browsers never fire onend for long text; don't get stuck.
    later(done, Math.min(90000, 4000 + text.length * 95));
    // Held on the ref so the browser can't garbage-collect it mid-speech, and
    // spoken a beat after any cancel() -- Chrome drops a speak() that follows
    // a cancel() too closely, and stays silent if the engine was left paused.
    s.utter = utter;
    s.spokeAt = performance.now();
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
    if (s.mode !== "speak") return;
    window.speechSynthesis.cancel();
    setLevel(0);
    if (s.muted) {
      s.mode = "off";
      setState("muted");
    } else beginListening();
  }

  // --- microphone ---------------------------------------------------------

  async function openMic() {
    const s = r.current;
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    } catch {
      if (s.closed) return;
      s.muted = true;
      s.mode = "off";
      setMuted(true);
      setState("denied");
      return;
    }
    if (s.closed) {
      stream.getTracks().forEach((t) => t.stop());
      return;
    }
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    ctx.resume?.().catch(() => {});
    // Speech lives roughly between 200 Hz and 3.5 kHz. Fans, AC and traffic
    // rumble sit below that, hiss above it -- neither reaches the detector.
    const high = ctx.createBiquadFilter();
    high.type = "highpass";
    high.frequency.value = 200;
    const low = ctx.createBiquadFilter();
    low.type = "lowpass";
    low.frequency.value = 3500;
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(high);
    high.connect(low);
    low.connect(analyser);
    s.stream = stream;
    s.ctx = ctx;
    s.analyser = analyser;
    s.buf = new Float32Array(analyser.fftSize);
    s.muted = false;
    setMuted(false);
    clearInterval(s.interval);
    s.interval = setInterval(tick, TICK_MS);
    beginListening();
  }

  function closeMic() {
    const s = r.current;
    clearInterval(s.interval);
    stopCaption();
    stopRecorder(false);
    s.stream?.getTracks().forEach((t) => t.stop());
    s.ctx?.close().catch(() => {});
    s.stream = null;
    s.ctx = null;
    s.analyser = null;
  }

  function tryAgain() {
    setState("idle");
    openMic();
  }

  function toggleMute() {
    const s = r.current;
    if (!s.stream) return tryAgain();
    if (s.muted) {
      s.muted = false;
      setMuted(false);
      s.stream.getAudioTracks().forEach((t) => (t.enabled = true));
      if (s.mode !== "think" && s.mode !== "speak") beginListening();
    } else {
      s.muted = true;
      setMuted(true);
      s.stream.getAudioTracks().forEach((t) => (t.enabled = false));
      if (s.mode === "listen") {
        // Whatever was half-said is discarded, not sent.
        s.turn += 1;
        s.mode = "off";
        stopCaption();
        stopRecorder(false);
        setHeard("");
        setLevel(0);
        setState("muted");
      }
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
    openMic();

    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      s.closed = true;
      s.mode = "off";
      s.timers.forEach(clearTimeout);
      s.timers = [];
      window.speechSynthesis.cancel();
      closeMic();
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
        <div className="aaiji-voice-heard">{heard && ["listening", "thinking", "speaking"].includes(state) ? `“${heard}”` : ""}</div>
        <div className="aaiji-voice-micstate">{MIC_TEXT[state]}</div>
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
