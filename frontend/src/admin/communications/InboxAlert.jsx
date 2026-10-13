import { useEffect, useState, useSyncExternalStore } from "react";
import { api } from "../../api";

// One poller for the whole admin shell, so a new WhatsApp message is noticed
// on any page: the Inbox menu shows an unread badge, the browser tab title
// gets a "(n)" prefix, and a short beep plays when a new one arrives.
const POLL_MS = 15000;
let unread = 0;
const listeners = new Set();

function setUnread(n) {
  if (n === unread) return;
  unread = n;
  listeners.forEach((fn) => fn());
}

export function useInboxUnread() {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    () => unread
  );
}

export function InboxBadge() {
  const n = useInboxUnread();
  if (!n) return null;
  return (
    <span className="badge badge-accent" style={{ marginLeft: 8 }} aria-label={`${n} unread WhatsApp messages`}>
      {n > 99 ? "99+" : n}
    </span>
  );
}

function beep() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.35);
    osc.onended = () => ctx.close();
  } catch {
    // Browsers block sound until the page has been interacted with; the badge still shows.
  }
}

export default function InboxAlert() {
  const n = useInboxUnread();
  const [baseTitle] = useState(() => document.title.replace(/^\(\d+\)\s*/, ""));

  useEffect(() => {
    let alive = true;
    let first = true;
    function poll() {
      api
        .get("/admin/communications/inbox/unread-count")
        .then((d) => {
          if (!alive) return;
          if (!first && d.count > unread) beep();
          first = false;
          setUnread(d.count);
        })
        .catch(() => {});
    }
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    document.title = n ? `(${n}) ${baseTitle}` : baseTitle;
    return () => {
      document.title = baseTitle;
    };
  }, [n, baseTitle]);

  return null;
}
