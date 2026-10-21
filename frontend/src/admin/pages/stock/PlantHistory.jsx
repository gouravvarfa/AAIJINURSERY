import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../../api";
import { num } from "../../stock/stockUi";

const fmtDate = (v) => (v ? new Date(`${String(v).slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "-");
const fmtTime = (v) => new Date(v).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const money = (n) => (n == null ? "-" : `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);
const TYPE_LABEL = { RECEIPT: "Received", USAGE: "Used", ADJUSTMENT: "Adjusted", EXPIRED_WRITEOFF: "Written off", CORRECTION: "Corrected" };

export default function PlantHistory() {
  const { id } = useParams();
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { api.get(`/admin/plants/${id}/history`).then(setD).catch((e) => setError(e.message || "Could not load.")); }, [id]);
  if (error) return <div className="sm"><div className="alert alert-error">{error}</div></div>;
  if (!d) return <div className="sm"><p className="stock-hint">Loading...</p></div>;
  const { plant, packets, packet_totals: t } = d;

  return (
    <div className="sm sp">
      <div className="sm-head">
        <div className="sm-title">
          <div>
            <h1>{plant.name}: history</h1>
            <p>Ready plants {num(plant.ready_stock)} · {plant.is_active ? "Active on website" : "Inactive (not on website)"} · Seed packets are counted separately from plant stock.</p>
          </div>
        </div>
        <div className="sm-head-actions"><Link className="btn btn-outline dark" to="/admin/stock/packets">Seed Packet Entry</Link></div>
      </div>

      <div className="sp-kpis">
        <div><span>{num(t.lots)}</span>Packet lots</div>
        <div><span>{num(t.remaining_lots)}</span>With stock left</div>
        <div className={t.expired ? "bad" : ""}><span>{num(t.expired)}</span>Expired</div>
      </div>

      <h3>Seed packets for this plant</h3>
      {packets.length === 0 ? <p className="stock-hint">No seed packets are linked to this plant yet.</p> : (
        <div className="admin-table-wrap">
          <table className="admin-table sp-table">
            <thead><tr><th>Item / company</th><th>Lot</th><th>Supplier · bill</th><th>Purchased</th><th className="num">Received</th><th className="num">Remaining</th><th>Expiry</th><th>Status</th></tr></thead>
            <tbody>
              {packets.map((r) => (
                <tr key={r.id}>
                  <td><strong>{r.item_name || r.plant_name}</strong><small>{r.company || "-"} · {r.record_no}</small></td>
                  <td>{r.batch_number || "-"}</td>
                  <td>{r.receipts.length === 0 ? (r.supplier || "-") : r.receipts.map((x, i) => (
                    <div key={i}>{x.supplier || "-"}{x.bill_number ? ` · bill ${x.bill_number}` : ""}{x.purchase_id ? <> · <Link to={`/admin/accounting/bills/${x.purchase_id}`}>open</Link></> : ""}</div>
                  ))}</td>
                  <td>{fmtDate(r.purchase_date)}</td>
                  <td className="num">{num(r.received)} <small>{r.quantity_unit}</small></td>
                  <td className="num"><strong>{num(r.remaining)}</strong> <small>{r.quantity_unit}</small></td>
                  <td>{r.expiry_date ? fmtDate(r.expiry_date) : "No expiry"}</td>
                  <td>{r.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3>Packet movements</h3>
      {d.packet_movements.length === 0 ? <p className="stock-hint">No packet movements yet.</p> : (
        <div className="admin-table-wrap">
          <table className="admin-table sp-table">
            <thead><tr><th>When</th><th>What</th><th>Lot</th><th className="num">Quantity</th><th>Reason</th><th>By</th></tr></thead>
            <tbody>
              {d.packet_movements.map((h) => (
                <tr key={h.id}>
                  <td>{fmtTime(h.at)}</td>
                  <td>{TYPE_LABEL[h.type] || h.type}</td>
                  <td>{h.batch_number || "-"}</td>
                  <td className="num">{h.quantity > 0 ? `+${num(h.quantity)}` : h.quantity < 0 ? `−${num(Math.abs(h.quantity))}` : "-"} {h.quantity ? <small>{h.unit}</small> : null}</td>
                  <td>{h.reason}</td>
                  <td>{h.by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3>Ready plant stock movements</h3>
      {d.stock_movements.length === 0 ? <p className="stock-hint">No plant stock movements yet.</p> : (
        <div className="admin-table-wrap">
          <table className="admin-table sp-table">
            <thead><tr><th>When</th><th>Type</th><th className="num">Quantity</th><th className="num">Before → After</th><th>Source</th><th>By</th></tr></thead>
            <tbody>
              {d.stock_movements.map((s) => (
                <tr key={s.id}><td>{fmtTime(s.at)}</td><td>{s.type}</td><td className="num">{num(s.quantity)}</td><td className="num">{num(s.before)} → {num(s.after)}</td><td>{s.source || "-"}{s.notes && <small>{s.notes}</small>}</td><td>{s.by || "-"}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {d.plant_purchases.length > 0 && (
        <>
          <h3>Plant purchases</h3>
          <div className="admin-table-wrap">
            <table className="admin-table sp-table">
              <thead><tr><th>Date</th><th>Supplier</th><th>Bill</th><th className="num">Quantity</th><th className="num">Cost</th></tr></thead>
              <tbody>{d.plant_purchases.map((p) => (<tr key={p.purchase_id}><td>{fmtDate(p.date)}</td><td>{p.supplier || "-"}</td><td>{p.bill_number || "-"}</td><td className="num">{num(p.quantity)}</td><td className="num">{money(p.total_cost)}</td></tr>))}</tbody>
            </table>
          </div>
        </>
      )}

      {d.customer_seeds.length > 0 && (
        <>
          <h3>Customer seeds</h3>
          <div className="admin-table-wrap">
            <table className="admin-table sp-table">
              <thead><tr><th>Entry</th><th>Customer</th><th>Date</th><th className="num">Seeds</th><th className="num">Good plants</th><th>Status</th></tr></thead>
              <tbody>{d.customer_seeds.map((e) => (<tr key={e.id}><td>{e.entry_number}</td><td>{e.customer}</td><td>{fmtDate(e.date)}</td><td className="num">{num(e.seeds_given)}</td><td className="num">{num(e.good_for_customer)}</td><td>{e.status}</td></tr>))}</tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
