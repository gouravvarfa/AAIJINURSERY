import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";
import { StockHelp, num } from "../stock/stockUi";

// Stock Overview: ready plants vs. what customers have ordered, in plain words,
// with one clear "what to do" per plant. Website orders and offline Sales
// Orders are counted once (never the mirror Sales Order of a website order).
function advice(r) {
  if (r.to_produce > 0)
    return { text: `Make ${num(r.to_produce)} more ${r.unit}`, to: `/admin/stock/batches?plant=${r.plant_id}&variant=${r.variant_id || ""}`, action: "Start a batch", tone: "red" };
  if (r.undecided > 0 && r.available_stock > 0)
    return { text: "Ready plants can go to waiting orders", to: "/admin/stock/allocations", action: "See the orders", tone: "orange" };
  if (r.in_production > 0) return { text: "A batch is already making them", to: "/admin/stock/batches", action: "See batches", tone: "orange" };
  if (r.outstanding_demand > 0) return { text: "Orders are being prepared by the nursery", tone: "orange" };
  return { text: "All good", tone: "green" };
}

export default function StockDemand() {
  const [data, setData] = useState(null);
  const [onlyAction, setOnlyAction] = useState(false);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");

  function load() {
    setError("");
    api.get("/admin/inventory/stock-demand").then(setData).catch((err) => setError(err.message || "Could not load the stock."));
  }
  useEffect(load, []);

  const rows = (data?.items || []).filter((r) => (!onlyAction || advice(r).tone !== "green") && (!q || r.name.toLowerCase().includes(q.toLowerCase())));
  return (
    <div>
      <div className="admin-page-head">
        <h1>Stock Overview</h1>
        <div className="admin-page-head-controls">
          <input className="form-control admin-control-sm" placeholder="Search a plant..." value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search plants" />
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={onlyAction} onChange={(e) => setOnlyAction(e.target.checked)} />
            Only plants that need action
          </label>
          <button type="button" className="btn btn-outline dark" onClick={load}>Refresh</button>
        </div>
      </div>
      <StockHelp
        id="overview"
        title="How to read this page"
        steps={[
          "\"Ready now\" = plants you can sell today. \"Waiting orders need\" = what customers ordered and still has not been given.",
          "\"Being made\" = plants in a batch that is not finished. They are NOT counted as ready.",
          "\"Still to make\" = Waiting orders need − Ready now − Being made. This is the number to put in a new batch.",
          "The last column tells you what to do. Follow it from top to bottom.",
        ]}
        note="Seeds are on the Seeds page. Ready plants come only from finished batches or purchases."
      />
      {error && <div className="alert alert-error">{error}</div>}
      {!data && !error ? <Loading /> : data ? (
        <>
          <div className="stock-kpis">
            <div><span>Waiting orders need</span><strong>{num(data.totals.outstanding_demand)}</strong></div>
            <div><span>Being made now</span><strong>{num(data.totals.in_production)}</strong></div>
            <div className={data.totals.to_produce ? "alert-red" : ""}><span>Still to make</span><strong>{num(data.totals.to_produce)}</strong></div>
          </div>
          {rows.length === 0 ? <Empty>{onlyAction ? "Nothing needs action right now." : "No plants found."}</Empty> : (
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr><th>Plant</th><th>Ready now</th><th>Given to orders</th><th>Waiting orders need</th><th>Being made</th><th>Still to make</th><th>What to do</th></tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const a = advice(r);
                    return (
                      <tr key={`${r.plant_id}-${r.variant_id || 0}`}>
                        <td><strong>{r.name}</strong></td>
                        <td>{num(r.available_stock)}</td>
                        <td>{num(r.reserved_stock)}</td>
                        <td>{num(r.outstanding_demand)}</td>
                        <td>{num(r.in_production)}</td>
                        <td>{r.to_produce > 0 ? <span className="dl-pill dl-red"><span className="dl-label">{num(r.to_produce)}</span></span> : "-"}</td>
                        <td>
                          <span className={`stock-advice stock-advice-${a.tone}`}>{a.text}</span>
                          {a.to && <> <Link className="btn btn-sm btn-outline dark" to={a.to}>{a.action}</Link></>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <p className="stock-hint">{data.note}</p>
        </>
      ) : null}
    </div>
  );
}
