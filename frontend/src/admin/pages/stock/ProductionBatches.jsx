import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import { Hint, STATUS_BADGE, StockHelp, num } from "../../stock/stockUi";
import { sanitizeQuantityText } from "../../../utils/quantity";

// Production Batches: one batch = one round of making plants from seeds.
export default function ProductionBatches() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [batches, setBatches] = useState(null);
  const [plants, setPlants] = useState([]);
  const [seeds, setSeeds] = useState([]);
  const [demand, setDemand] = useState([]);
  const [waiting, setWaiting] = useState([]);
  const [showForm, setShowForm] = useState(Boolean(params.get("plant")));
  const [form, setForm] = useState({ plant_id: params.get("plant") || "", variant_id: params.get("variant") || "", seed_item_id: "", planned_quantity: "", notes: "" });
  const [picked, setPicked] = useState({});
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/admin/stock/batches").then(setBatches).catch((e) => setError(e.message || "Could not load the batches."));
    api.get("/admin/plants").then(setPlants).catch(() => {});
    api.get("/admin/stock/seeds").then(setSeeds).catch(() => {});
    api.get("/admin/inventory/stock-demand").then((d) => setDemand(d.items)).catch(() => {});
    api.get("/admin/stock/allocations").then((d) => setWaiting(d.items)).catch(() => {});
  }, []);

  const plant = plants.find((p) => String(p.id) === String(form.plant_id));
  const tray = plant?.variants?.find((v) => String(v.id) === String(form.variant_id));
  const row = demand.find((r) => String(r.plant_id) === String(form.plant_id) && String(r.variant_id || "") === String(form.variant_id || ""));
  const needsTray = Boolean(plant?.variants?.length);
  const suggestion = row ? row.to_produce * (tray ? tray.tray_size : 1) : 0;
  const matchingSeeds = seeds.filter((s) => !s.plant_id || String(s.plant_id) === String(form.plant_id));
  const lines = useMemo(
    () => waiting.filter((w) => w.pending > 0 && String(w.plant_id) === String(form.plant_id) && String(w.variant_id || "") === String(form.variant_id || "")),
    [waiting, form.plant_id, form.variant_id]
  );

  async function create(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const batch = await api.post("/admin/stock/batches", {
        plant_id: Number(form.plant_id),
        variant_id: form.variant_id ? Number(form.variant_id) : null,
        seed_item_id: form.seed_item_id ? Number(form.seed_item_id) : null,
        planned_quantity: Number(form.planned_quantity),
        notes: form.notes,
        links: lines.filter((l) => picked[`${l.kind}-${l.item_id}`]).map((l) => ({ kind: l.kind, item_id: l.item_id })),
      });
      navigate(`/admin/stock/batches/${batch.id}`);
    } catch (err) {
      setError(err.message || "Could not create the batch.");
      setBusy(false);
    }
  }

  const shown = (batches || []).filter((b) => !filter || b.status === filter);
  return (
    <div>
      <div className="admin-page-head">
        <h1>Production Batches</h1>
        <div className="admin-page-head-controls">
          <select className="form-control admin-control-sm" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter batches">
            <option value="">All batches</option>
            <option value="Draft">Planned (not started)</option>
            <option value="In Progress">In progress</option>
            <option value="Completed">Completed</option>
            <option value="Cancelled">Cancelled</option>
          </select>
          <button type="button" className="btn btn-primary" onClick={() => setShowForm((v) => !v)}>{showForm ? "Close" : "+ New batch"}</button>
        </div>
      </div>
      <StockHelp
        id="batches"
        steps={[
          "Press \"+ New batch\", choose the plant and write how many plants you want to make.",
          "Open the batch and write how many seeds you took from the store (\"Give seeds to this batch\").",
          "When the plants are ready, press \"Finish the batch\" and write what really happened: seeds used, seeds put back, healthy plants, rejected plants.",
          "The healthy plants you accept go into Ready Plants by themselves. If you made extra, the extra stay in stock for the next order.",
        ]}
        note="You never have to guess: write the real numbers. A batch can't be finished until every seed is accounted for."
      />
      {error && <div className="alert alert-error">{error}</div>}

      {showForm && (
        <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
          <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Start a new batch</h2>
          <form onSubmit={create} className="stock-form-grid">
            <label>
              1. Which plant will you make?
              <select className="form-control" required value={form.plant_id} onChange={(e) => { setForm({ ...form, plant_id: e.target.value, variant_id: "", seed_item_id: "" }); setPicked({}); }}>
                <option value="">Choose a plant...</option>
                {plants.map((p) => (<option key={p.id} value={p.id}>{p.name}</option>))}
              </select>
            </label>
            {needsTray && (
              <label>
                2. Which tray size?
                <select className="form-control" required value={form.variant_id} onChange={(e) => { setForm({ ...form, variant_id: e.target.value }); setPicked({}); }}>
                  <option value="">Choose a tray...</option>
                  {plant.variants.map((v) => (<option key={v.id} value={v.id}>{v.tray_size} plants per tray</option>))}
                </select>
              </label>
            )}
            <label>
              Which seeds will you use? (optional)
              <select className="form-control" value={form.seed_item_id} onChange={(e) => setForm({ ...form, seed_item_id: e.target.value })}>
                <option value="">No seeds (e.g. bought seedlings)</option>
                {matchingSeeds.map((s) => (<option key={s.id} value={s.id}>{s.name} - {num(s.balance)} in store</option>))}
              </select>
            </label>
            <label>
              How many PLANTS do you want to make?
              <input className="form-control" required inputMode="numeric" value={form.planned_quantity} onChange={(e) => setForm({ ...form, planned_quantity: sanitizeQuantityText(e.target.value, 100000000) })} />
            </label>
            {row && (
              <div className="stock-suggest">
                <strong>What the system sees for this plant{tray ? ` (${tray.tray_size}-plant tray)` : ""}:</strong>
                <div>Waiting orders need <b>{num(row.outstanding_demand)}</b> · ready now <b>{num(row.available_stock)}</b> · already being made <b>{num(row.in_production)}</b></div>
                <div>Still to make: <b>{num(row.to_produce)}</b> {row.unit}{tray && row.to_produce ? ` (= ${num(suggestion)} plants)` : ""}</div>
                {suggestion > 0 && (
                  <button type="button" className="btn btn-sm btn-outline dark" onClick={() => setForm({ ...form, planned_quantity: String(suggestion) })}>Use {num(suggestion)} plants</button>
                )}
              </div>
            )}
            {lines.length > 0 && (
              <div className="stock-suggest">
                <strong>Which waiting orders is this batch for? (optional, just a note)</strong>
                {lines.map((l) => (
                  <label key={`${l.kind}-${l.item_id}`} className="stock-check">
                    <input type="checkbox" checked={!!picked[`${l.kind}-${l.item_id}`]} onChange={(e) => setPicked({ ...picked, [`${l.kind}-${l.item_id}`]: e.target.checked })} />
                    {l.number} - {l.customer || "customer"} - waiting for {num(l.pending)}
                  </label>
                ))}
              </div>
            )}
            <label>
              Note (optional)
              <input className="form-control" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </label>
            <div><button className="btn btn-primary" disabled={busy || !form.plant_id || (needsTray && !form.variant_id) || !form.planned_quantity}>{busy ? "Creating..." : "Create batch"}</button></div>
          </form>
          <Hint>Creating a batch does not use any seeds yet. It only says "we plan to make this".</Hint>
        </div>
      )}

      {!batches && !error ? (
        <Loading />
      ) : shown.length === 0 ? (
        <Empty>No batches here yet. Press "+ New batch" to plan one.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr><th>Batch</th><th>Plant</th><th>Status</th><th>Plan (plants)</th><th>Seeds given</th><th>Healthy plants</th><th>Added to ready stock</th><th /></tr>
            </thead>
            <tbody>
              {shown.map((b) => (
                <tr key={b.id}>
                  <td><strong>{b.batch_number}</strong></td>
                  <td>{b.plant_name}</td>
                  <td><span className={`badge ${STATUS_BADGE[b.status] || "badge-muted"}`}>{b.status === "Draft" ? "Planned" : b.status}</span></td>
                  <td>{num(b.planned_quantity)}</td>
                  <td>{b.seed_item_id ? num(b.seeds_issued) : "-"}</td>
                  <td>{b.status === "Completed" ? num(b.healthy_plants) : "-"}</td>
                  <td>{b.status === "Completed" ? `${num(b.accepted_units)} ${b.unit}` : "-"}</td>
                  <td><Link className="btn btn-sm btn-outline dark" to={`/admin/stock/batches/${b.id}`}>Open</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
