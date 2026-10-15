import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";
import { StockHelp, num } from "../stock/stockUi";
import SeedEntries from "./stock/SeedEntries";
import { sanitizeQuantityText } from "../../utils/quantity";

// Stock: how many plants are ready, how many orders are waiting, and what to do.
function advice(r) {
  const make = r.to_produce > 0 ? { to: `/admin/stock/add?plant=${r.plant_id}&variant=${r.variant_id || ""}`, action: "Add plants" } : null;
  if (r.outstanding_demand > 0 && r.available_stock > 0) {
    return { text: r.to_produce > 0 ? `Give the ready plants to the waiting orders, then make ${num(r.to_produce)} more ${r.unit}` : "Give the ready plants to the waiting orders", tone: r.to_produce > 0 ? "red" : "orange", to: "/admin/stock/allocations", action: "Give to orders", make };
  }
  if (r.to_produce > 0) return { text: `Make ${num(r.to_produce)} more ${r.unit}`, tone: "red", ...make, make: null };
  if (r.outstanding_demand > 0) return { text: "Orders are waiting for the nursery", tone: "orange" };
  return { text: "All good", tone: "green" };
}

export default function StockDemand() {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [onlyAction, setOnlyAction] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [fix, setFix] = useState(null);
  const [count, setCount] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [plants, setPlants] = useState([]);

  useEffect(() => { api.get("/admin/plants").then(setPlants).catch(() => {}); }, []);

  function load() {
    setError("");
    api.get("/admin/inventory/stock-demand").then(setData).catch((err) => setError(err.message || "Could not load the stock."));
  }
  useEffect(load, []);

  async function saveCount(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api.post("/admin/stock/ready/adjust", { plant_id: fix.plant_id, variant_id: fix.variant_id, new_quantity: Number(count), reason });
      setMsg(r.changed_by === 0 ? "The count was already correct." : `Done. Ready stock changed by ${r.changed_by > 0 ? "+" : ""}${r.changed_by}.`);
      setFix(null);
      load();
    } catch (err) {
      setError(err.message || "Could not save the count.");
    } finally {
      setBusy(false);
    }
  }

  const rows = (data?.items || []).filter((r) => (!onlyAction || advice(r).tone !== "green") && (!q || r.name.toLowerCase().includes(q.toLowerCase())));
  return (
    <div>
      <div className="admin-page-head">
        <h1>Stock</h1>
        <div className="admin-page-head-controls">
          <input className="form-control admin-control-sm" placeholder="Search a plant..." value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search plants" />
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={onlyAction} onChange={(e) => setOnlyAction(e.target.checked)} />
            Only plants that need action
          </label>
        </div>
      </div>
      <StockHelp
        id="stock-simple"
        title="How this works (3 easy steps)"
        steps={[
          "Look at this page: \"Ready now\" is what you can sell today. \"Orders waiting\" is what customers asked for.",
          "Plants made? Press \"Add plants\" and write how many came out good. They go into Ready now.",
          "Then open \"Orders Waiting\" and press \"Give from stock\" for each order.",
        ]}
        note={'If your count is different from the real plants in the nursery, press "Correct count" and write why.'}
      />
      {error && <div className="alert alert-error">{error}</div>}
      {msg && <div className="alert alert-success" role="status">{msg}</div>}
      <div className="stock-actions-row">
        <Link className="btn btn-primary" to="/admin/stock/add">+ Add plants I made</Link>
        <Link className="btn btn-outline dark" to="/admin/stock/allocations">Orders waiting for plants</Link>
        <a className="btn btn-outline dark" href="#seed-entries" onClick={(e) => { e.preventDefault(); document.getElementById("seed-entries")?.scrollIntoView({ behavior: "smooth" }); }}>+ New Seed Entry</a>
      </div>
      {!data && !error ? <Loading /> : data ? (
        rows.length === 0 ? <Empty>{onlyAction ? "Nothing needs action right now." : "No plants found."}</Empty> : (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead><tr><th>Plant</th><th>Ready now</th><th>Orders waiting</th><th>Still to make</th><th>What to do</th><th /></tr></thead>
              <tbody>
                {rows.map((r) => {
                  const a = advice(r);
                  return (
                    <tr key={`${r.plant_id}-${r.variant_id || 0}`}>
                      <td><strong>{r.name}</strong></td>
                      <td><strong>{num(r.available_stock)}</strong> {r.unit}</td>
                      <td>{num(r.outstanding_demand)}</td>
                      <td>{r.to_produce > 0 ? <span className="dl-pill dl-red"><span className="dl-label">{num(r.to_produce)}</span></span> : "-"}</td>
                      <td>
                        <span className={`stock-advice stock-advice-${a.tone}`}>{a.text}</span>
                        {a.to && <> <Link className="btn btn-sm btn-outline dark" to={a.to}>{a.action}</Link></>}
                        {a.make && <> <Link className="btn btn-sm btn-outline dark" to={a.make.to}>{a.make.action}</Link></>}
                      </td>
                      <td><button type="button" className="btn btn-sm btn-outline dark" onClick={() => { setFix(r); setCount(String(r.available_stock)); setReason(""); setMsg(""); }}>Correct count</button></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )
      ) : null}
      {fix && (
        <div className="admin-form-card" style={{ maxWidth: 560, marginTop: 20 }}>
          <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Correct count: {fix.name}</h2>
          <form onSubmit={saveCount}>
            <div className="form-group">
              <label htmlFor="fix-count">How many are ready now, after you counted? (the system says {num(fix.available_stock)})</label>
              <input id="fix-count" className="form-control" required inputMode="numeric" value={count} onChange={(e) => setCount(sanitizeQuantityText(e.target.value, 100000000))} autoFocus />
            </div>
            <div className="form-group">
              <label htmlFor="fix-reason">Why is it different? (required)</label>
              <input id="fix-reason" className="form-control" required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. 8 plants dried" />
            </div>
            <button className="btn btn-primary" disabled={busy || count === "" || reason.trim().length < 3}>{busy ? "Saving..." : "Save"}</button>{" "}
            <button type="button" className="btn btn-outline dark" onClick={() => setFix(null)}>Cancel</button>
          </form>
        </div>
      )}
      <div id="seed-entries"><SeedEntries plants={plants} onChanged={load} /></div>
    </div>
  );
}
