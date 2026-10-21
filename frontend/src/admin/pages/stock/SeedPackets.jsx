import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../api";
import { qtyText, useSupplyMeta } from "../../accounting/supplyCommon";
import { num } from "../../stock/stockUi";

const newId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
const today = () => new Date().toISOString().slice(0, 10);
const fmtDate = (v) => (v ? new Date(`${v}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "-");
const fmtTime = (v) => new Date(v).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const money = (n) => (n == null ? "-" : `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);
const TYPE_LABEL = { RECEIPT: "Received", USAGE: "Used", ADJUSTMENT: "Adjusted", EXPIRED_WRITEOFF: "Written off", CORRECTION: "Corrected" };
const BADGE = { OK: "sp-ok", "Expiring soon": "sp-soon", Expired: "sp-expired", Empty: "sp-empty" };

function daysText(d) {
  if (d == null) return "no expiry";
  if (d < 0) return `expired ${Math.abs(d)} day${Math.abs(d) === 1 ? "" : "s"} ago`;
  if (d === 0) return "expires today";
  return `${d} day${d === 1 ? "" : "s"} left`;
}

export function SeedPacketAlerts({ compact = false, onOpen }) {
  const [data, setData] = useState(null);
  useEffect(() => { api.get("/admin/stock/seed-packets/alerts").then(setData).catch(() => {}); }, []);
  if (!data || data.items.length === 0) return null;
  const shown = compact ? data.items.slice(0, 3) : data.items;
  return (
    <section className="sp-alerts" aria-label="Expiry alerts">
      <div className="sp-alerts-head">
        <strong>{data.expired > 0 ? `${data.expired} expired` : ""}{data.expired > 0 && data.expiring > 0 ? " · " : ""}{data.expiring > 0 ? `${data.expiring} expiring soon` : ""} stock lot{data.items.length === 1 ? "" : "s"}</strong>
        {onOpen && <button type="button" className="btn btn-sm btn-outline dark" onClick={onOpen}>Open packet inventory</button>}
      </div>
      <div className="sp-alert-grid">
        {shown.map((a) => (
          <div key={a.id} className={`sp-alert sp-alert-${a.level}`}>
            <div className="sp-alert-tag">{a.status === "Expired" ? "EXPIRED" : a.level === "critical" ? "HIGH ALERT" : "WARNING"}{a.is_new ? <em>new</em> : null}</div>
            <h4>{a.item_name || a.plant_name}{a.item_kind === "seed_packet" && a.plant_id ? ` · ${a.plant_name}` : ""}</h4>
            <dl>
              <div><dt>Type</dt><dd>{a.kind_label}</dd></div>
              <div><dt>Company</dt><dd>{a.company || "-"}</dd></div>
              <div><dt>Lot</dt><dd>{a.batch_number || "-"}</dd></div>
              <div><dt>Remaining</dt><dd>{num(a.remaining)} {a.quantity_unit}</dd></div>
              <div><dt>Expiry</dt><dd>{fmtDate(a.expiry_date)}</dd></div>
            </dl>
            <p className="sp-days">{daysText(a.days_left)}</p>
          </div>
        ))}
      </div>
      {compact && data.items.length > shown.length && <small className="stock-hint">and {data.items.length - shown.length} more</small>}
    </section>
  );
}

export default function SeedPackets() {
  const [tab, setTab] = useState("inventory");
  const [plants, setPlants] = useState([]);
  const [tick, setTick] = useState(0);
  const [notice, setNotice] = useState("");

  useEffect(() => { api.get("/admin/plants").then(setPlants).catch(() => {}); }, []);
  const refresh = (msg) => { if (msg) setNotice(msg); setTick((t) => t + 1); };

  return (
    <div className="sm sp">
      <div className="sm-head">
        <div className="sm-title">
          <span className="sm-title-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M6 3h12l2 5v13H4V8z" /><path d="M4 8h16M9 12h6" /></svg>
          </span>
          <div>
            <h1>Seed Packet Stock</h1>
            <p>Seed packets, medicines, fertilizers and supplies: lot, expiry, usage and history. New stock comes in through Purchase Orders. Separate from plant stock.</p>
          </div>
        </div>
        <div className="sm-head-actions"><Link className="btn btn-primary sm-new" to="/admin/accounting/purchase-orders">+ New Purchase Order</Link></div>
      </div>
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      <SeedPacketAlerts key={tick} onOpen={() => setTab("inventory")} />
      <div className="sm-filters" role="tablist" aria-label="Packet sections">
        {[["inventory", "Packet Inventory"], ["history", "Packet History"]].map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} className={`sm-chip${tab === key ? " active" : ""}`} onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>
      {tab === "inventory" && <Inventory plants={plants} tick={tick} onChanged={refresh} />}
      {tab === "history" && <History tick={tick} />}
    </div>
  );
}

function Inventory({ plants, tick, onChanged }) {
  const { meta, whole } = useSupplyMeta();
  const [data, setData] = useState(null);
  const [f, setF] = useState({ q: "", plant_id: "", kind: "", company: "", supplier: "", batch: "", expiry: "all", show_empty: false });
  const [act, setAct] = useState(null); // { kind, row, ...fields }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const t = setTimeout(() => {
      const qs = new URLSearchParams({ expiry: f.expiry, show_empty: String(f.show_empty) });
      ["q", "plant_id", "kind", "company", "supplier", "batch"].forEach((key) => f[key] && qs.set(key, f[key]));
      api.get(`/admin/stock/seed-packets?${qs}`).then(setData).catch((e) => setError(e.message || "Could not load the stock."));
    }, 200);
    return () => clearTimeout(t);
  }, [f, tick]);

  async function submit(e) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    const id = newId();
    const b = `/admin/stock/seed-packets/${act.row.id}`;
    try {
      if (act.kind === "use") await api.post(`${b}/use`, { quantity: Number(act.qty), reason: act.reason || "Used for sowing", allow_expired: act.row.status === "Expired", request_id: id });
      if (act.kind === "adjust") await api.post(`${b}/adjust`, { new_remaining: Number(act.count), reason: act.reason, request_id: id });
      if (act.kind === "correct") await api.post(`${b}/correct`, { expiry_date: act.expiry || null, batch_number: act.batch, storage_location: act.storage, reason: act.reason, request_id: id });
      if (act.kind === "writeoff") await api.post(`${b}/write-off`, { reason: act.reason || "Expired: discarded", request_id: id });
      setAct(null);
      onChanged(`${act.row.record_no} updated.`);
    } catch (err) {
      setError(err.message || "Could not save.");
    } finally {
      setBusy(false);
    }
  }
  const setFilter = (key) => (e) => setF({ ...f, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const t = data?.totals;
  const open = (kind, row) => { setError(""); setAct({ kind, row, qty: "", count: String(row.remaining), reason: "", expiry: row.expiry_date || "", batch: row.batch_number, storage: row.storage_location }); };
  const u = act?.row?.quantity_unit || "packets";

  return (
    <section>
      {t && (
        <div className="sp-kpis">
          <div><span>{num(t.batches)}</span>Active lots</div>
          <div className={t.expiring_soon ? "warn" : ""}><span>{num(t.expiring_soon)}</span>Expiring soon</div>
          <div className={t.expired ? "bad" : ""}><span>{num(t.expired)}</span>Expired</div>
        </div>
      )}
      <div className="sp-filters">
        <input className="form-control" placeholder="Search item, plant, company, lot..." value={f.q} onChange={setFilter("q")} aria-label="Search stock" />
        <select className="form-control" value={f.kind} onChange={setFilter("kind")} aria-label="Item type"><option value="">All item types</option>{meta.kinds.map((x) => (<option key={x.key} value={x.key}>{x.label}</option>))}</select>
        <select className="form-control" value={f.plant_id} onChange={setFilter("plant_id")} aria-label="Plant"><option value="">All plants</option>{plants.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
        <input className="form-control" placeholder="Company" value={f.company} onChange={setFilter("company")} aria-label="Company" />
        <input className="form-control" placeholder="Supplier" value={f.supplier} onChange={setFilter("supplier")} aria-label="Supplier" />
        <input className="form-control" placeholder="Lot" value={f.batch} onChange={setFilter("batch")} aria-label="Lot" />
        <select className="form-control" value={f.expiry} onChange={setFilter("expiry")} aria-label="Expiry status">
          <option value="all">All expiry status</option><option value="ok">OK</option><option value="soon">Expiring soon</option><option value="expired">Expired</option><option value="empty">Empty (finished)</option>
        </select>
        <label className="sp-check"><input type="checkbox" checked={f.show_empty} onChange={setFilter("show_empty")} /> Show finished lots</label>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {act && (
        <form className="seed-form seed-edit" onSubmit={submit}>
          <h4>{{ use: "Use stock", adjust: "Correct the count", correct: "Correct lot details", writeoff: "Write off what is left" }[act.kind]}: {act.row.item_name || act.row.plant_name}, lot {act.row.batch_number || "-"}</h4>
          {act.kind === "use" && (
            <>
              {act.row.status === "Expired" && <p className="sp-problem">This lot is expired. Using it is an exception and will be recorded with your reason.</p>}
              <label>Quantity used in {u} (left: {num(act.row.remaining)})<input className="form-control" required inputMode={whole(u) ? "numeric" : "decimal"} value={act.qty} onChange={(e) => setAct({ ...act, qty: whole(u) ? e.target.value.replace(/\D/g, "") : qtyText(e.target.value) })} /></label>
              <label>{act.row.status === "Expired" ? "Reason for using expired stock *" : "Used for (optional)"}<input className="form-control" required={act.row.status === "Expired"} minLength={act.row.status === "Expired" ? 5 : 0} value={act.reason} onChange={(e) => setAct({ ...act, reason: e.target.value })} /></label>
            </>
          )}
          {act.kind === "adjust" && (
            <>
              <label>{u} really left after counting<input className="form-control" required inputMode={whole(u) ? "numeric" : "decimal"} value={act.count} onChange={(e) => setAct({ ...act, count: whole(u) ? e.target.value.replace(/\D/g, "") : qtyText(e.target.value) })} /></label>
              <label>Why is it different? *<input className="form-control" required minLength={3} value={act.reason} onChange={(e) => setAct({ ...act, reason: e.target.value })} /></label>
            </>
          )}
          {act.kind === "correct" && (
            <>
              <label>Expiry date<input className="form-control" type="date" value={act.expiry} onChange={(e) => setAct({ ...act, expiry: e.target.value })} /></label>
              <label>Lot number<input className="form-control" maxLength={80} value={act.batch} onChange={(e) => setAct({ ...act, batch: e.target.value })} /></label>
              <label>Storage location<input className="form-control" maxLength={120} value={act.storage} onChange={(e) => setAct({ ...act, storage: e.target.value })} /></label>
              <label>What was wrong? *<input className="form-control" required minLength={3} value={act.reason} onChange={(e) => setAct({ ...act, reason: e.target.value })} /></label>
              <p className="stock-hint">The old value is kept in Packet History.</p>
            </>
          )}
          {act.kind === "writeoff" && (
            <>
              <p className="stock-hint">All {num(act.row.remaining)} {u} left will be removed from stock. They stay in the history.</p>
              <label>Reason *<input className="form-control" required minLength={3} value={act.reason || "Expired: discarded"} onChange={(e) => setAct({ ...act, reason: e.target.value })} /></label>
            </>
          )}
          <div><button className="btn btn-primary" disabled={busy}>{busy ? "Saving..." : "Save"}</button>{" "}<button type="button" className="btn btn-outline dark" onClick={() => setAct(null)}>Cancel</button></div>
        </form>
      )}
      {data && data.items.length === 0 ? <p className="stock-hint">Nothing here yet. Stock is added when a Purchase Order is converted to a bill.</p> : data && (
        <div className="admin-table-wrap">
          <table className="admin-table sp-table">
            <thead><tr><th>Item</th><th>Plant</th><th>Company</th><th>Lot</th><th className="num">Received</th><th className="num">Used</th><th className="num">Remaining</th><th>Purchased</th><th>Expiry</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>
              {data.items.map((r) => (
                <tr key={r.id} className={r.status === "Expired" ? "sp-row-expired" : r.status === "Expiring soon" ? "sp-row-soon" : ""}>
                  <td><strong>{r.item_name || r.plant_name}</strong><small>{r.kind_label} · {r.record_no}{r.supplier ? ` · ${r.supplier}` : ""}</small></td>
                  <td>{r.plant_id ? <Link to={`/admin/plants/${r.plant_id}/history`}>{r.plant_name}</Link> : <span className="stock-hint" style={{ margin: 0 }}>{r.item_kind === "seed_packet" ? "Unassigned" : "-"}</span>}</td>
                  <td>{r.company || "-"}</td>
                  <td>{r.batch_number || "-"}{r.storage_location && <small>{r.storage_location}</small>}</td>
                  <td className="num">{num(r.received)} <small>{r.quantity_unit}</small></td>
                  <td className="num">{num(r.used)}{r.adjusted !== 0 || r.written_off > 0 ? <small>{r.adjusted !== 0 ? `adj ${r.adjusted > 0 ? "+" : ""}${r.adjusted}` : ""}{r.written_off > 0 ? ` off ${r.written_off}` : ""}</small> : null}</td>
                  <td className="num"><strong>{num(r.remaining)}</strong> <small>{r.quantity_unit}</small></td>
                  <td>{fmtDate(r.purchase_date)}</td>
                  <td>{r.expiry_date ? fmtDate(r.expiry_date) : <span className="stock-hint" style={{ margin: 0 }}>No expiry</span>}<small>{r.status === "Empty" || !r.expiry_date ? "" : daysText(r.days_left)}</small></td>
                  <td><span className={`sp-badge ${BADGE[r.status]}`}>{r.status}</span></td>
                  <td>
                    <div className="sm-actions">
                      {r.remaining > 0 && <button type="button" className="btn btn-sm btn-outline dark" onClick={() => open("use", r)}>Use</button>}
                      <details className="sm-menu" onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) e.currentTarget.removeAttribute("open"); }}>
                        <summary className="sm-more" aria-label="More actions">⋯</summary>
                        <div className="sm-menu-list">
                          <button type="button" onClick={() => open("adjust", r)}>Correct count</button>
                          <button type="button" onClick={() => open("correct", r)}>Correct details</button>
                          {r.remaining > 0 && <button type="button" onClick={() => open("writeoff", r)}>Write off</button>}
                        </div>
                      </details>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function History({ tick }) {
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState("");
  useEffect(() => {
    const t = setTimeout(() => api.get(`/admin/stock/seed-packets/history${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`).then(setRows).catch(() => setRows([])), 200);
    return () => clearTimeout(t);
  }, [q, tick]);
  return (
    <section>
      <div className="sp-filters"><input className="form-control" placeholder="Search item, plant, company, lot, bill number, reason or person..." value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search history" /></div>
      {!rows ? null : rows.length === 0 ? <p className="stock-hint">No history yet.</p> : (
        <div className="admin-table-wrap">
          <table className="admin-table sp-table">
            <thead><tr><th>When</th><th>What</th><th>Item / lot</th><th className="num">Quantity</th><th>Reason / details</th><th>By</th></tr></thead>
            <tbody>
              {rows.map((h) => (
                <tr key={h.id}>
                  <td>{fmtTime(h.at)}</td>
                  <td><span className={`sp-type sp-type-${h.type.toLowerCase()}`}>{TYPE_LABEL[h.type] || h.type}</span>{h.is_exception && <small className="sp-problem">expired exception</small>}</td>
                  <td><strong>{h.item_name || h.plant_name}</strong>{h.item_kind === "seed_packet" && h.plant_name && h.item_name ? ` · ${h.plant_name}` : ""}<small>{h.company ? `${h.company} · ` : ""}lot {h.batch_number || "-"} · {h.record_no}</small></td>
                  <td className="num">{h.quantity > 0 ? `+${num(h.quantity)}` : h.quantity < 0 ? `−${num(Math.abs(h.quantity))}` : "-"} {h.quantity ? <small>{h.unit}</small> : null}</td>
                  <td>{h.reason}{h.detail && <small>{h.detail}</small>}{h.type === "RECEIPT" && (h.invoice_number || h.supplier || h.total_amount) ? <small>{h.supplier}{h.invoice_number ? ` · bill ${h.invoice_number}` : ""}{h.total_amount ? ` · ${money(h.total_amount)}` : ""}{h.purchase_id ? <> · <Link to={`/admin/accounting/bills/${h.purchase_id}`}>open bill</Link></> : ""}{h.expense_id ? " · in Expenses" : ""}</small> : null}</td>
                  <td>{h.by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
