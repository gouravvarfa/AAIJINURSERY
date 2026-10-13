// Delivery-date alert for the Sales Orders / Invoices lists.
//
// Delivery dates are saved as plain calendar dates ("2026-10-20T00:00:00",
// no zone). They are compared as calendar days against today's date in India
// (Asia/Kolkata) -- never through `new Date(value)`, which would shift the day
// depending on the browser's zone.
//
//   overdue  (before today)  red, "Overdue 2d"
//   today                    red, "Due today"
//   tomorrow                 orange
//   in 2-3 days              orange
//   later than 3 days        green
//
// No alert (null) when there is no date, or the order / invoice / delivery is
// already finished or cancelled.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DONE_DELIVERY = ["Delivered", "Partially Delivered", "Cancelled"];
const DEAD_DOCUMENT = ["Cancelled", "Voided"];

export function istToday(now = new Date()) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

function dayNumber(ymd) {
  const [y, m, d] = ymd.split("-").map(Number);
  return Date.UTC(y, m - 1, d) / 86400000;
}

export function dateOnly(value) {
  const text = String(value || "").slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : "";
}

export function formatDeliveryDate(value) {
  const ymd = dateOnly(value);
  if (!ymd) return "";
  const [y, m, d] = ymd.split("-").map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

export function deliveryAlert({ deliveryDate, deliveryStatus, status } = {}, today = istToday()) {
  const ymd = dateOnly(deliveryDate);
  if (!ymd) return null;
  if (DEAD_DOCUMENT.includes(status) || DONE_DELIVERY.includes(deliveryStatus)) return null;
  const days = dayNumber(ymd) - dayNumber(today);
  if (days < 0) return { level: "red", kind: "overdue", days, label: `Overdue ${-days}d` };
  if (days === 0) return { level: "red", kind: "today", days, label: "Due today" };
  if (days === 1) return { level: "orange", kind: "tomorrow", days, label: "Due tomorrow" };
  if (days <= 3) return { level: "orange", kind: "soon", days, label: `Due in ${days} days` };
  return { level: "green", kind: "later", days, label: `In ${days} days` };
}

export const DELIVERY_FILTERS = [
  { value: "", label: "All delivery dates" },
  { value: "overdue", label: "Overdue" },
  { value: "today", label: "Due today" },
  { value: "tomorrow", label: "Due tomorrow" },
  { value: "soon", label: "Next 3 days" },
  { value: "later", label: "Later (4+ days)" },
  { value: "none", label: "No date / no alert" },
];

export function matchesDeliveryFilter(info, filter) {
  if (!filter) return true;
  if (filter === "none") return info === null;
  if (!info) return false;
  if (filter === "soon") return info.days >= 0 && info.days <= 3;
  return info.kind === filter;
}
