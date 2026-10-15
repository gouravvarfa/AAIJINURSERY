import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import { StockHelp, num } from "../../stock/stockUi";
import { sanitizeQuantityText } from "../../../utils/quantity";

// Orders Waiting: give plants to an order right here.
export default function StockAllocations() {
  const [items, setItems] = useState(null);
  const [ready, setReady] = useState({});
  const [qty, setQty] = useState({});
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(null);
  const [only, setOnly] = useState("waiting");

  function load() {
    api.get("/admin/stock/allocations").then((d) => setItems(d.items)).catch((e) => setError(e.message || "Could not load the orders."));
    api.get("/admin/inventory/stock-demand").then((d) => setReady(Object.fromEntries(d.items.map((r) => [`${r.plant_id}:${r.variant_id || 0}`, r.available_stock])))).catch(() => {});
  }
  useEffect(load, []);

  async function act(r, action, quantity) {
    setBusy(`${r.kind}-${r.item_id}`);
    setError("");
    setMsg("");
    try {
      await api.post("/admin/inventory/fulfil", { kind: r.kind, item_id: r.item_id, action, quantity: quantity || null });
      setMsg(action === "stock" ? `Given ${num(quantity)} to ${r.number}.` : `${r.number}: the nursery will prepare it.`);
      setQty((q) => ({ ...q, [`${r.kind}-${r.item_id}`]: "" }));
      load();
    } catch (err) {
      setError(err.message || "Could not do this.");
    } finally {
      setBusy(null);
    }
  }

  const shown = (items || []).filter((r) => (only === "waiting" ? r.pending > 0 : true));
  return (
    <div>
      <div className="admin-page-head">
        <h1>Orders Waiting</h1>
        <div className="admin-page-head-controls">
          <select className="form-control admin-control-sm" value={only} onChange={(e) => setOnly(e.target.value)} aria-label="Show">
            <option value="waiting">Only orders still waiting</option>
            <option value="all">All open orders</option>
          </select>
          <Link className="btn btn-outline dark" to="/admin/stock/add">+ Add plants I made</Link>
        </div>
      </div>
      <StockHelp
        id="orders-waiting"
        steps={[
          "Each row is an order that still needs plants. \"In stock\" is how many plants are ready for it.",
          "Press \"Give from stock\" to give plants from the stock (you can change the number).",
          "No plants in stock? Press \"We will prepare\". The customer is told we are preparing the order.",
        ]}
      />
      {error && <div className="alert alert-error">{error}</div>}
      {msg && <div className="alert alert-success" role="status">{msg}</div>}
      {!items && !error ? <Loading /> : shown.length === 0 ? <Empty>No order is waiting for plants. 🎉</Empty> : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead><tr><th>Order</th><th>Customer</th><th>Plant</th><th>Ordered</th><th>Given</th><th>Waiting</th><th>In stock</th><th>What do you want to do?</th></tr></thead>
            <tbody>
              {shown.map((r) => {
                const key = `${r.kind}-${r.item_id}`;
                const inStock = ready[`${r.plant_id}:${r.variant_id || 0}`];
                const give = Math.min(r.pending, inStock ?? 0);
                const typed = qty[key];
                const wanted = typed === undefined || typed === "" ? give : Number(typed);
                const valid = wanted >= 1 && wanted <= r.pending && (inStock == null || wanted <= inStock);
                return (
                  <tr key={key}>
                    <td><Link to={r.link}><strong>{r.number}</strong></Link></td>
                    <td>{r.customer || "-"}</td>
                    <td>{r.plant}</td>
                    <td>{num(r.ordered)}</td>
                    <td>{num(r.allocated)}</td>
                    <td><strong>{num(r.pending)}</strong></td>
                    <td>{inStock == null ? "-" : num(inStock)}</td>
                    <td>
                      {r.pending > 0 ? (
                        <div className="fulfil-actions">
                          <input className="form-control fulfil-qty" inputMode="numeric" aria-label={`Plants to give to ${r.number}`} value={typed === undefined ? String(give || "") : typed} onChange={(e) => setQty((q) => ({ ...q, [key]: sanitizeQuantityText(e.target.value) }))} />
                          <button type="button" className="btn btn-sm btn-primary" disabled={busy === key || !valid} onClick={() => act(r, "stock", wanted)}>Give from stock</button>
                          {r.to_prepare ? <span className="badge badge-gold">We will prepare</span> : <button type="button" className="btn btn-sm btn-outline dark" disabled={busy === key} onClick={() => act(r, "prepare")}>We will prepare</button>}
                        </div>
                      ) : <span className="badge badge-accent">All given</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
