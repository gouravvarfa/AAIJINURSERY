import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../api";
import { PlantLink, qtyText, useSuggestions, useSupplyMeta } from "../../accounting/supplyCommon";
import { num } from "../../stock/stockUi";

const newId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
const today = () => new Date().toISOString().slice(0, 10);
const fmtDate = (v) => (v ? new Date(`${v}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "-");
const fmtTime = (v) => new Date(v).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const money = (n) => (n == null ? "-" : `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);
const SIZE_UNITS = ["g", "kg", "mg", "seeds", "pcs", "ml", "litre"];
const TYPE_LABEL = { RECEIPT: "Received", USAGE: "Used", ADJUSTMENT: "Adjusted", EXPIRED_WRITEOFF: "Written off", CORRECTION: "Corrected" };
const BADGE = { OK: "sp-ok", "Expiring soon": "sp-soon", Expired: "sp-expired", Empty: "sp-empty" };
const EMPTY = {
  item_kind: "seed_packet", item_name: "", plant_id: "", company: "", supplier_contact_id: "", supplier: "", lot_number: "", quantity: "", unit: "", packet_size: "", packet_unit: "g",
  purchase_date: today(), mfg_date: "", expiry_date: "", unit_price: "", total_amount: "", invoice_number: "", storage_location: "", notes: "", attachment_url: "",
};

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
            <h1>Seed Packet Entry</h1>
            <p>Seed packets, medicines, fertilizers and supplies you buy: lot, expiry, usage and history. Separate from plant stock.</p>
          </div>
        </div>
        <div className="sm-head-actions">
          <button type="button" className="btn btn-primary sm-new" onClick={() => { setTab("new"); setNotice(""); }}>+ New Packet Entry</button>
        </div>
      </div>
      {notice && <div className="alert alert-success" role="status">{notice}</div>}
      <SeedPacketAlerts key={tick} onOpen={() => setTab("inventory")} />
      <div className="sm-filters" role="tablist" aria-label="Packet sections">
        {[["new", "New Packet Entry"], ["inventory", "Packet Inventory"], ["history", "Packet History"]].map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} className={`sm-chip${tab === key ? " active" : ""}`} onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>
      {tab === "new" && <NewEntry plants={plants} onPlantCreated={(pl) => setPlants((list) => [...list, pl].sort((x, y) => x.name.localeCompare(y.name)))} onSaved={(msg) => { refresh(msg); setTab("inventory"); }} />}
      {tab === "inventory" && <Inventory plants={plants} tick={tick} onChanged={refresh} />}
      {tab === "history" && <History tick={tick} />}
    </div>
  );
}

