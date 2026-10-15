import { useState } from "react";

export const num = (v) => Number(v || 0).toLocaleString("en-IN");

// Plain-language names for every ledger movement, so nobody has to learn the codes.
export const MOVEMENT_LABEL = {
  RECEIVED: "Seeds received",
  ISSUED: "Seeds given to a batch",
  RETURNED: "Unused seeds put back",
  CONSUMED: "Seeds used up",
  WASTED: "Seeds spoiled in a batch",
  DAMAGED: "Seeds damaged in the store",
  PRODUCTION_RECEIVED: "Ready plants added from a batch",
  SALE: "Plants given to an order",
  SALE_REVERSAL: "Order cancelled: plants put back",
  MANUAL_ADJUSTMENT: "Count corrected",
  OPENING_STOCK: "Opening stock",
  PURCHASE_RECEIVED: "Bought and received",
};

export const STATUS_BADGE = { Draft: "badge-muted", "In Progress": "badge-gold", Completed: "badge-accent", Cancelled: "badge-danger" };

// A short "How this works" box on every Stock page. Open the first time, then remembers the choice.
export function StockHelp({ id, title = "How this works", steps, note }) {
  const key = `aaiji_stock_help_${id}`;
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(key) !== "closed";
    } catch {
      return true;
    }
  });
  function toggle() {
    const next = !open;
    setOpen(next);
    try {
      localStorage.setItem(key, next ? "open" : "closed");
    } catch {
      // storage blocked: the box just won't remember
    }
  }
  return (
    <div className="stock-help">
      <button type="button" className="stock-help-head" onClick={toggle} aria-expanded={open}>
        <span aria-hidden="true">💡</span> {title} <span className="stock-help-toggle">{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <div className="stock-help-body">
          <ol>
            {steps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
          {note && <p className="stock-help-note">{note}</p>}
        </div>
      )}
    </div>
  );
}

export function Hint({ children }) {
  return <p className="stock-hint">{children}</p>;
}
