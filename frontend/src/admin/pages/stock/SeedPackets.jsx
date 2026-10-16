import { useEffect, useRef, useState } from "react";
import { api } from "../../../api";
import SearchSelect from "../../accounting/SearchSelect";
import { sanitizeQuantityText } from "../../../utils/quantity";
import { num } from "../../stock/stockUi";

const newId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
const iso = (d) => d.toISOString().slice(0, 10);
const today = () => iso(new Date());
const fmtDate = (v) => (v ? new Date(`${v}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "-");
const fmtTime = (v) => new Date(v).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const money = (n) => (n == null ? "-" : `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);
const UNITS = ["g", "kg", "mg", "seeds", "pcs"];
const METHODS = ["Cash", "Bank", "UPI", "Card", "Online", "Other"];
const TYPE_LABEL = { RECEIPT: "Received", USAGE: "Used", ADJUSTMENT: "Adjusted", EXPIRED_WRITEOFF: "Written off", CORRECTION: "Corrected" };
const BADGE = { OK: "sp-ok", "Expiring soon": "sp-soon", Expired: "sp-expired", Empty: "sp-empty" };
const EMPTY = {
  plant_id: "", variety: "", company: "", supplier: "", batch_number: "", packets: "", packet_size: "", packet_unit: "g", purchase_date: today(), manufacturing_date: "", expiry_date: "",
  unit_price: "", total_amount: "", invoice_number: "", storage_location: "", notes: "", attachment_url: "", paid_now: false, paid_method: "Cash",
};

function daysText(d) {
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
    <section className="sp-alerts" aria-label="Seed packet expiry alerts">
      <div className="sp-alerts-head">
        <strong>{data.expired > 0 ? `${data.expired} expired` : ""}{data.expired > 0 && data.expiring > 0 ? " · " : ""}{data.expiring > 0 ? `${data.expiring} expiring soon` : ""} seed packet batch{data.items.length === 1 ? "" : "es"}</strong>
        {onOpen && <button type="button" className="btn btn-sm btn-outline dark" onClick={onOpen}>Open packet inventory</button>}
      </div>
      <div className="sp-alert-grid">
        {shown.map((a) => (
          <div key={a.id} className={`sp-alert sp-alert-${a.level}`}>
            <div className="sp-alert-tag">{a.status === "Expired" ? "EXPIRED" : a.level === "critical" ? "HIGH ALERT" : "WARNING"}{a.is_new ? <em>new</em> : null}</div>
            <h4>{a.plant_name}{a.variety ? ` · ${a.variety}` : ""}</h4>
            <dl>
              <div><dt>Company</dt><dd>{a.company || "-"}</dd></div>
              <div><dt>Batch</dt><dd>{a.batch_number}</dd></div>
              <div><dt>Remaining</dt><dd>{num(a.remaining)} packets</dd></div>
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
            <h1>Seed Packet Entry</h1>
            <p>Packets bought from seed companies: batch, expiry, usage and history. Separate from plant stock.</p>
          </div>
        </div>
        <div className="sm-head-actions">
          <button type="button" className="btn btn-primary sm-new" onClick={() => { setTab("new"); setNotice(""); }}>+ New Packet Entry</button>
        </div>
      </div>
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      <SeedPacketAlerts key={tick} onOpen={() => setTab("inventory")} />
      <div className="sm-filters" role="tablist" aria-label="Seed packet sections">
        {[["new", "New Packet Entry"], ["inventory", "Packet Inventory"], ["history", "Packet History"]].map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} className={`sm-chip${tab === key ? " active" : ""}`} onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>
      {tab === "new" && <NewEntry plants={plants} onSaved={(msg) => { refresh(msg); setTab("inventory"); }} />}
      {tab === "inventory" && <Inventory plants={plants} tick={tick} onChanged={refresh} />}
      {tab === "history" && <History tick={tick} />}
    </div>
  );
}

function NewEntry({ plants, onSaved }) {
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ask, setAsk] = useState("");
  const requestId = useRef(newId());
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const packets = Number(form.packets || 0);
  const total = form.total_amount !== "" ? Number(form.total_amount) : form.unit_price !== "" && packets ? Number(form.unit_price) * packets : null;
  const problems = [];
  if (form.expiry_date && form.purchase_date && form.expiry_date < form.purchase_date) problems.push("Expiry date is before the purchase date.");
  if (form.manufacturing_date && form.expiry_date && form.manufacturing_date > form.expiry_date) problems.push("Manufacturing date is after the expiry date.");
  const ready = form.plant_id && form.company.trim() && form.batch_number.trim() && packets > 0 && form.expiry_date && form.purchase_date && problems.length === 0;

  async function save(e, merge = false) {
    e?.preventDefault();
    if (busy || !ready) return;
    setBusy(true);
    setError("");
    try {
      const body = {
        plant_id: Number(form.plant_id), variety: form.variety, company: form.company, supplier: form.supplier, batch_number: form.batch_number, packets,
        packet_size: form.packet_size === "" ? null : Number(form.packet_size), packet_unit: form.packet_unit, purchase_date: form.purchase_date, manufacturing_date: form.manufacturing_date || null,
        expiry_date: form.expiry_date, unit_price: form.unit_price === "" ? null : Number(form.unit_price), total_amount: form.total_amount === "" ? null : Number(form.total_amount),
        invoice_number: form.invoice_number, storage_location: form.storage_location, notes: form.notes, attachment_url: form.attachment_url,
        paid_now: form.paid_now, paid_method: form.paid_method, merge_into_existing: merge, request_id: requestId.current,
      };
      const r = await api.post("/admin/stock/seed-packets", body);
      const exp = r.expense_id ? " The purchase was added to Accounting > Expenses automatically." : "";
      setForm(EMPTY);
      setAsk("");
      requestId.current = newId();
      onSaved(`Saved ${r.record_no}: ${num(packets)} packets, batch ${r.batch_number}, expiry ${fmtDate(r.expiry_date)}.${exp}`);
    } catch (err) {
      if (err.status === 409 && String(err.message).startsWith("BATCH_EXISTS")) setAsk(String(err.message).replace("BATCH_EXISTS: ", ""));
      else setError(err.message || "Could not save the packet entry.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="sp-form" onSubmit={save}>
      {error && <div className="alert alert-error">{error}</div>}
      {ask && (
        <div className="alert alert-warning sp-ask" role="alert">
          <p>{ask}</p>
          <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={(e) => save(e, true)}>Yes, add to that batch</button>{" "}
          <button type="button" className="btn btn-sm btn-outline dark" onClick={() => setAsk("")}>No, let me check the batch number</button>
        </div>
      )}
      <div className="sp-grid">
        <div className="form-group sp-wide">
          <label htmlFor="sp_plant">Plant name *</label>
          <SearchSelect id="sp_plant" options={plants.map((p) => ({ value: p.id, label: p.name }))} value={form.plant_id} onChange={(v) => setForm({ ...form, plant_id: v })} placeholder="Search and select a plant..." searchPlaceholder="Type the plant name" emptyText="No plant matches" />
        </div>
        <label>Seed variety / name<input className="form-control" maxLength={150} value={form.variety} onChange={set("variety")} placeholder="e.g. Hybrid 1057" /></label>
        <label>Seed company / brand *<input className="form-control" required maxLength={150} value={form.company} onChange={set("company")} /></label>
        <label>Supplier / vendor<input className="form-control" maxLength={150} value={form.supplier} onChange={set("supplier")} /></label>
        <label>Batch / Lot number *<input className="form-control" required maxLength={80} value={form.batch_number} onChange={set("batch_number")} /></label>
        <label>Packets received *<input className="form-control" required inputMode="numeric" value={form.packets} onChange={(e) => setForm({ ...form, packets: sanitizeQuantityText(e.target.value, 1000000) })} /></label>
        <div className="sp-pair">
          <label>Packet size<input className="form-control" inputMode="decimal" value={form.packet_size} onChange={(e) => setForm({ ...form, packet_size: e.target.value.replace(/[^0-9.]/g, "") })} /></label>
          <label>Unit<select className="form-control" value={form.packet_unit} onChange={set("packet_unit")}>{UNITS.map((u) => <option key={u}>{u}</option>)}</select></label>
        </div>
        <label>Purchase date *<input className="form-control" type="date" required value={form.purchase_date} max={today()} onChange={set("purchase_date")} /></label>
        <label>Manufacturing date<input className="form-control" type="date" value={form.manufacturing_date} onChange={set("manufacturing_date")} /></label>
        <label>Expiry date *<input className="form-control" type="date" required value={form.expiry_date} onChange={set("expiry_date")} /></label>
        <label>Price per packet (₹)<input className="form-control" inputMode="decimal" value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value.replace(/[^0-9.]/g, "") })} /></label>
        <label>Total purchase amount (₹)<input className="form-control" inputMode="decimal" value={form.total_amount} placeholder={total != null && form.total_amount === "" ? String(total) : ""} onChange={(e) => setForm({ ...form, total_amount: e.target.value.replace(/[^0-9.]/g, "") })} /></label>
        <label>Invoice / bill number<input className="form-control" maxLength={80} value={form.invoice_number} onChange={set("invoice_number")} /></label>
        <label>Storage location<input className="form-control" maxLength={120} value={form.storage_location} onChange={set("storage_location")} placeholder="e.g. Cold room, shelf 2" /></label>
        <label className="sp-wide">Packet label / bill photo link (optional)<input className="form-control" maxLength={300} value={form.attachment_url} onChange={set("attachment_url")} placeholder="https://..." /></label>
        <label className="sp-wide">Notes<input className="form-control" maxLength={1000} value={form.notes} onChange={set("notes")} /></label>
      </div>
      {problems.map((p) => <p key={p} className="sp-problem">{p}</p>)}
      <div className="sp-expense">
        {total != null && total > 0 ? (
          <>
            <p><strong>{money(total)}</strong> will be added to <strong>Accounting → Expenses</strong> (category "Seed Packets"{form.supplier ? `, supplier ${form.supplier}` : ""}) automatically. You do not need to enter it again.</p>
            <label className="sp-check"><input type="checkbox" checked={form.paid_now} onChange={(e) => setForm({ ...form, paid_now: e.target.checked })} /> Already paid</label>
            {form.paid_now && <select className="form-control" style={{ maxWidth: 160 }} value={form.paid_method} onChange={set("paid_method")} aria-label="Payment method">{METHODS.map((m) => <option key={m}>{m}</option>)}</select>}
          </>
        ) : <p className="stock-hint">No amount entered, so no expense is created. Add the price or total to book it in Accounting.</p>}
      </div>
      <button className="btn btn-primary" disabled={busy || !ready}>{busy ? "Saving..." : "Save packet entry"}</button>
    </form>
  );
}

function Inventory({ plants, tick, onChanged }) {
  const [data, setData] = useState(null);
  const [f, setF] = useState({ q: "", plant_id: "", company: "", supplier: "", batch: "", expiry: "all", show_empty: false });
  const [act, setAct] = useState(null); // { kind, row, ...fields }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const t = setTimeout(() => {
      const qs = new URLSearchParams({ expiry: f.expiry, show_empty: String(f.show_empty) });
      ["q", "plant_id", "company", "supplier", "batch"].forEach((k) => f[k] && qs.set(k, f[k]));
      api.get(`/admin/stock/seed-packets?${qs}`).then(setData).catch((e) => setError(e.message || "Could not load packets."));
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
  const setFilter = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const t = data?.totals;
  const open = (kind, row) => { setError(""); setAct({ kind, row, qty: "", count: String(row.remaining), reason: "", expiry: row.expiry_date, batch: row.batch_number, storage: row.storage_location }); };

  return (
    <section>
      {t && (
        <div className="sp-kpis">
          <div><span>{num(t.batches)}</span>Active batches</div>
          <div><span>{num(t.remaining)}</span>Packets in stock</div>
          <div className={t.expiring_soon ? "warn" : ""}><span>{num(t.expiring_soon)}</span>Expiring soon</div>
          <div className={t.expired ? "bad" : ""}><span>{num(t.expired)}</span>Expired</div>
        </div>
      )}
      <div className="sp-filters">
        <input className="form-control" placeholder="Search plant, variety, company, batch..." value={f.q} onChange={setFilter("q")} aria-label="Search packets" />
        <select className="form-control" value={f.plant_id} onChange={setFilter("plant_id")} aria-label="Plant"><option value="">All plants</option>{plants.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
        <input className="form-control" placeholder="Company" value={f.company} onChange={setFilter("company")} aria-label="Company" />
        <input className="form-control" placeholder="Supplier" value={f.supplier} onChange={setFilter("supplier")} aria-label="Supplier" />
        <input className="form-control" placeholder="Batch" value={f.batch} onChange={setFilter("batch")} aria-label="Batch" />
        <select className="form-control" value={f.expiry} onChange={setFilter("expiry")} aria-label="Expiry status">
          <option value="all">All expiry status</option><option value="ok">OK</option><option value="soon">Expiring soon</option><option value="expired">Expired</option><option value="empty">Empty (finished)</option>
        </select>
        <label className="sp-check"><input type="checkbox" checked={f.show_empty} onChange={setFilter("show_empty")} /> Show finished batches</label>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {act && (
        <form className="seed-form seed-edit" onSubmit={submit}>
          <h4>{{ use: "Use packets", adjust: "Correct the count", correct: "Correct batch details", writeoff: "Write off remaining packets" }[act.kind]}: {act.row.plant_name}, batch {act.row.batch_number}</h4>
          {act.kind === "use" && (
            <>
              {act.row.status === "Expired" && <p className="sp-problem">This batch is expired. Using it is an exception and will be recorded with your reason.</p>}
              <label>Packets used (left: {num(act.row.remaining)})<input className="form-control" required inputMode="numeric" value={act.qty} onChange={(e) => setAct({ ...act, qty: sanitizeQuantityText(e.target.value, 1000000) })} /></label>
              <label>{act.row.status === "Expired" ? "Reason for using expired packets *" : "Used for (optional)"}<input className="form-control" required={act.row.status === "Expired"} minLength={act.row.status === "Expired" ? 5 : 0} value={act.reason} onChange={(e) => setAct({ ...act, reason: e.target.value })} /></label>
            </>
          )}
          {act.kind === "adjust" && (
            <>
              <label>Packets really left after counting<input className="form-control" required inputMode="numeric" value={act.count} onChange={(e) => setAct({ ...act, count: sanitizeQuantityText(e.target.value, 1000000) })} /></label>
              <label>Why is it different? *<input className="form-control" required minLength={3} value={act.reason} onChange={(e) => setAct({ ...act, reason: e.target.value })} /></label>
            </>
          )}
          {act.kind === "correct" && (
            <>
              <label>Expiry date<input className="form-control" type="date" value={act.expiry} onChange={(e) => setAct({ ...act, expiry: e.target.value })} /></label>
              <label>Batch number<input className="form-control" maxLength={80} value={act.batch} onChange={(e) => setAct({ ...act, batch: e.target.value })} /></label>
              <label>Storage location<input className="form-control" maxLength={120} value={act.storage} onChange={(e) => setAct({ ...act, storage: e.target.value })} /></label>
              <label>What was wrong? *<input className="form-control" required minLength={3} value={act.reason} onChange={(e) => setAct({ ...act, reason: e.target.value })} /></label>
              <p className="stock-hint">The old value is kept in Packet History.</p>
            </>
          )}
          {act.kind === "writeoff" && (
            <>
              <p className="stock-hint">All {num(act.row.remaining)} remaining packets will be removed from stock. They stay in the history.</p>
              <label>Reason *<input className="form-control" required minLength={3} value={act.reason || "Expired: discarded"} onChange={(e) => setAct({ ...act, reason: e.target.value })} /></label>
            </>
          )}
          <div><button className="btn btn-primary" disabled={busy}>{busy ? "Saving..." : "Save"}</button>{" "}<button type="button" className="btn btn-outline dark" onClick={() => setAct(null)}>Cancel</button></div>
        </form>
      )}
      {data && data.items.length === 0 ? <p className="stock-hint">No packets match. Use "New Packet Entry" to add the first batch.</p> : data && (
        <div className="admin-table-wrap">
          <table className="admin-table sp-table">
            <thead><tr><th>Plant</th><th>Variety</th><th>Company</th><th>Batch</th><th className="num">Received</th><th className="num">Used</th><th className="num">Remaining</th><th>Purchased</th><th>Expiry</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>
              {data.items.map((r) => (
                <tr key={r.id} className={r.status === "Expired" ? "sp-row-expired" : r.status === "Expiring soon" ? "sp-row-soon" : ""}>
                  <td><strong>{r.plant_name}</strong><small>{r.record_no}{r.supplier ? ` · ${r.supplier}` : ""}</small></td>
                  <td>{r.variety || "-"}</td>
                  <td>{r.company || "-"}</td>
                  <td>{r.batch_number}{r.storage_location && <small>{r.storage_location}</small>}</td>
                  <td className="num">{num(r.received)}</td>
                  <td className="num">{num(r.used)}{r.adjusted !== 0 || r.written_off > 0 ? <small>{r.adjusted !== 0 ? `adj ${r.adjusted > 0 ? "+" : ""}${r.adjusted}` : ""}{r.written_off > 0 ? ` off ${r.written_off}` : ""}</small> : null}</td>
                  <td className="num"><strong>{num(r.remaining)}</strong></td>
                  <td>{fmtDate(r.purchase_date)}</td>
                  <td>{fmtDate(r.expiry_date)}<small>{r.status === "Empty" ? "" : daysText(r.days_left)}</small></td>
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
      <div className="sp-filters"><input className="form-control" placeholder="Search plant, company, batch, reason or person..." value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search history" /></div>
      {!rows ? null : rows.length === 0 ? <p className="stock-hint">No history yet.</p> : (
        <div className="admin-table-wrap">
          <table className="admin-table sp-table">
            <thead><tr><th>When</th><th>What</th><th>Plant / batch</th><th className="num">Packets</th><th>Reason / details</th><th>By</th></tr></thead>
            <tbody>
              {rows.map((h) => (
                <tr key={h.id}>
                  <td>{fmtTime(h.at)}</td>
                  <td><span className={`sp-type sp-type-${h.type.toLowerCase()}`}>{TYPE_LABEL[h.type] || h.type}</span>{h.is_exception && <small className="sp-problem">expired exception</small>}</td>
                  <td><strong>{h.plant_name}</strong>{h.variety ? ` · ${h.variety}` : ""}<small>{h.company} · batch {h.batch_number} · {h.record_no}</small></td>
                  <td className="num">{h.quantity > 0 ? `+${num(h.quantity)}` : h.quantity < 0 ? `−${num(Math.abs(h.quantity))}` : "-"}</td>
                  <td>{h.reason}{h.detail && <small>{h.detail}</small>}{h.total_amount ? <small>{money(h.total_amount)}{h.invoice_number ? ` · ${h.invoice_number}` : ""}{h.expense_id ? " · in Expenses" : ""}</small> : null}</td>
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
