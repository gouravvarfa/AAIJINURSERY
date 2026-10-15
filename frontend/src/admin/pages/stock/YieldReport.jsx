import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import { formatIst } from "../../communications/time";
import { StockHelp, num } from "../../stock/stockUi";

const pct = (v) => (v === null || v === undefined ? "-" : `${v}%`);

// How many seeds really became healthy plants, and how many were lost.
export default function YieldReport() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.get("/admin/stock/reports/yield").then(setData).catch((e) => setError(e.message || "Could not load the report."));
  }, []);
  return (
    <div>
      <div className="admin-page-head"><h1>Yield &amp; Wastage</h1></div>
      <StockHelp
        id="yield"
        steps={[
          "Yield % = healthy plants ÷ seeds used. If you used 1000 seeds and got 800 healthy plants, the yield is 80%.",
          "Use it to plan seeds: for 1000 plants at 80% yield you need about 1250 seeds.",
          "Only finished batches are counted here.",
        ]}
      />
      {error && <div className="alert alert-error">{error}</div>}
      {!data && !error ? <Loading /> : data.batches.length === 0 ? <Empty>No finished batch yet. Finish a batch and its numbers will appear here.</Empty> : (
        <>
          <h2 style={{ fontSize: "1.1rem" }}>By plant</h2>
          <div className="admin-table-wrap" style={{ marginBottom: 24 }}>
            <table className="admin-table">
              <thead><tr><th>Plant</th><th>Batches</th><th>Seeds used</th><th>Healthy plants</th><th>Rejected</th><th>Seeds spoiled</th><th>Yield</th></tr></thead>
              <tbody>
                {data.by_plant.map((p) => (
                  <tr key={p.plant}><td><strong>{p.plant}</strong></td><td>{p.batches}</td><td>{num(p.seeds_consumed)}</td><td>{num(p.healthy)}</td><td>{num(p.rejected)}</td><td>{num(p.seeds_wasted)}</td><td><strong>{pct(p.yield_pct)}</strong></td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <h2 style={{ fontSize: "1.1rem" }}>Each batch</h2>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead><tr><th>Batch</th><th>Plant</th><th>Finished</th><th>Seeds used</th><th>Healthy</th><th>Rejected</th><th>Accepted</th><th>Yield</th></tr></thead>
              <tbody>
                {data.batches.map((b) => (
                  <tr key={b.id}>
                    <td><Link to={`/admin/stock/batches/${b.id}`}>{b.batch_number}</Link></td><td>{b.plant_name}</td><td>{formatIst(b.completed_at)}</td>
                    <td>{num(b.seeds_consumed)}</td><td>{num(b.healthy_plants)}</td><td>{num(b.rejected_plants)}</td><td>{num(b.accepted_plants)}</td><td><strong>{pct(b.yield_pct)}</strong></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
