import { useEffect, useState } from "react";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import { Hint, StockHelp, num } from "../../stock/stockUi";
import { sanitizeQuantityText } from "../../../utils/quantity";

// Seeds (beej): what is in the store, what is out with open batches.
export default function SeedStock() {
  const [seeds, setSeeds] = useState(null);
  const [plants, setPlants] = useState([]);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [form, setForm] = useState({ name: "", plant_id: "", opening_quantity: "" });
  const [action, setAction] = useState(null); // { id, kind: "receive" | "damaged" }
  const [qty, setQty] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    api.get("/admin/stock/seeds").then(setSeeds).catch((e) => setError(e.message || "Could not load the seeds."));
  }
  useEffect(() => {
    load();
    api.get("/admin/plants").then(setPlants).catch(() => {});
  }, []);

  async function addItem(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.post("/admin/stock/seeds", { name: form.name, plant_id: form.plant_id ? Number(form.plant_id) : null, opening_quantity: Number(form.opening_quantity || 0) });
      setForm({ name: "", plant_id: "", opening_quantity: "" });
      setMsg("Seed item added.");
      load();
    } catch (err) {
      setError(err.message || "Could not add the seed item.");
    } finally {
      setBusy(false);
    }
  }

  async function submitAction(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.post(`/admin/stock/seeds/${action.id}/${action.kind}`, { quantity: Number(qty), notes: note, request_id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}` });
      setMsg(action.kind === "receive" ? "Seeds added to the store." : "Damaged seeds removed from the store.");
      setAction(null);
      setQty("");
      setNote("");
      load();
    } catch (err) {
      setError(err.message || "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="admin-page-head">
        <h1>Seeds (beej)</h1>
      </div>
      <StockHelp
        id="seeds"
        steps={[
          "Add each kind of seed once (for example \"Tomato 1057 seeds\") and say which plant it grows into.",
          "When new seeds arrive, press \"Seeds received\" and write how many.",
          "When the nursery team takes seeds for preparing plants, that happens inside a Production Batch (the store count goes down by itself).",
          "If some seeds are spoiled in the store, press \"Seeds damaged\" and write the reason.",
        ]}
        note={'"With open batches" means seeds already given to a batch that is not finished yet.'}
      />
      {error && <div className="alert alert-error">{error}</div>}
      {msg && <div className="alert alert-success" role="status">{msg}</div>}

      <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
        <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Add a new seed item</h2>
        <form onSubmit={addItem} className="stock-form-row">
          <label>
            Seed name
            <input className="form-control" required maxLength={150} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Tomato 1057 seeds" />
          </label>
          <label>
            Grows into this plant
            <select className="form-control" value={form.plant_id} onChange={(e) => setForm({ ...form, plant_id: e.target.value })}>
              <option value="">(not decided)</option>
              {plants.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </label>
          <label>
            Seeds you have right now
            <input className="form-control" inputMode="numeric" value={form.opening_quantity} onChange={(e) => setForm({ ...form, opening_quantity: sanitizeQuantityText(e.target.value, 100000000) })} placeholder="0" />
          </label>
          <button className="btn btn-primary" disabled={busy || !form.name.trim()}>Add seed item</button>
        </form>
      </div>

      {!seeds && !error ? (
        <Loading />
      ) : seeds && seeds.length === 0 ? (
        <Empty>No seed items yet. Add your first one above.</Empty>
      ) : seeds ? (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr><th>Seed</th><th>Grows into</th><th>In the store</th><th>With open batches</th><th>What do you want to do?</th></tr>
            </thead>
            <tbody>
              {seeds.map((s) => (
                <tr key={s.id}>
                  <td><strong>{s.name}</strong></td>
                  <td>{plants.find((p) => p.id === s.plant_id)?.name || "-"}</td>
                  <td><strong>{num(s.balance)}</strong> {s.unit}</td>
                  <td>{num(s.with_open_batches)}</td>
                  <td>
                    <button type="button" className="btn btn-sm btn-primary" onClick={() => { setAction({ id: s.id, kind: "receive", name: s.name }); setMsg(""); }}>Seeds received</button>{" "}
                    <button type="button" className="btn btn-sm btn-outline dark" onClick={() => { setAction({ id: s.id, kind: "damaged", name: s.name }); setMsg(""); }}>Seeds damaged</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {action && (
        <div className="admin-form-card" style={{ maxWidth: 560, marginTop: 20 }}>
          <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>{action.kind === "receive" ? "Seeds received" : "Seeds damaged"}: {action.name}</h2>
          <form onSubmit={submitAction}>
            <div className="form-group">
              <label htmlFor="seed-qty">{action.kind === "receive" ? "How many seeds came in?" : "How many seeds are damaged?"}</label>
              <input id="seed-qty" className="form-control" required inputMode="numeric" value={qty} onChange={(e) => setQty(sanitizeQuantityText(e.target.value, 100000000))} autoFocus />
            </div>
            <div className="form-group">
              <label htmlFor="seed-note">{action.kind === "receive" ? "Note (supplier, bill number...) - optional" : "Why? (required)"}</label>
              <input id="seed-note" className="form-control" required={action.kind === "damaged"} value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            <button className="btn btn-primary" disabled={busy || !qty}>{busy ? "Saving..." : "Save"}</button>{" "}
            <button type="button" className="btn btn-outline dark" onClick={() => setAction(null)}>Cancel</button>
          </form>
          <Hint>Every change is written in the Movements list, with your name and the time.</Hint>
        </div>
      )}
    </div>
  );
}
