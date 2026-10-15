import { useEffect, useState } from "react";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import { Hint, StockHelp, num } from "../../stock/stockUi";
import { sanitizeQuantityText } from "../../../utils/quantity";

// Ready plants (taiyar paude): what can be sold today.
export default function ReadyPlants() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [fix, setFix] = useState(null); // the row being corrected
  const [count, setCount] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");

  function load() {
    api.get("/admin/inventory/stock-demand").then((d) => setRows(d.items)).catch((e) => setError(e.message || "Could not load the stock."));
  }
  useEffect(load, []);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api.post("/admin/stock/ready/adjust", { plant_id: fix.plant_id, variant_id: fix.variant_id, new_quantity: Number(count), reason });
      setMsg(r.changed_by === 0 ? "The count was already correct, nothing changed." : `Done. Stock changed by ${r.changed_by > 0 ? "+" : ""}${r.changed_by}.`);
      setFix(null);
      setCount("");
      setReason("");
      load();
    } catch (err) {
      setError(err.message || "Could not save the new count.");
    } finally {
      setBusy(false);
    }
  }

  const shown = (rows || []).filter((r) => !q || r.name.toLowerCase().includes(q.toLowerCase()));
  return (
    <div>
      <div className="admin-page-head">
        <h1>Ready Plants (taiyar paude)</h1>
        <div className="admin-page-head-controls">
          <input className="form-control admin-control-sm" placeholder="Search a plant..." value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search plants" />
        </div>
      </div>
      <StockHelp
        id="ready"
        steps={[
          "\"Ready now\" is what you can give to an order today.",
          "\"Given to orders\" plants are already promised to a customer, but not yet delivered.",
          "\"Total in nursery\" = Ready now + Given to orders.",
          "New ready plants come from a finished Production Batch or from buying plants. Don't type them here.",
          "Use \"Correct the count\" only after you physically count the plants. Always write the reason.",
        ]}
      />
      {error && <div className="alert alert-error">{error}</div>}
      {msg && <div className="alert alert-success" role="status">{msg}</div>}
      {!rows && !error ? <Loading /> : shown.length === 0 ? <Empty>No plants found.</Empty> : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead><tr><th>Plant</th><th>Ready now</th><th>Given to orders</th><th>Total in nursery</th><th>Being made</th><th /></tr></thead>
            <tbody>
              {shown.map((r) => (
                <tr key={`${r.plant_id}-${r.variant_id || 0}`}>
                  <td><strong>{r.name}</strong></td>
                  <td><strong>{num(r.available_stock)}</strong> {r.unit}</td>
                  <td>{num(r.reserved_stock)}</td>
                  <td>{num(r.physical_stock)}</td>
                  <td>{r.in_production ? `${num(r.in_production)} ${r.unit}` : "-"}</td>
                  <td><button type="button" className="btn btn-sm btn-outline dark" onClick={() => { setFix(r); setCount(String(r.available_stock)); setReason(""); setMsg(""); }}>Correct the count</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {fix && (
        <div className="admin-form-card" style={{ maxWidth: 560, marginTop: 20 }}>
          <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Correct the count: {fix.name}</h2>
          <form onSubmit={save}>
            <div className="form-group">
              <label htmlFor="fix-count">How many are READY NOW after you counted? (now the system says {num(fix.available_stock)})</label>
              <input id="fix-count" className="form-control" required inputMode="numeric" value={count} onChange={(e) => setCount(sanitizeQuantityText(e.target.value, 100000000))} autoFocus />
            </div>
            <div className="form-group">
              <label htmlFor="fix-reason">Why is it different? (required)</label>
              <input id="fix-reason" className="form-control" required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Physical count: 8 plants dried" />
            </div>
            <button className="btn btn-primary" disabled={busy || count === "" || reason.trim().length < 3}>{busy ? "Saving..." : "Save the new count"}</button>{" "}
            <button type="button" className="btn btn-outline dark" onClick={() => setFix(null)}>Cancel</button>
          </form>
          <Hint>The difference and your reason are written in the Movements list.</Hint>
        </div>
      )}
    </div>
  );
}
