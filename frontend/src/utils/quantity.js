// Order quantity rules shared by every quantity control.
//
// Quantity is NEVER limited by stock (the nursery prepares what it does not
// have in stock). The only limits are: a whole number, at least 1, and a safe
// upper bound that matches the server's MAX_ORDER_QUANTITY.
export const MAX_ORDER_QUANTITY = 1000000;

// Keeps only digits (so pasted "1,000", "5 000", "250 plants" or "-3" become
// usable text) and caps the length.
export function sanitizeQuantityText(text, max = MAX_ORDER_QUANTITY) {
  return String(text ?? "").replace(/\D/g, "").slice(0, String(max).length);
}

// Returns a whole number from 1..max, or null when the text is not a valid
// quantity yet (empty, 0, too large).
export function parseQuantity(text, max = MAX_ORDER_QUANTITY) {
  const digits = sanitizeQuantityText(text, max);
  if (!digits) return null;
  const n = Number(digits);
  return Number.isSafeInteger(n) && n >= 1 && n <= max ? n : null;
}

export function stepQuantity(value, delta, max = MAX_ORDER_QUANTITY) {
  const base = Number.isFinite(Number(value)) ? Number(value) : 1;
  return Math.min(max, Math.max(1, Math.trunc(base) + delta));
}

// Customer-facing note about stock. Stock never blocks an order; when there
// is less in stock than asked for, the rest is prepared and the nursery team
// confirms the delivery date.
export function stockNote(available, quantity) {
  const stock = Number(available);
  if (!Number.isFinite(stock)) return "";
  if (stock >= quantity) return "In stock";
  if (stock > 0) {
    const rest = (quantity - stock).toLocaleString("en-IN");
    return `${stock.toLocaleString("en-IN")} in stock now. The remaining ${rest} will be prepared for you, and our team will confirm the delivery date.`;
  }
  return "Made to order. Our team will prepare it and confirm the delivery date.";
}
