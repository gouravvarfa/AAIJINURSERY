import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";

// Finds orders the nursery team has just confirmed, for the logged-in
// customer, wherever they are browsing. The backend is the only source of
// truth (team_confirmation_status === "CONFIRMED"); nothing is shown before it
// says so.
//
// "Already seen" ids live in localStorage per customer. The first look after
// login only records what is already confirmed (no popup for old orders);
// after that, every order that turns CONFIRMED is shown exactly once, even if
// the customer was away when it happened. Polling is light (every 20s while
// the tab is visible) and silent on errors, and it reconciles by order id so
// repeated or overlapping responses can't create duplicate popups.
const POLL_MS = 20000;
const key = (customerId) => `aaiji_seen_confirmed_${customerId}`;

function loadSeen(customerId) {
  try {
    const raw = localStorage.getItem(key(customerId));
    return raw === null ? null : new Set(JSON.parse(raw));
  } catch {
    return null;
  }
}

function saveSeen(customerId, seen) {
  try {
    localStorage.setItem(key(customerId), JSON.stringify([...seen].slice(-500)));
  } catch {
    // private mode / blocked storage: the popup may repeat after a reload, nothing else breaks
  }
}

export default function useOrderConfirmations(customerId) {
  const [queue, setQueue] = useState([]); // orders waiting to be announced, oldest first
  const seenRef = useRef(null);
  const queuedRef = useRef(new Set());

  const check = useCallback(async () => {
    if (!customerId) return;
    let orders;
    try {
      orders = await api.get("/customer/orders");
    } catch {
      return; // offline / server hiccup: try again next time
    }
    if (!Array.isArray(orders)) return;
    const confirmed = orders.filter((o) => o.team_confirmation_status === "CONFIRMED" && o.status !== "Cancelled");

    if (seenRef.current === null) {
      const stored = loadSeen(customerId);
      if (stored === null) {
        // first look on this browser: whatever is confirmed already is old news
        seenRef.current = new Set(confirmed.map((o) => o.id));
        saveSeen(customerId, seenRef.current);
        return;
      }
      seenRef.current = stored;
    }

    const fresh = confirmed
      .filter((o) => !seenRef.current.has(o.id) && !queuedRef.current.has(o.id))
      .sort((a, b) => String(a.team_confirmed_at || "").localeCompare(String(b.team_confirmed_at || "")));
    if (fresh.length === 0) return;
    fresh.forEach((o) => queuedRef.current.add(o.id));
    setQueue((q) => [...q, ...fresh]);
  }, [customerId]);

  useEffect(() => {
    seenRef.current = null;
    queuedRef.current = new Set();
    setQueue([]);
    if (!customerId) return undefined;
    check();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") check();
    }, POLL_MS);
    const onVisible = () => document.visibilityState === "visible" && check();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", check);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", check);
    };
  }, [customerId, check]);

  // Marks the order as announced (whichever button closed the popup) and moves on to the next one.
  const dismiss = useCallback(
    (orderId) => {
      if (seenRef.current) {
        seenRef.current.add(orderId);
        saveSeen(customerId, seenRef.current);
      }
      queuedRef.current.delete(orderId);
      setQueue((q) => q.filter((o) => o.id !== orderId));
    },
    [customerId]
  );

  return { current: queue[0] || null, dismiss };
}
