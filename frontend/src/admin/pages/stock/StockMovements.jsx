import { useEffect, useState } from "react";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import { formatIst } from "../../communications/time";
import { MOVEMENT_LABEL, StockHelp, num } from "../../stock/stockUi";

// The full history: every time plants or seeds went up or down, who did it and why.
export default function StockMovements() {
  const [kind, setKind] = useState("all");
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setItems(null);
    api.get(`/admin/stock/movements?kind=${kind}&limit=200`).then((d) => setItems(d.items)).catch((e) => setError(e.message || "Could not load the history."));
  }, [kind]);

  return (
    <div>
      <div className="admin-page-head">
        <h1>Stock Movements (history)</h1>
        <div className="admin-page-head-controls">
          <select className="form-control admin-control-sm" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Show">
            <option value="all">Plants and seeds</option>
            <option value="stock">Only ready plants</option>
            <option value="seed">Only seeds</option>
          </select>
        </div>
      </div>
      <StockHelp
        id="movements"
        steps={[
          "Every change in plants or seeds is written here, newest first. Nothing is ever erased.",
          "\"Before → After\" shows the stock number before and after that change.",
          "To find a problem, look for the plant and read what happened in order.",
        ]}
      />
      {error && <div className="alert alert-error">{error}</div>}
      {!items && !error ? <Loading /> : items.length === 0 ? <Empty>No movements yet.</Empty> : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead><tr><th>When</th><th>What</th><th>Item</th><th>How many</th><th>Before → After</th><th>Done by</th><th>Note</th></tr></thead>
            <tbody>
              {items.map((m, i) => (
                <tr key={`${m.kind}-${m.at}-${i}`}>
                  <td>{formatIst(m.at)}</td>
                  <td>{MOVEMENT_LABEL[m.type] || m.type}<br /><small className="dl-none">{m.kind === "seeds" ? "seeds" : "plants"}</small></td>
                  <td>{m.item}</td>
                  <td><strong>{num(m.quantity)}</strong></td>
                  <td>{num(m.before)} → {num(m.after)}</td>
                  <td>{m.by || "system"}</td>
                  <td>{m.notes || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
