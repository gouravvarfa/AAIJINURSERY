import { useEffect, useRef, useState } from "react";
import { api } from "../../../api";
import { sanitizeQuantityText } from "../../../utils/quantity";
import { num } from "../../stock/stockUi";

const newId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
const today = () => new Date().toISOString().slice(0, 10);
const BADGE = { Pending: "badge-gold", "In Progress": "badge-accent", Completed: "badge-muted" };
const EMPTY = { customer_id: "", new_name: "", new_phone: "", plant_id: "", variant_id: "", seeds: "", date: today(), reference: "", notes: "" };

// Seeds a walk-in customer hands over. Lives inside the Stock page (no separate page).
export default function SeedEntries({ plants, onChanged }) {
  const [data, setData] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [addNew, setAddNew] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [upd, setUpd] = useState(null); // { entry, prepared, extra, rejected, notes }
  const [showAll, setShowAll] = useState(false);
  const formId = useRef(newId());
  const updId = useRef(newId());

  function load() {
    api.get(`/admin/stock/seed-entries?status=${showAll ? "all" : "open"}`).then(setData).catch((e) => setError(e.message || "Could not load seed entries."));
  }
  useEffect(load, [showAll]);
  useEffect(() => {
    if (open) api.get("/admin/stock/seed-entries/customers").then(setCustomers).catch(() => {});
  }, [open]);

  const plant = plants.find((p) => String(p.id) === String(form.plant_id));
  const needsTray = Boolean(plant?.variants?.length);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  async function save(e) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const body = {
        plant_id: Number(form.plant_id), variant_id: form.variant_id ? Number(form.variant_id) : null, seeds_given: Number(form.seeds),
        entry_date: form.date || null, reference: form.reference, notes: form.notes, request_id: formId.current,
      };
      if (addNew) body.new_customer = { name: form.new_name, phone: form.new_phone };
      else body.contact_id = Number(form.customer_id);
      const r = await api.post("/admin/stock/seed-entries", body);
      setMsg(`Saved ${r.entry_number}: ${num(r.seeds_given)} seeds of ${r.plant_name} from ${r.customer_name}. Status: Seeds Given / Production Pending.`);
      setForm(EMPTY);
      setAddNew(false);
      setOpen(false);
      formId.current = newId();
      load();
      onChanged?.();
    } catch (err) {
      setError(err.message || "Could not save the entry.");
    } finally {
      setBusy(false);
    }
  }

  async function saveUpdate(e, finish) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const r = await api.post(`/admin/stock/seed-entries/${upd.entry.id}/update`, {
        prepared_plants: Number(upd.prepared || 0), extra_plants: Number(upd.extra || 0), rejected_plants: Number(upd.rejected || 0), finish, notes: upd.notes, request_id: updId.current,
      });
      setMsg(`${r.entry_number} updated: ${num(r.prepared_plants)} for the customer, ${num(r.extra_plants)} extra, ${num(r.remaining)} seeds remaining${r.status === "Completed" ? " (completed)" : ""}.`);
      setUpd(null);
      updId.current = newId();
      load();
      onChanged?.();
    } catch (err) {
      setError(err.message || "Could not update the entry.");
    } finally {
      setBusy(false);
    }
  }

  const t = data?.totals;
  const numSet = (k) => (e) => setUpd({ ...upd, [k]: sanitizeQuantityText(e.target.value, 100000000) });
  return (
    <section style={{ marginTop: 24 }} aria-label="Seed entries">
      <div className="stock-actions-row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <h2 style={{ fontSize: "1.2rem", margin: 0 }}>Customer seeds (production pending)</h2>
        <button type="button" className="btn btn-primary" onClick={() => { setOpen(!open); setMsg(""); setError(""); }}>{open ? "Close" : "+ New Seed Entry"}</button>
      </div>
      <p className="stock-hint" style={{ margin: "6px 0 12px" }}>
        When a customer gives seeds, save them here at once. Seeds are not ready plants, so they do not add to Ready now. Update the same entry later when plants are prepared.
      </p>
      {msg && <div className="alert alert-success" role="status">{msg}</div>}
      {error && <div className="alert alert-error">{error}</div>}
      {open && (
        <div className="admin-form-card" style={{ maxWidth: 640, marginBottom: 16 }}>
          <form onSubmit={save} className="stock-form-grid">
            {addNew ? (
              <>
                <label>Customer name<input className="form-control" required maxLength={150} value={form.new_name} onChange={set("new_name")} /></label>
                <label>Mobile (optional)<input className="form-control" inputMode="tel" maxLength={20} value={form.new_phone} onChange={set("new_phone")} /></label>
                <button type="button" className="btn btn-sm btn-outline dark" onClick={() => setAddNew(false)}>Choose an existing customer instead</button>
              </>
            ) : (
              <>
                <label>
                  Customer
                  <select className="form-control" required value={form.customer_id} onChange={set("customer_id")}>
                    <option value="">Choose a customer...</option>
                    {customers.map((c) => (<option key={c.id} value={c.id}>{c.name}{c.phone ? ` (${c.phone})` : ""}</option>))}
                  </select>
                </label>
                <button type="button" className="btn btn-sm btn-outline dark" onClick={() => setAddNew(true)}>+ New customer</button>
              </>
            )}
            <label>
              Plant
              <select className="form-control" required value={form.plant_id} onChange={(e) => setForm({ ...form, plant_id: e.target.value, variant_id: "" })}>
                <option value="">Choose a plant...</option>
                {plants.map((p) => (<option key={p.id} value={p.id}>{p.name}</option>))}
              </select>
            </label>
            {needsTray && (
              <label>
                Tray size
                <select className="form-control" required value={form.variant_id} onChange={set("variant_id")}>
                  <option value="">Choose a tray...</option>
                  {plant.variants.map((v) => (<option key={v.id} value={v.id}>{v.tray_size} plants per tray</option>))}
                </select>
              </label>
            )}
            <label>Seed quantity<input className="form-control" required inputMode="numeric" value={form.seeds} onChange={(e) => setForm({ ...form, seeds: sanitizeQuantityText(e.target.value, 100000000) })} /></label>
            <label>Entry date<input className="form-control" type="date" required value={form.date} onChange={set("date")} /></label>
            <label>Sales order / reference (optional)<input className="form-control" maxLength={80} value={form.reference} onChange={set("reference")} /></label>
            <label>Notes (optional)<input className="form-control" maxLength={1000} value={form.notes} onChange={set("notes")} /></label>
            <button className="btn btn-primary" disabled={busy || !form.seeds || Number(form.seeds) < 1}>{busy ? "Saving..." : "Save seed entry"}</button>
          </form>
        </div>
      )}
      {t && (
        <div className="stock-actions-row" style={{ gap: 16, flexWrap: "wrap" }} data-testid="seed-totals">
          <span><strong>{num(t.open_entries)}</strong> open entries</span>
          <span><strong>{num(t.seeds_given)}</strong> seeds given</span>
          <span><strong>{num(t.remaining)}</strong> seeds still to grow</span>
          <span><strong>{num(t.prepared)}</strong> prepared for customers</span>
          <span><strong>{num(t.extra)}</strong> extra plants</span>
        </div>
      )}
      <label style={{ display: "flex", alignItems: "center", gap: 8, margin: "8px 0" }}>
        <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Show completed entries too
      </label>
      {data && data.items.length === 0 ? <p className="stock-hint">No seed entries yet.</p> : data && (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead><tr><th>Entry</th><th>Date</th><th>Customer</th><th>Plant</th><th>Seeds given</th><th>Prepared</th><th>Extra</th><th>Remaining</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {data.items.map((r) => (
                <tr key={r.id}>
                  <td>{r.entry_number}{r.reference ? <div className="stock-hint">{r.reference}</div> : null}</td>
                  <td>{r.entry_date}</td>
                  <td>{r.customer_name}</td>
                  <td>{r.plant_name}</td>
                  <td>{num(r.seeds_given)}</td>
                  <td>{num(r.prepared_plants)}</td>
                  <td>{num(r.extra_plants)}</td>
                  <td>{num(r.remaining)}</td>
                  <td><span className={`badge ${BADGE[r.status] || "badge-muted"}`}>{r.status_label}</span></td>
                  <td>{r.status !== "Completed" && <button type="button" className="btn btn-sm btn-outline dark" onClick={() => { setUpd({ entry: r, prepared: "", extra: "", rejected: "", notes: "" }); updId.current = newId(); setError(""); }}>Update production</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {upd && (
        <div className="admin-form-card" style={{ maxWidth: 560, marginTop: 16 }}>
          <h3 style={{ marginTop: 0 }}>Update {upd.entry.entry_number}: {upd.entry.customer_name}, {upd.entry.plant_name}</h3>
          <p className="stock-hint">{num(upd.entry.remaining)} seeds remaining. Write only the NEW numbers since the last update. Extra usable plants go into Ready now.</p>
          <form onSubmit={(e) => saveUpdate(e, false)} className="stock-form-grid">
            <label>Prepared for this customer<input className="form-control" inputMode="numeric" value={upd.prepared} onChange={numSet("prepared")} /></label>
            <label>Extra usable plants<input className="form-control" inputMode="numeric" value={upd.extra} onChange={numSet("extra")} /></label>
            <label>Rejected / dead<input className="form-control" inputMode="numeric" value={upd.rejected} onChange={numSet("rejected")} /></label>
            <label>Notes (optional)<input className="form-control" maxLength={1000} value={upd.notes} onChange={(e) => setUpd({ ...upd, notes: e.target.value })} /></label>
            <div>
              <button className="btn btn-primary" disabled={busy || !(Number(upd.prepared) || Number(upd.extra) || Number(upd.rejected))}>{busy ? "Saving..." : "Save update"}</button>{" "}
              <button type="button" className="btn btn-outline dark" disabled={busy} onClick={(e) => saveUpdate(e, true)}>Save and finish (rest did not grow)</button>{" "}
              <button type="button" className="btn btn-outline dark" onClick={() => setUpd(null)}>Cancel</button>
            </div>
          </form>
        </div>
      )}
    </section>
  );
}
