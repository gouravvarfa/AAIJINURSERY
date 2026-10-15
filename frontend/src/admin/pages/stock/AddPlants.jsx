import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../../api";
import { Hint, StockHelp, num } from "../../stock/stockUi";
import { sanitizeQuantityText } from "../../../utils/quantity";

const newId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

// Add plants I made: one short form. The good plants go straight into "Ready now".
export default function AddPlants() {
  const [params] = useSearchParams();
  const [plants, setPlants] = useState([]);
  const [form, setForm] = useState({ plant_id: params.get("plant") || "", variant_id: params.get("variant") || "", good: "", bad: "", seeds: "", notes: "" });
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const requestId = useRef(newId()); // the same id for every click of one form, so a double click cannot add twice

  useEffect(() => {
    api.get("/admin/plants").then(setPlants).catch(() => {});
  }, []);

  const plant = plants.find((p) => String(p.id) === String(form.plant_id));
  const needsTray = Boolean(plant?.variants?.length);
  const tray = plant?.variants?.find((v) => String(v.id) === String(form.variant_id));
  const good = Number(form.good || 0);
  const trays = tray ? Math.floor(good / tray.tray_size) : 0;
  const loose = tray ? good % tray.tray_size : 0;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const numSet = (k) => (e) => setForm({ ...form, [k]: sanitizeQuantityText(e.target.value, 100000000) });

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api.post("/admin/stock/add-plants", {
        plant_id: Number(form.plant_id),
        variant_id: form.variant_id ? Number(form.variant_id) : null,
        good_plants: good,
        rejected_plants: Number(form.bad || 0),
        seeds_used: form.seeds === "" ? null : Number(form.seeds),
        notes: form.notes,
        request_id: requestId.current,
      });
      setResult({ ...r, name: plant.name });
    } catch (err) {
      setError(err.message || "Could not add the plants.");
    } finally {
      setBusy(false);
    }
  }

  function again() {
    requestId.current = newId();
    setResult(null);
    setForm({ plant_id: "", variant_id: "", good: "", bad: "", seeds: "", notes: "" });
  }

  if (result) {
    return (
      <div>
        <div className="admin-page-head"><h1>Add plants I made</h1></div>
        <div className="admin-form-card" style={{ maxWidth: 640 }}>
          <h2 style={{ marginTop: 0, color: "#1f7a45" }}>✓ Done</h2>
          <p>{result.already_added ? "These plants were already added (nothing was added twice)." : <>Added <strong>{num(result.added_units)} {result.unit}</strong> of <strong>{result.name}</strong> to stock.</>}</p>
          <p>Ready now: <strong>{num(result.new_ready)} {result.unit}</strong>.{result.loose_plants > 0 && <> {num(result.loose_plants)} loose plants did not fill a tray and are kept aside.</>}</p>
          <Link className="btn btn-primary" to="/admin/stock/allocations">Give to waiting orders</Link>{" "}
          <button type="button" className="btn btn-outline dark" onClick={again}>Add more plants</button>{" "}
          <Link className="btn btn-outline dark" to="/admin/stock-demand">Back to Stock</Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="admin-page-head"><h1>Add plants I made</h1></div>
      <StockHelp
        id="add-plants"
        steps={["Choose the plant.", "Write how many GOOD plants you got (and bad ones, if any).", "Press \"Add to stock\". Done. The good plants are now in Ready now."]}
        note="Write the real count. Seeds used is optional (it only helps to see how many seeds became good plants)."
      />
      {error && <div className="alert alert-error">{error}</div>}
      <div className="admin-form-card" style={{ maxWidth: 640 }}>
        <form onSubmit={submit} className="stock-form-grid">
          <label>
            Which plant?
            <select className="form-control" required value={form.plant_id} onChange={(e) => setForm({ ...form, plant_id: e.target.value, variant_id: "" })}>
              <option value="">Choose a plant...</option>
              {plants.map((p) => (<option key={p.id} value={p.id}>{p.name}</option>))}
            </select>
          </label>
          {needsTray && (
            <label>
              Which tray size?
              <select className="form-control" required value={form.variant_id} onChange={set("variant_id")}>
                <option value="">Choose a tray...</option>
                {plant.variants.map((v) => (<option key={v.id} value={v.id}>{v.tray_size} plants per tray</option>))}
              </select>
            </label>
          )}
          <label>
            How many GOOD plants did you get?
            <input className="form-control" required inputMode="numeric" value={form.good} onChange={numSet("good")} />
          </label>
          {tray && good > 0 && (
            <p className="stock-hint" style={{ margin: 0 }}>
              {good} plants = <strong>{trays} trays</strong> of {tray.tray_size}{loose > 0 ? <>, and <strong>{loose} loose plants</strong> that do not fill a tray are kept aside</> : null}.
            </p>
          )}
          <label>
            How many bad / dead plants? (optional)
            <input className="form-control" inputMode="numeric" value={form.bad} onChange={numSet("bad")} />
          </label>
          <label>
            How many seeds did you use? (optional)
            <input className="form-control" inputMode="numeric" value={form.seeds} onChange={numSet("seeds")} />
          </label>
          <label>
            Note (optional)
            <input className="form-control" value={form.notes} onChange={set("notes")} />
          </label>
          <div>
            <button className="btn btn-primary" disabled={busy || !form.plant_id || (needsTray && !form.variant_id) || good < 1}>{busy ? "Adding..." : "Add to stock"}</button>{" "}
            <Link className="btn btn-outline dark" to="/admin/stock-demand">Cancel</Link>
          </div>
        </form>
        <Hint>Every addition is saved with your name and the time.</Hint>
      </div>
    </div>
  );
}
