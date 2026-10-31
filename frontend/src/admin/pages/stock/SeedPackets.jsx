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
        {[["inventory", "Packet Inventory"], ["sowing", "Sowing Entry"], ["history", "Stock History"]].map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} className={`sm-chip${tab === key ? " active" : ""}`} onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>
      {tab === "inventory" && <Inventory plants={plants} tick={tick} onChanged={refresh} />}
      {tab === "sowing" && <Sowing tick={tick} onSaved={(msg) => refresh(msg)} />}
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
            <thead><tr><th>When</th><th>What</th><th>Item / lot</th><th className="num">Quantity</th><th className="num">Balance</th><th>Reason / details</th><th>By</th></tr></thead>
            <tbody>
              {rows.map((h) => (
                <tr key={h.id}>
                  <td>{fmtTime(h.at)}</td>
                  <td><span className={`sp-type sp-type-${h.type.toLowerCase()}`}>{TYPE_LABEL[h.type] || h.type}</span>{h.is_exception && <small className="sp-problem">expired exception</small>}</td>
                  <td><strong>{h.item_name || h.plant_name}</strong>{h.item_kind === "seed_packet" && h.plant_name && h.item_name ? ` · ${h.plant_name}` : ""}<small>{h.company ? `${h.company} · ` : ""}lot {h.batch_number || "-"} · {h.record_no}</small></td>
                  <td className="num">{h.quantity > 0 ? `+${num(h.quantity)}` : h.quantity < 0 ? `−${num(Math.abs(h.quantity))}` : "-"} {h.quantity ? <small>{h.unit}</small> : null}</td>
                  <td className="num">{h.balance_after == null ? "-" : num(h.balance_after)}</td>
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

function Sowing({ tick, onSaved }) {
  const blank = () => ({ batch_id: "", sowing_date: today(), packets_used: "", trays_sown: "", nursery_batch_number: "", notes: "", allow_expired: false, expired_reason: "" });
  const [lots, setLots] = useState([]);
  const [rows, setRows] = useState(null);
  const [form, setForm] = useState(blank);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [key, setKey] = useState(newId);

  useEffect(() => { api.get("/admin/stock/seed-packets?kind=seed_packet").then((d) => setLots(d.items)).catch(() => {}); }, [tick]);
  useEffect(() => {
    const t = setTimeout(() => api.get(`/admin/stock/seed-sowings${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`).then(setRows).catch(() => setRows([])), 200);
    return () => clearTimeout(t);
  }, [q, tick]);

  const lot = lots.find((l) => String(l.id) === String(form.batch_id));
  const used = Number(form.packets_used || 0);
  const left = lot ? Math.round((lot.remaining - used) * 1000) / 1000 : null;
  const expired = lot?.status === "Expired";
  const ready = lot && used > 0 && used <= lot.remaining + 1e-9 && Number(form.trays_sown) >= 1 && form.sowing_date && (!expired || (form.allow_expired && form.expired_reason.trim().length >= 5));
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function save(e) {
    e.preventDefault();
    if (busy || !ready) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.post("/admin/stock/seed-sowings", { ...form, batch_id: Number(form.batch_id), packets_used: used, trays_sown: Number(form.trays_sown), request_id: key });
      setForm(blank());
      setKey(newId());
      onSaved(`Saved ${r.record_no}: ${num(r.packets_used)} packets of ${r.item_name} (lot ${r.lot_number || "-"}) sown in ${r.trays_sown} trays. ${num(r.remaining_after)} packets left in the lot.`);
    } catch (err) {
      setError(err.message || "Could not save the sowing.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <form className="sp-form" onSubmit={save}>
        {error && <div className="alert alert-error">{error}</div>}
        <div className="sp-grid">
          <label className="sp-span2">Seed (name, variety, lot) *
            <select className="form-control" value={form.batch_id} onChange={set("batch_id")} required>
              <option value="">Choose the seed lot you used</option>
              {lots.filter((l) => l.remaining > 0).map((l) => (
                <option key={l.id} value={l.id}>{l.item_name || l.plant_name}{l.plant_id && l.item_name ? ` (${l.plant_name})` : ""} · {l.company || "-"} · lot {l.batch_number || "-"} · {num(l.remaining)} {l.quantity_unit} left{l.status === "Expired" ? " · EXPIRED" : ""}</option>
              ))}
            </select>
          </label>
          <label>Sowing date *<input className="form-control" type="date" required max={today()} value={form.sowing_date} onChange={set("sowing_date")} /></label>
          <label>Packets used *<input className="form-control" inputMode="decimal" placeholder="e.g. 3 or 0.5" value={form.packets_used} onChange={(e) => setForm({ ...form, packets_used: qtyText(e.target.value) })} /></label>
          <label>Trays sown *<input className="form-control" inputMode="numeric" value={form.trays_sown} onChange={(e) => setForm({ ...form, trays_sown: e.target.value.replace(/\D/g, "") })} /></label>
          <label>Nursery batch number<input className="form-control" maxLength={80} value={form.nursery_batch_number} onChange={set("nursery_batch_number")} placeholder="Your batch no. for these trays" /></label>
          <label className="sp-wide">Notes<input className="form-control" maxLength={1000} value={form.notes} onChange={set("notes")} /></label>
        </div>
        {lot && <p className="stock-hint">In stock now: <strong>{num(lot.remaining)}</strong> {lot.quantity_unit}.{used > 0 ? <> After this sowing: <strong>{num(Math.max(left, 0))}</strong>.</> : ""} Half a packet is fine: type 0.5.</p>}
        {lot && used > lot.remaining + 1e-9 && <p className="sp-problem">Only {num(lot.remaining)} packets are in stock for this lot.</p>}
        {expired && (
          <div className="alert alert-warning">
            <label className="sp-check"><input type="checkbox" checked={form.allow_expired} onChange={(e) => setForm({ ...form, allow_expired: e.target.checked })} /> This lot is expired. Sow it anyway (recorded as an exception)</label>
            {form.allow_expired && <input className="form-control" placeholder="Reason (required)" value={form.expired_reason} onChange={set("expired_reason")} />}
          </div>
        )}
        <button className="btn btn-primary" disabled={busy || !ready}>{busy ? "Saving..." : "Save sowing"}</button>
      </form>

      <h3 style={{ marginTop: 24 }}>Sowing history</h3>
      <div className="sp-filters"><input className="form-control" placeholder="Search seed, lot, nursery batch..." value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search sowings" /></div>
      {!rows ? null : rows.length === 0 ? <p className="stock-hint">No sowing recorded yet.</p> : (
        <div className="admin-table-wrap">
          <table className="admin-table sp-table">
            <thead><tr><th>Date</th><th>Seed / lot</th><th className="num">Packets used</th><th className="num">Trays</th><th>Nursery batch</th><th className="num">Lot balance</th><th>By</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{fmtDate(r.sowing_date)}<small>{r.record_no}</small></td>
                  <td><strong>{r.item_name}</strong>{r.plant_name && r.plant_name !== r.item_name ? ` · ${r.plant_name}` : ""}<small>{r.company ? `${r.company} · ` : ""}lot {r.lot_number || "-"}</small></td>
                  <td className="num">{num(r.packets_used)}</td>
                  <td className="num">{num(r.trays_sown)}</td>
                  <td>{r.nursery_batch_number || "-"}{r.notes && <small>{r.notes}</small>}</td>
                  <td className="num">{r.remaining_after == null ? "-" : num(r.remaining_after)}</td>
                  <td>{r.by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
