import { useEffect, useRef, useState } from "react";
import { api } from "../../../api";
import { sanitizeQuantityText } from "../../../utils/quantity";
import { num } from "../../stock/stockUi";
import SeedHistory from "./SeedHistory";

const newId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
const today = () => new Date().toISOString().slice(0, 10);
const BADGE = { Pending: "badge-gold", "In Progress": "badge-accent", Completed: "badge-muted" };
const EMPTY = { customer_id: "", new_name: "", new_phone: "", plant_id: "", variant_id: "", seeds: "", date: today(), reference: "", notes: "" };

// Seeds a walk-in customer hands over. Lives on the Stock page (no separate page).
// The plants that come out are recorded on the "Add Plants" page by choosing the customer there.
export default function SeedEntries({ plants, onChanged, startOpen = false }) {
  const [data, setData] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [open, setOpen] = useState(startOpen);
  const [form, setForm] = useState(EMPTY);
  const [addNew, setAddNew] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [version, setVersion] = useState(0);
  const formId = useRef(newId());

  function load() {
    api.get("/admin/stock/seed-entries?status=open").then(setData).catch((e) => setError(e.message || "Could not load seed entries."));
    setVersion((v) => v + 1);
  }
  useEffect(load, []);
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

  const t = data?.totals;
  return (
    <section className="seed-card" aria-label="Seed entries">
      <div className="seed-head">
        <div>
          <h2>Customer seeds</h2>
          <p>Customer gave seeds? Save them here. When the plants are ready, press "Add plants" on that row.</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => { setOpen(!open); setMsg(""); setError(""); }}>{open ? "Close" : "+ New Seed Entry"}</button>
      </div>
      {msg && <div className="alert alert-success" role="status">{msg}</div>}
      {error && <div className="alert alert-error">{error}</div>}
      {open && (
        <div className="seed-form">
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
        <div className="seed-kpis" data-testid="seed-totals">
          <div><span>{num(t.open_entries)}</span>Open entries</div>
          <div><span>{num(t.seeds_given)}</span>Seeds given</div>
          <div><span>{num(t.remaining)}</span>Still to grow</div>
          <div><span>{num(t.prepared)}</span>Ready for customers</div>
          <div><span>{num(t.extra)}</span>Extra plants</div>
        </div>
      )}
      <SeedHistory plants={plants} version={version} onChanged={() => { load(); onChanged?.(); }} />
    </section>
  );
}
