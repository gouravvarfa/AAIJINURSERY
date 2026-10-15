import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import { StockHelp, num } from "../../stock/stockUi";

// Which orders are waiting for plants, and which plants are already promised.
export default function StockAllocations() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [only, setOnly] = useState("");

  useEffect(() => {
    api.get("/admin/stock/allocations").then((d) => setItems(d.items)).catch((e) => setError(e.message || "Could not load the orders."));
  }, []);

  const shown = (items || []).filter((r) => (only === "waiting" ? r.pending > 0 : only === "given" ? r.allocated > 0 : true));
  const state = (r) => (r.pending === 0 ? ["Fully given from stock", "badge-accent"] : r.to_prepare ? ["Nursery will prepare", "badge-gold"] : r.allocated > 0 ? ["Partly given, rest waiting", "badge-muted"] : ["Waiting, not decided", "badge-muted"]);
  return (
    <div>
      <div className="admin-page-head">
        <h1>Orders &amp; Allocations</h1>
        <div className="admin-page-head-controls">
          <select className="form-control admin-control-sm" value={only} onChange={(e) => setOnly(e.target.value)} aria-label="Show">
            <option value="">All open orders</option>
            <option value="waiting">Only orders waiting for plants</option>
            <option value="given">Only orders that got plants</option>
          </select>
        </div>
      </div>
      <StockHelp
        id="allocations"
        steps={[
          "\"Ordered\" is what the customer asked for.",
          "\"Given from stock\" plants are set aside for that order.",
          "\"Waiting\" is the rest. Open the order and press \"Give from stock\", or \"Nursery will prepare\".",
          "Delivered and cancelled orders are not shown here.",
        ]}
      />
      {error && <div className="alert alert-error">{error}</div>}
      {!items && !error ? <Loading /> : shown.length === 0 ? <Empty>Nothing here. No order is waiting for plants.</Empty> : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead><tr><th>Order</th><th>Customer</th><th>Plant</th><th>Ordered</th><th>Given from stock</th><th>Waiting</th><th>Where it stands</th><th /></tr></thead>
            <tbody>
              {shown.map((r) => {
                const [label, badge] = state(r);
                return (
                  <tr key={`${r.kind}-${r.item_id}`}>
                    <td><strong>{r.number}</strong></td><td>{r.customer || "-"}</td><td>{r.plant}</td>
                    <td>{num(r.ordered)}</td><td>{num(r.allocated)}</td><td><strong>{num(r.pending)}</strong></td>
                    <td><span className={`badge ${badge}`}>{label}</span></td>
                    <td><Link className="btn btn-sm btn-outline dark" to={r.link}>Open</Link></td>
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