function NewEntry({ plants, onSaved, onPlantCreated }) {
  const { meta, kind, whole } = useSupplyMeta();
  const [form, setForm] = useState(EMPTY);
  const [suppliers, setSuppliers] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ask, setAsk] = useState(""); // same lot already recorded: add to it?
  const [dup, setDup] = useState(""); // this supplier already has this bill number
  const [dupReason, setDupReason] = useState("");
  const requestId = useRef(newId());
  const sug = useSuggestions(form.item_kind);
  const k = kind(form.item_kind);
  const unit = form.unit || k.default_unit;
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value });

  useEffect(() => {
    Promise.all([api.get("/admin/accounting/contacts?contact_type=supplier"), api.get("/admin/accounting/contacts?contact_type=both")])
      .then(([a, b]) => setSuppliers([...a, ...b].sort((x, y) => x.name.localeCompare(y.name)))).catch(() => {});
  }, []);

  const qty = Number(form.quantity || 0);
  const total = form.total_amount !== "" ? Number(form.total_amount) : form.unit_price !== "" && qty ? Math.round(Number(form.unit_price) * qty * 100) / 100 : null;
  const supplierName = form.supplier_contact_id ? suppliers.find((s) => s.id === Number(form.supplier_contact_id))?.name : form.supplier.trim();
  const problems = [];
  if (form.expiry_date && form.purchase_date && form.expiry_date < form.purchase_date) problems.push("Expiry date is before the purchase date.");
  if (form.mfg_date && form.expiry_date && form.mfg_date > form.expiry_date) problems.push("Manufacturing date is after the expiry date.");
  if (qty > 0 && whole(unit) && Math.abs(qty - Math.round(qty)) > 1e-9) problems.push(`${unit} must be a whole number. Use kg, g, litre or ml for fractions.`);
  const hasName = form.item_name.trim() || (form.item_kind === "seed_packet" && form.plant_id);
  const ready = hasName && (form.item_kind !== "seed_packet" || form.company.trim()) && (!k.lot_required || form.lot_number.trim()) && (!k.expiry_required || form.expiry_date) && qty > 0 && form.purchase_date && problems.length === 0;

  async function save(e, merge = false) {
    e?.preventDefault();
    if (busy || !ready) return;
    setBusy(true);
    setError("");
    try {
      const body = {
        item_kind: form.item_kind, item_name: form.item_name, plant_id: form.item_kind === "seed_packet" && form.plant_id ? Number(form.plant_id) : null, company: form.company,
        supplier: form.supplier_contact_id ? "" : form.supplier, supplier_contact_id: form.supplier_contact_id ? Number(form.supplier_contact_id) : null, lot_number: form.lot_number,
        quantity: qty, quantity_unit: unit, packet_size: form.item_kind === "seed_packet" && form.packet_size ? Number(form.packet_size) : null, packet_unit: form.item_kind === "seed_packet" ? form.packet_unit : "",
        purchase_date: form.purchase_date, manufacturing_date: form.mfg_date || null, expiry_date: form.expiry_date || null,
        unit_price: form.unit_price === "" ? null : Number(form.unit_price), total_amount: form.total_amount === "" ? null : Number(form.total_amount),
        invoice_number: form.invoice_number, storage_location: form.storage_location, notes: form.notes, attachment_url: form.attachment_url,
        merge_into_existing: merge, allow_duplicate_bill: Boolean(dup), duplicate_reason: dup ? dupReason : "", request_id: requestId.current,
      };
      const r = await api.post("/admin/stock/seed-packets", body);
      const bill = r.billed ? ` A Bill was made for ${supplierName} (Unpaid) in Accounting → Bills. Pay it from Payments Out.` : "";
      setForm(EMPTY);
      setAsk("");
      setDup("");
      setDupReason("");
      requestId.current = newId();
      onSaved(`Saved ${r.record_no}: ${num(qty)} ${unit} of ${r.item_name || r.plant_name}${r.batch_number ? `, lot ${r.batch_number}` : ""}${r.expiry_date ? `, expiry ${fmtDate(r.expiry_date)}` : ""}.${bill}`);
    } catch (err) {
      const msg = String(err.message || "");
      if (err.status === 409 && msg.startsWith("BATCH_EXISTS")) setAsk(msg.replace("BATCH_EXISTS: ", ""));
      else if (err.status === 409 && msg.startsWith("DUPLICATE_BILL")) setDup(msg.replace("DUPLICATE_BILL: ", ""));
      else setError(msg || "Could not save the entry.");
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
          <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={(e) => save(e, true)}>Yes, add to that lot</button>{" "}
          <button type="button" className="btn btn-sm btn-outline dark" onClick={() => setAsk("")}>No, let me check the lot number</button>
        </div>
      )}
      {dup && (
        <div className="alert alert-warning sp-ask" role="alert">
          <p>{dup}</p>
          <input className="form-control" placeholder="Why is this a second bill with the same number? (required)" value={dupReason} onChange={(e) => setDupReason(e.target.value)} aria-label="Reason for the duplicate bill number" />
          <div><button type="button" className="btn btn-sm btn-primary" disabled={busy || dupReason.trim().length < 5} onClick={(e) => save(e)}>Save anyway</button>{" "}
            <button type="button" className="btn btn-sm btn-outline dark" onClick={() => { setDup(""); setDupReason(""); }}>No, let me check the bill number</button></div>
        </div>
      )}
      <div className="sp-grid">
        <label>Item type *
          <select className="form-control" value={form.item_kind} onChange={(e) => setForm({ ...form, item_kind: e.target.value, unit: "", plant_id: e.target.value === "seed_packet" ? form.plant_id : "" })}>
            {meta.kinds.map((x) => (<option key={x.key} value={x.key}>{x.label}</option>))}
          </select>
        </label>
        <label className="sp-span2">{form.item_kind === "seed_packet" ? "Seed name / variety" : "Item name *"}
          <input className="form-control" list="sp-names" maxLength={200} value={form.item_name} onChange={set("item_name")} placeholder={form.item_kind === "seed_packet" ? "e.g. Hybrid 1057 (or choose the plant below)" : "e.g. Neem oil"} />
          <datalist id="sp-names">{sug.names.map((x) => (<option key={x} value={x} />))}</datalist>
        </label>
        {form.item_kind === "seed_packet" && (
          <div className="form-group sp-wide">
            <label htmlFor="sp_plant">Plant (optional)</label>
            <PlantLink id="sp_plant" plants={plants} value={form.plant_id} onChange={(v) => setForm((f) => ({ ...f, plant_id: v }))} onPlantCreated={onPlantCreated} />
          </div>
        )}
        <label>{form.item_kind === "seed_packet" ? "Seed company / brand *" : "Company / brand"}
          <input className="form-control" list="sp-co" maxLength={150} value={form.company} onChange={set("company")} />
          <datalist id="sp-co">{sug.companies.map((x) => (<option key={x} value={x} />))}</datalist>
        </label>
        <label>Lot / batch number{k.lot_required ? " *" : ""}<input className="form-control" maxLength={80} value={form.lot_number} onChange={set("lot_number")} /></label>
        <div className="sp-pair">
          <label>Quantity received *<input className="form-control" inputMode="decimal" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: qtyText(e.target.value) })} /></label>
          <label>Unit<select className="form-control" value={unit} onChange={set("unit")}>{meta.units.map((u) => (<option key={u.key} value={u.key}>{u.key}</option>))}</select></label>
        </div>
        {form.item_kind === "seed_packet" && (
          <div className="sp-pair">
            <label>Packet size<input className="form-control" inputMode="decimal" value={form.packet_size} onChange={(e) => setForm({ ...form, packet_size: qtyText(e.target.value) })} /></label>
            <label>Size unit<select className="form-control" value={form.packet_unit} onChange={set("packet_unit")}>{SIZE_UNITS.map((u) => <option key={u}>{u}</option>)}</select></label>
          </div>
        )}
        <label>Purchase date *<input className="form-control" type="date" required value={form.purchase_date} max={today()} onChange={set("purchase_date")} /></label>
        <label>Manufacturing date<input className="form-control" type="date" value={form.mfg_date} onChange={set("mfg_date")} /></label>
        <label>Expiry date{k.expiry_required ? " *" : ""}<input className="form-control" type="date" value={form.expiry_date} onChange={set("expiry_date")} /></label>
        <label className="sp-span2">Supplier / vendor
          <select className="form-control" value={form.supplier_contact_id} onChange={(e) => setForm({ ...form, supplier_contact_id: e.target.value, supplier: e.target.value ? "" : form.supplier })}>
            <option value="">{`Type a supplier name below (or choose an existing supplier)`}</option>
            {suppliers.map((s) => (<option key={s.id} value={s.id}>{s.name}{s.phone ? ` (${s.phone})` : ""}</option>))}
          </select>
          {!form.supplier_contact_id && <input className="form-control" maxLength={150} style={{ marginTop: 6 }} placeholder="Supplier name" value={form.supplier} onChange={set("supplier")} />}
        </label>
        <label>Supplier bill / invoice number<input className="form-control" maxLength={80} value={form.invoice_number} onChange={(e) => { setForm({ ...form, invoice_number: e.target.value }); setDup(""); }} placeholder="Leave empty if no bill yet" /></label>
        <label>Cost per {unit} (₹)<input className="form-control" inputMode="decimal" value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: qtyText(e.target.value) })} /></label>
        <label>Total purchase amount (₹)<input className="form-control" inputMode="decimal" value={form.total_amount} placeholder={total != null && form.total_amount === "" ? String(total) : ""} onChange={(e) => setForm({ ...form, total_amount: qtyText(e.target.value) })} /></label>
        <label>Storage location<input className="form-control" maxLength={120} value={form.storage_location} onChange={set("storage_location")} placeholder="e.g. Cold room, shelf 2" /></label>
        <label className="sp-wide">Packet label / bill photo link (optional)<input className="form-control" maxLength={300} value={form.attachment_url} onChange={set("attachment_url")} placeholder="https://..." /></label>
        <label className="sp-wide">Notes<input className="form-control" maxLength={1000} value={form.notes} onChange={set("notes")} /></label>
      </div>
      {problems.map((p) => <p key={p} className="sp-problem">{p}</p>)}
      <div className="sp-expense">
        {total != null && total > 0 && supplierName ? (
          <p>A <strong>Bill of {money(total)}</strong> will be made for <strong>{supplierName}</strong> in <strong>Accounting → Bills</strong> and shows in their account as <strong>Unpaid</strong>. Pay it from Accounting → Payments Out. You do not enter it again.</p>
        ) : total != null && total > 0 ? (
          <p className="stock-hint">Choose or type a supplier to make a Bill in their account. Without a supplier the stock is saved but nothing is booked in Accounting.</p>
        ) : <p className="stock-hint">No amount entered, so no Bill is made. Add the cost and a supplier to book it in Accounting.</p>}
      </div>
      <button className="btn btn-primary" disabled={busy || !ready}>{busy ? "Saving..." : "Save entry"}</button>
    </form>
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
      {data && data.items.length === 0 ? <p className="stock-hint">Nothing matches. Use "New Packet Entry" to add the first lot.</p> : data && (
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
