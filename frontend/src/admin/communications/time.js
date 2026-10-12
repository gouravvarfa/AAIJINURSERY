// The backend stores and sends timestamps as naive UTC ("2026-10-12T12:42:18",
// no zone). `new Date()` reads such a string as *local* time, so every time
// showed up 5h30m behind IST (12:42 instead of 6:12 PM). Treat zone-less
// values as UTC, then show them in India time.
export function parseServerDate(value) {
  if (!value) return null;
  const text = String(value);
  return new Date(/([zZ]|[+-]\d\d:?\d\d)$/.test(text) ? text : `${text}Z`);
}

export function formatIst(value, withSeconds = false) {
  const d = parseServerDate(value);
  if (!d || Number.isNaN(d.getTime())) return "-";
  return d.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" } : {}),
    hour12: true,
  });
}
