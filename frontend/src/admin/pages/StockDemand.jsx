import { useEffect, useState } from "react";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";

const n = (v) => Number(v || 0).toLocaleString("en-IN");

// Physical stock vs. what customers have ordered. Counts website orders and
// offline Sales Orders once (never the mirror Sales Order of a website order).
export default function StockDemand() {
  const [data, setData] = useState(null);
  const [onlyShortage, setOnlyShortage] = useState(false);
  const [error, setError] = useState("");

  function load() {
    setError("");
    api.get(`/admin/inventory/stock-demand${onlyShortage ? "?only_shortage=true" : ""}`).then(setData).catch((err) => setError(err.message || "Could not load stock and demand."));
  }
  useEffect(load, [onlyShortage]);

  return (
    <div>
      <div className="admin-page-head">
        <h1>Stock &amp; Demand</h1>
        <div className="admin-page-head-controls">
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={onlyShortage} onChange={(e) => setOnlyShortage(e.target.checked)} />
            Only products with a shortage
          </label>
          <button type="button" className="btn btn-outline dark" onClick={load}>Refresh</button>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {!data && !error ? (
        <Loading />
      ) : data ? (
        <>
          <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 28 }}>
              <div><div className="dl-none">Outstanding demand</div><div style={{ fontSize: "1.5rem", fontWeight: 700 }}>{n(data.totals.outstanding_demand)}</div></div>
              <div><div className="dl-none">Not decided yet</div><div style={{ fontSize: "1.5rem", fontWeight: 700 }}>{n(data.totals.undecided)}</div></div>
              <div><div className="dl-none">Nursery to prepare</div><div style={{ fontSize: "1.5rem", fontWeight: 700 }}>{n(data.totals.to_prepare)}</div></div>
              <div><div className="dl-none">Shortage (more than in stock)</div><div style={{ fontSize: "1.5rem", fontWeight: 700, color: data.totals.shortage ? "#b3261e" : undefined }}>{n(data.totals.shortage)}</div></div>
            </div>
            <p style={{ margin: "12px 0 0", color: "var(--color-text-muted)", fontSize: "0.82rem" }}>{data.note}</p>
          </div>
          {data.items.length === 0 ? (
            <Empty>{onlyShortage ? "No product is short right now." : "No products yet."}</Empty>
          ) : (
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th>Physical stock</th>
                    <th>Reserved</th>
                    <th>Available</th>
                    <th>Outstanding demand</th>
                    <th>Not decided</th>
                    <th>To prepare</th>
                    <th>Shortage</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((r) => (
                    <tr key={`${r.plant_id}-${r.variant_id || 0}`}>
                      <td>{r.name}</td>
                      <td>{n(r.physical_stock)}</td>
                      <td>{n(r.reserved_stock)}</td>
                      <td>{n(r.available_stock)}</td>
                      <td>{n(r.outstanding_demand)}</td>
                      <td>{n(r.undecided)}</td>
                      <td>{n(r.to_prepare)}</td>
                      <td>{r.shortage > 0 ? <span className="dl-pill dl-red"><span className="dl-label">{n(r.shortage)}</span></span> : "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
