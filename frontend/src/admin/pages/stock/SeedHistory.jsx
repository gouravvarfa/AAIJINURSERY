import { useEffect, useState } from "react";
import { api } from "../../../api";
import { sanitizeQuantityText } from "../../../utils/quantity";
import { num } from "../../stock/stockUi";

const BADGE = { Pending: "badge-gold", "In Progress": "badge-accent", Completed: "badge-muted" };
const fmt = (iso) => (iso ? new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "-");
const pct = (e) => (e.seeds_given > 0 ? Math.round(((e.prepared_plants + e.extra_plants) / e.seeds_given) * 100) : 0);

// Customer-wise history of every seed entry: what came out good, extra and bad. Add / edit / remove here.
export default function SeedHistory({ plants, version, onChanged }) {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState(null); // { kind: "entry" | "line", entry, line, ...fields }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    const t = setTimeout(() => {
      api.get(`/admin/stock/seed-entries/history${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`).then(setData).catch((e) => setError(e.message || "Could not load the history."));
    }, q ? 250 : 0);
    return () => clearTimeout(t);
  }, [q, version]);

  async function run(fn, done) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await fn();
      setMsg(done);
      setEdit(null);
      onChanged?.();
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const base = "/admin/stock/seed-entries";
  const saveEntry = (e) => {
    e.preventDefault();
    const body = { seeds_given: Number(edit.seeds), entry_date: edit.date, reference: edit.reference, notes: edit.notes };
    if (edit.wanted) body.wanted_plants = Number(edit.wanted);
    if (!edit.entry.log.length) { body.plant_id = Number(edit.plant_id); body.variant_id = edit.variant_id ? Number(edit.variant_id) : null; }
    run(() => api.put(`${base}/${edit.entry.id}`, body), `${edit.entry.entry_number} saved.`);
  };
  const saveLine = (e) => {
    e.preventDefault();
    run(() => api.put(`${base}/${edit.entry.id}/updates/${edit.line.id}`, { prepared_plants: Number(edit.good || 0), extra_plants: Number(edit.extra || 0), rejected_plants: Number(edit.bad || 0), notes: edit.notes }), "Update saved.");
  };
  const removeLine = (entry, line) => {
    if (window.confirm("Remove this update? Any extra plants it added will be taken back from Ready now.")) run(() => api.del(`${base}/${entry.id}/updates/${line.id}`), "Update removed.");
  };
  const removeEntry = (entry) => {
    if (window.confirm(`Delete ${entry.entry_number}? This cannot be undone.`)) run(() => api.del(`${base}/${entry.id}`), `${entry.entry_number} deleted.`);
  };
  const handOver = (entry) => {
    const left = entry.remaining > 0 ? ` The ${num(entry.remaining)} seeds still left are counted as not grown.` : "";
    if (window.confirm(`Handed over ${entry.entry_number}? Use this when the plants were given to ${entry.customer_name}. They then leave the stock count.${left}`)) run(() => api.post(`${base}/${entry.id}/handover`, { request_id: `${Date.now()}${Math.random().toString(36).slice(2, 10)}` }), `${entry.entry_number} marked as handed over.`);
  };
  const openProduce = (entry) => setEdit({ kind: "produce", entry, wanted: entry.wanted_plants ? String(entry.wanted_plants) : "", good: "", bad: "", notes: "", rid: `${Date.now()}${Math.random().toString(36).slice(2, 10)}` });
  const saveProduce = (e) => {
    e.preventDefault();
    const en = edit.entry;
    const good = Number(edit.good || 0);
    const bad = Number(edit.bad || 0);
    const used = en.prepared_plants + en.extra_plants + en.rejected_plants + good + bad;
    let raise = false;
    if (used > en.seeds_given) {
      if (!window.confirm(`You wrote more plants (${num(used)}) than seeds given (${num(en.seeds_given)}). Save anyway and raise "seeds given" to ${num(used)}?`)) return;
      raise = true;
    }
    const body = { good_plants: good, rejected_plants: bad, notes: edit.notes, raise_seeds: raise, request_id: edit.rid };
    if (edit.wanted && Number(edit.wanted) !== en.wanted_plants) body.wanted_plants = Number(edit.wanted);
    run(() => api.post(`${base}/${en.id}/update`, body), `${en.entry_number} updated.`);
  };
  const wantedN = Number(edit?.wanted || 0);
  const goodN = Number(edit?.good || 0);
  const forCustomer = edit?.kind === "produce" ? Math.min(goodN, Math.max(wantedN - edit.entry.prepared_plants, 0)) : 0;
  const openEntryEdit = (entry) => setEdit({ kind: "entry", entry, seeds: String(entry.seeds_given), wanted: entry.wanted_plants ? String(entry.wanted_plants) : "", date: entry.entry_date || "", reference: entry.reference, notes: entry.notes, plant_id: String(entry.plant_id), variant_id: entry.variant_id ? String(entry.variant_id) : "" });
  const openLineEdit = (entry, line) => setEdit({ kind: "line", entry, line, good: String(line.prepared), extra: String(line.extra), bad: String(line.rejected), notes: line.notes });
  const numField = (k) => (e) => setEdit({ ...edit, [k]: sanitizeQuantityText(e.target.value, 100000000) });
  const editPlant = plants.find((p) => String(p.id) === String(edit?.plant_id));

  return (
    <div className="seed-hist">
      <div className="seed-hist-head">
        <h3>Customer history</h3>
        <input className="form-control" placeholder="Search customer or entry..." value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search customer seeds" />
      </div>
      {msg && <div className="alert alert-success" role="status">{msg}</div>}
      {error && <div className="alert alert-error">{error}</div>}
      {edit && (
        <div className="seed-form seed-edit">
          <h4>{edit.kind === "produce" ? `Update plants of ${edit.entry.entry_number}: ${edit.entry.customer_name}` : edit.kind === "entry" ? `Edit ${edit.entry.entry_number}: ${edit.entry.customer_name}` : `Edit update of ${edit.entry.entry_number} (${fmt(edit.line.at)})`}</h4>
          {edit.kind === "produce" ? (
            <form onSubmit={saveProduce} className="stock-form-grid">
              <p className="stock-hint" style={{ margin: 0 }}>Write only the NEW numbers since the last update. {num(edit.entry.remaining)} seeds are still left.</p>
              <label>Plants the customer wants
                <input className="form-control" required inputMode="numeric" value={edit.wanted} onChange={numField("wanted")} placeholder="e.g. 500" />
              </label>
              <label>Good plants that came out
                <input className="form-control" inputMode="numeric" value={edit.good} onChange={numField("good")} />
              </label>
              <label>Bad / dead plants (optional)
                <input className="form-control" inputMode="numeric" value={edit.bad} onChange={numField("bad")} />
              </label>
              {goodN > 0 && wantedN > 0 && (
                <p className="seed-split" role="status">
                  <strong>{num(forCustomer)}</strong> kept for {edit.entry.customer_name} (in Stock as Allocated, not for sale)
                  {goodN - forCustomer > 0 ? <>, and <strong>{num(goodN - forCustomer)}</strong> extra go to <strong>Ready now</strong> (for sale)</> : null}.
                  {edit.entry.prepared_plants + forCustomer < wantedN ? ` Still to give: ${num(wantedN - edit.entry.prepared_plants - forCustomer)}.` : ""}
                </p>
              )}
              <label>Notes (optional)<input className="form-control" maxLength={1000} value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} /></label>
              <div><button className="btn btn-primary" disabled={busy || (goodN + Number(edit.bad || 0) < 1) || !wantedN}>{busy ? "Saving..." : "Save"}</button>{" "}<button type="button" className="btn btn-outline dark" onClick={() => setEdit(null)}>Cancel</button></div>
            </form>
          ) : edit.kind === "entry" ? (
            <form onSubmit={saveEntry} className="stock-form-grid">
              {!edit.entry.log.length && (
                <>
                  <label>Plant
                    <select className="form-control" required value={edit.plant_id} onChange={(e) => setEdit({ ...edit, plant_id: e.target.value, variant_id: "" })}>
                      {plants.map((p) => (<option key={p.id} value={p.id}>{p.name}</option>))}
                    </select>
                  </label>
                  {editPlant?.variants?.length > 0 && (
                    <label>Tray size
                      <select className="form-control" required value={edit.variant_id} onChange={(e) => setEdit({ ...edit, variant_id: e.target.value })}>
                        <option value="">Choose a tray...</option>
                        {editPlant.variants.map((v) => (<option key={v.id} value={v.id}>{v.tray_size} plants per tray</option>))}
                      </select>
                    </label>
                  )}
                </>
              )}
              <label>Seeds given<input className="form-control" required inputMode="numeric" value={edit.seeds} onChange={numField("seeds")} /></label>
              <label>Plants the customer wants<input className="form-control" inputMode="numeric" value={edit.wanted || ""} onChange={numField("wanted")} /></label>
              <label>Entry date<input className="form-control" type="date" required value={edit.date} onChange={(e) => setEdit({ ...edit, date: e.target.value })} /></label>
              <label>Reference<input className="form-control" maxLength={80} value={edit.reference} onChange={(e) => setEdit({ ...edit, reference: e.target.value })} /></label>
              <label>Notes<input className="form-control" maxLength={1000} value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} /></label>
              <div><button className="btn btn-primary" disabled={busy || !edit.seeds}>{busy ? "Saving..." : "Save"}</button>{" "}<button type="button" className="btn btn-outline dark" onClick={() => setEdit(null)}>Cancel</button></div>
            </form>
          ) : (
            <form onSubmit={saveLine} className="stock-form-grid">
              <label>Good plants for the customer<input className="form-control" inputMode="numeric" value={edit.good} onChange={numField("good")} /></label>
              <label>Extra plants (go to Ready now)<input className="form-control" inputMode="numeric" value={edit.extra} onChange={numField("extra")} /></label>
              <label>Bad / dead plants<input className="form-control" inputMode="numeric" value={edit.bad} onChange={numField("bad")} /></label>
              <label>Notes<input className="form-control" maxLength={1000} value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} /></label>
              <div><button className="btn btn-primary" disabled={busy}>{busy ? "Saving..." : "Save"}</button>{" "}<button type="button" className="btn btn-outline dark" onClick={() => setEdit(null)}>Cancel</button></div>
            </form>
          )}
        </div>
      )}
      {!data ? null : data.customers.length === 0 ? <p className="stock-hint">{q ? "No customer matches." : "No seed entries yet."}</p> : (
        <div className="seed-custs">
          {data.customers.map((c) => (
            <details key={c.contact_id} className="seed-cust" open={Boolean(q.trim()) && data.customers.length <= 2}>
              <summary>
                <div className="seed-cust-name"><strong>{c.name}</strong>{c.phone && <small>{c.phone}</small>}</div>
                <div className="seed-cust-nums">
                  <span><b>{num(c.seeds)}</b> seeds</span>
                  <span className="good"><b>{num(c.good)}</b> good</span>
                  <span className="extra"><b>{num(c.extra)}</b> extra</span>
                  <span className="bad"><b>{num(c.rejected)}</b> bad</span>
                  <span><b>{num(c.remaining)}</b> left</span>
                </div>
              </summary>
              <div className="seed-cust-body">
                {c.entries.map((e) => (
                  <div key={e.id} className="seed-ent">
                    <div className="seed-ent-top">
                      <div>
                        <strong>{e.plant_name}</strong>
                        <small>{e.entry_number} · {e.entry_date}{e.reference ? ` · ${e.reference}` : ""}</small>
                      </div>
                      <span>
                        <span className={`badge ${BADGE[e.status] || "badge-muted"}`}>{e.status_label}</span>
                        {" "}
                        {e.handed_over ? <span className="badge badge-muted">Handed over</span> : e.prepared_plants > 0 ? <span className="badge badge-accent">Plants with us</span> : null}
                      </span>
                    </div>
                    <div className="seed-ent-nums">
                      <div><span>{num(e.seeds_given)}</span>Seeds given</div>
                      {e.wanted_plants ? <div><span>{num(e.wanted_plants)}</span>Customer wants</div> : null}
                      <div className="good"><span>{num(e.prepared_plants)}</span>Good (for customer)</div>
                      <div className="extra"><span>{num(e.extra_plants)}</span>Extra</div>
                      <div className="bad"><span>{num(e.rejected_plants)}</span>Bad</div>
                      <div><span>{num(e.remaining)}</span>Left</div>
                      <div><span>{pct(e)}%</span>Came out good</div>
                    </div>
                    {e.notes && <p className="stock-hint">Note: {e.notes}</p>}
                    {e.log.length > 0 && (
                      <div className="admin-table-wrap">
                        <table className="admin-table seed-log">
                          <thead><tr><th>Date</th><th className="num">Good</th><th className="num">Extra</th><th className="num">Bad</th><th>Note</th><th /></tr></thead>
                          <tbody>
                            {e.log.map((l) => (
                              <tr key={l.id}>
                                <td>{fmt(l.at)}{l.finished && <small> (closed)</small>}</td>
                                <td className="num">{num(l.prepared)}</td>
                                <td className="num">{num(l.extra)}</td>
                                <td className="num">{num(l.rejected)}</td>
                                <td>{l.notes}</td>
                                <td style={{ whiteSpace: "nowrap" }}>
                                  <button type="button" className="btn btn-sm btn-outline dark" onClick={() => openLineEdit(e, l)}>Edit</button>{" "}
                                  <button type="button" className="btn btn-sm btn-outline dark" disabled={busy} onClick={() => removeLine(e, l)}>Remove</button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                    <div className="seed-ent-actions">
                      {e.status !== "Completed" && <button type="button" className="btn btn-sm btn-primary" onClick={() => openProduce(e)}>Update plants</button>}
                      <button type="button" className="btn btn-sm btn-outline dark" onClick={() => openEntryEdit(e)}>Edit entry</button>
                      {!e.handed_over && <button type="button" className="btn btn-sm btn-outline dark" disabled={busy} onClick={() => handOver(e)}>{e.status === "Completed" ? "Handed over" : "Handed over / Close"}</button>}
                      {e.log.length === 0 && <button type="button" className="btn btn-sm btn-outline dark" disabled={busy} onClick={() => removeEntry(e)}>Delete</button>}
                    </div>
                  </div>
                ))}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
