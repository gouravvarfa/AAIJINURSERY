import { useEffect, useState } from "react";
import { api } from "../../api";
import { sanitizeQuantityText } from "../../utils/quantity";

// Per-line decision for an order that asks for more than may be in stock:
// give some / all of the pending quantity from nursery stock now, or mark it
// "nursery will prepare". Nothing is taken from stock automatically.
// Used on the website order page (kind="order") and on offline Sales Orders
// (kind="sales_order"). The server enforces the same rules shown here.
export default function FulfilmentPanel({ kind, items, open, onChanged }) {
  const [stock, setStock] = useState({}); // "plantId:variantId" -> available
  const [qty, setQty] = useState({}); // item id -> typed text
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    // Staff without Products access simply don't get the stock hints; the server still checks.
    api
      .get("/admin/inventory/stock-demand")
      .then((d) => setStock(Object.fromEntries(d.items.map((r) => [`${r.plant_id}:${r.variant_id || 0}`, r.available_stock]))))
      .catch(() => {});
  }, [items.map((i) => `${i.id}:${i.allocated}`).join(",")]);

  const lines = items.filter((i) => i.plant_id);
  if (lines.length === 0) return null;

  async function act(item, action, quantity) {
    setBusyId(item.id);
    setError("");
    try {
      await api.post("/admin/inventory/fulfil", { kind, item_id: item.id, action, quantity: quantity || null });
      setQty((q) => ({ ...q, [item.id]: "" }));
      onChanged();
    } catch (err) {
      setError(err.message || "Could not update this line.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
      <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Stock &amp; Preparation</h2>
      <p style={{ margin: "0 0 12px", color: "var(--color-text-muted)", fontSize: "0.88rem" }}>
        Nothing is taken from stock automatically. For each line, give plants from stock or mark them for the nursery to prepare.
      </p>
      {error && <div className="alert alert-error" style={{ marginBottom: 12 }}>{error}</div>}

      {lines.map((item) => {
        const name = item.plant_name || item.description || "Item";
        const unit = item.tray_size ? `trays of ${item.tray_size}` : "plants";
        const available = stock[`${item.plant_id}:${item.variant_id || 0}`];
        const give = Math.min(item.pending, available ?? item.pending);
        const typed = qty[item.id];
        const wanted = typed === undefined || typed === "" ? give : Number(typed);
        const valid = Number.isInteger(wanted) && wanted >= 1 && wanted <= item.pending && (available == null || wanted <= available);
        const state =
          item.pending === 0 ? "Fully from stock" : item.to_prepare ? "Nursery will prepare the rest" : "Not decided yet";
        return (
          <div key={item.id} className="fulfil-line">
            <div style={{ fontWeight: 700 }}>{name}</div>
            <div className="fulfil-numbers">
              <span>Ordered <strong>{item.quantity.toLocaleString("en-IN")}</strong> {unit}</span>
              <span>From stock <strong>{item.allocated.toLocaleString("en-IN")}</strong></span>
              <span>Pending <strong>{item.pending.toLocaleString("en-IN")}</strong></span>
              {available != null && <span>In stock now <strong>{available.toLocaleString("en-IN")}</strong></span>}
            </div>
            <div>
              <span className={`badge ${item.pending === 0 ? "badge-accent" : item.to_prepare ? "badge-gold" : "badge-muted"}`}>{state}</span>
            </div>
            {open && item.pending > 0 && (
              <div className="fulfil-actions">
                <input
                  type="text"
                  inputMode="numeric"
                  className="form-control fulfil-qty"
                  aria-label={`Quantity to give from stock for ${name}`}
                  value={typed === undefined ? String(give || "") : typed}
                  onChange={(e) => setQty((q) => ({ ...q, [item.id]: sanitizeQuantityText(e.target.value) }))}
                />
                <button type="button" className="btn btn-sm btn-primary" disabled={busyId === item.id || !valid || available === 0} onClick={() => act(item, "stock", wanted)}>
                  Give from stock
                </button>
                {item.to_prepare ? (
                  <button type="button" className="btn btn-sm btn-outline dark" disabled={busyId === item.id} onClick={() => act(item, "clear")}>
                    Undo &ldquo;prepare&rdquo;
                  </button>
                ) : (
                  <button type="button" className="btn btn-sm btn-outline dark" disabled={busyId === item.id} onClick={() => act(item, "prepare")}>
                    Nursery will prepare
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
