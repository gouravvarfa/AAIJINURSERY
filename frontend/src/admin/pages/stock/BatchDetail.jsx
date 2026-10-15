import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../../api";
import { Loading } from "../../../components/Loading";
import { formatIst } from "../../communications/time";
import { Hint, MOVEMENT_LABEL, STATUS_BADGE, StockHelp, num } from "../../stock/stockUi";
import { sanitizeQuantityText } from "../../../utils/quantity";

const toNum = (v) => (v === "" ? 0 : Number(v));

function Steps({ status, hasSeeds, issued }) {
  const done = status === "Completed";
  const items = [
    { label: "1. Plan made", ok: true },
    { label: hasSeeds ? "2. Seeds given" : "2. (no seeds)", ok: done || issued > 0 || !hasSeeds },
    { label: "3. Finish and count", ok: done },
  ];
  return (
    <ol className="stock-steps" aria-label="Progress">
      {items.map((s) => (
        <li key={s.label} className={s.ok ? "done" : ""}>{s.ok ? "✓ " : ""}{s.label}</li>
      ))}
    </ol>
  );
}

export default function BatchDetail() {
  const { id } = useParams();
  const [b, setB] = useState(null);
  const [seed, setSeed] = useState(null);
  const [suggest, setSuggest] = useState(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [issueQty, setIssueQty] = useState("");
  const [f, setF] = useState({ consumed: "", returned: "", wasted: "", healthy: "", rejected: "", accepted: "", notes: "" });

  function load() {
    api.get(`/admin/stock/batches/${id}`).then((d) => {
      setB(d);
      if (d.seed_item_id) api.get("/admin/stock/seeds").then((all) => setSeed(all.find((s) => s.id === d.seed_item_id) || null)).catch(() => {});
      if (d.status === "Completed") api.get(`/admin/stock/batches/${id}/suggest`).then(setSuggest).catch(() => {});
    }).catch((e) => setError(e.message || "Could not load this batch."));
  }
  useEffect(load, [id]);

  const open = b && (b.status === "Draft" || b.status === "In Progress");
  const hasSeeds = Boolean(b?.seed_item_id);
  const accounted = toNum(f.consumed) + toNum(f.returned) + toNum(f.wasted);
  const seedsOk = !hasSeeds || accounted === b?.seeds_issued;
  const healthy = toNum(f.healthy);
  const accepted = f.accepted === "" ? healthy : toNum(f.accepted);
  const tray = b?.tray_size;
  const trays = tray ? Math.floor(accepted / tray) : accepted;
  const loose = tray ? accepted % tray : 0;
  const problems = useMemo(() => {
    const p = [];
    if (hasSeeds && !seedsOk) p.push(`Seeds do not add up yet: ${num(b.seeds_issued)} were given, you have written ${num(accounted)}.`);
    if (accepted > healthy) p.push("Accepted plants can't be more than the healthy plants.");
    if (hasSeeds && healthy + toNum(f.rejected) > toNum(f.consumed)) p.push("Healthy + rejected plants can't be more than the seeds used.");
    return p;
  }, [hasSeeds, seedsOk, accepted, healthy, f.rejected, f.consumed, accounted, b]);

  async function run(fn, ok) {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      await fn();
      setMsg(ok);
      load();
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  if (error && !b) return <div className="alert alert-error">{error}</div>;
  if (!b) return <Loading />;

  const issue = () => run(async () => {
    await api.post(`/admin/stock/batches/${id}/issue-seeds`, { quantity: Number(issueQty), request_id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}` });
    setIssueQty("");
  }, "Seeds given to this batch. The seed store count went down.");
  const finish = () => {
    if (!window.confirm(`Finish ${b.batch_number}? ${num(accepted)} plants will be added to ready stock. This cannot be undone.`)) return;
    run(() => api.post(`/admin/stock/batches/${id}/complete`, {
      seeds_consumed: toNum(f.consumed), seeds_returned: toNum(f.returned), seeds_wasted: toNum(f.wasted),
      healthy_plants: healthy, rejected_plants: toNum(f.rejected), accepted_plants: accepted, notes: f.notes,
    }), "Batch finished. The accepted plants are now in ready stock.");
  };
  const cancel = () => {
    if (!window.confirm(`Cancel ${b.batch_number}? Any seeds already given will be put back in the store.`)) return;
    run(() => api.post(`/admin/stock/batches/${id}/cancel`), "Batch cancelled.");
  };
  const numInput = (key, label, help) => (
    <label key={key}>
      {label}
      <input className="form-control" inputMode="numeric" value={f[key]} onChange={(e) => setF({ ...f, [key]: sanitizeQuantityText(e.target.value, 100000000) })} />
      {help && <small>{help}</small>}
    </label>
  );

  return (
    <div>
      <div className="admin-page-head">
        <div>
          <h1 style={{ marginBottom: 4 }}>{b.batch_number}: {b.plant_name}</h1>
          <span className={`badge ${STATUS_BADGE[b.status] || "badge-muted"}`}>{b.status === "Draft" ? "Planned" : b.status}</span>
        </div>
        <Link className="btn btn-sm btn-outline dark" to="/admin/stock/batches">&larr; All batches</Link>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {msg && <div className="alert alert-success" role="status">{msg}</div>}
      <Steps status={b.status} hasSeeds={hasSeeds} issued={b.seeds_issued} />

      <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
        <div className="stock-facts">
          <div><span>Plan</span><strong>{num(b.planned_quantity)} plants</strong>{tray && <small>= {num(b.planned_units)} trays of {tray}</small>}</div>
          <div><span>Seeds</span><strong>{hasSeeds ? b.seed_name : "none"}</strong></div>
          <div><span>Seeds given</span><strong>{num(b.seeds_issued)}</strong></div>
          {b.status === "Completed" && (<>
            <div><span>Seeds used</span><strong>{num(b.seeds_consumed)}</strong></div>
            <div><span>Put back</span><strong>{num(b.seeds_returned)}</strong></div>
            <div><span>Healthy plants</span><strong>{num(b.healthy_plants)}</strong></div>
            <div><span>Rejected</span><strong>{num(b.rejected_plants)}</strong></div>
            <div><span>Added to ready stock</span><strong>{num(b.accepted_units)} {b.unit}</strong>{b.loose_plants > 0 && <small>{num(b.loose_plants)} loose plants kept aside</small>}</div>
          </>)}
        </div>
        {b.notes && <Hint>Note: {b.notes}</Hint>}
      </div>

      {open && hasSeeds && (
        <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
          <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Step 2: Give seeds to this batch</h2>
          <p className="stock-hint">In the store now: <strong>{seed ? num(seed.balance) : "..."}</strong> {seed?.unit}. You can do this more than once.</p>
          <div className="stock-form-row">
            <label>
              How many seeds are you taking out?
              <input className="form-control" inputMode="numeric" value={issueQty} onChange={(e) => setIssueQty(sanitizeQuantityText(e.target.value, 100000000))} />
            </label>
            <button type="button" className="btn btn-primary" disabled={busy || !issueQty || Number(issueQty) < 1} onClick={issue}>Give seeds to this batch</button>
          </div>
        </div>
      )}

      {open && (!hasSeeds || b.seeds_issued > 0) && (
        <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
          <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Step 3: Finish the batch (write what really happened)</h2>
          {hasSeeds && (<>
            <h3 className="stock-sub">Seeds: {num(b.seeds_issued)} were given. Where did they go?</h3>
            <div className="stock-form-row">
              {numInput("consumed", "Seeds used (sown)")}
              {numInput("returned", "Seeds put back in the store")}
              {numInput("wasted", "Seeds spoiled / thrown")}
            </div>
            <p className={seedsOk ? "stock-ok" : "stock-warn"}>{seedsOk ? "✓ Every seed is accounted for." : `Seeds written: ${num(accounted)} of ${num(b.seeds_issued)}. ${accounted < b.seeds_issued ? `${num(b.seeds_issued - accounted)} still to account for.` : "That is more than were given."}`}</p>
          </>)}
          <h3 className="stock-sub">Plants: what did you get?</h3>
          <div className="stock-form-row">
            {numInput("healthy", "Healthy plants made", "Good plants that are alive and fit to sell")}
            {numInput("rejected", "Rejected / dead plants", "Not fit to sell")}
            {numInput("accepted", "Plants accepted into ready stock", `Leave empty to accept all ${num(healthy)} healthy plants`)}
          </div>
          <p className="stock-hint">
            You will add <strong>{num(accepted)} plants</strong> to Ready Plants{tray ? <>: <strong>{num(trays)} trays</strong> of {tray}{loose > 0 ? <>, and <strong>{num(loose)} loose plants</strong> that do not fill a tray are kept aside (not counted in stock)</> : null}</> : null}.
          </p>
          <label className="stock-block">
            Note (optional)
            <input className="form-control" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
          </label>
          {problems.map((p) => (<p key={p} className="stock-warn">{p}</p>))}
          <button type="button" className="btn btn-primary" disabled={busy || problems.length > 0 || f.healthy === ""} onClick={finish}>Finish the batch</button>
        </div>
      )}

      {open && <button type="button" className="btn btn-outline dark" disabled={busy} onClick={cancel}>Cancel this batch</button>}

      {b.status === "Completed" && (
        <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
          <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>What next? Give the plants to waiting orders</h2>
          {!suggest ? <p className="stock-hint">Loading...</p> : suggest.lines.length === 0 ? (
            <p className="stock-hint">No order is waiting for this plant. The {num(suggest.available_stock)} {suggest.unit} stay in ready stock for the next order.</p>
          ) : (<>
            <p className="stock-hint">Ready stock now: <strong>{num(suggest.available_stock)}</strong> {suggest.unit}. Suggested order (first come, first served). Open the order and press "Give from stock".</p>
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead><tr><th>Order</th><th>Customer</th><th>Waiting for</th><th>Suggested to give</th><th /></tr></thead>
                <tbody>
                  {suggest.lines.map((l) => (
                    <tr key={`${l.kind}-${l.item_id}`}>
                      <td>{l.order_number}</td><td>{l.customer || "-"}</td><td>{num(l.pending)}</td><td><strong>{num(l.suggested)}</strong></td>
                      <td><Link className="btn btn-sm btn-primary" to={l.link}>Open order</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {suggest.left_after > 0 && <p className="stock-hint">After these, {num(suggest.left_after)} {suggest.unit} would still be free for new orders.</p>}
          </>)}
        </div>
      )}

      {b.seed_movements?.length > 0 && (
        <div className="admin-form-card" style={{ maxWidth: "none" }}>
          <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Seed history of this batch</h2>
          <div className="admin-table-wrap"><table className="admin-table">
            <thead><tr><th>When</th><th>What</th><th>Seeds</th><th>Store before → after</th><th>By</th></tr></thead>
            <tbody>
              {b.seed_movements.map((m) => (
                <tr key={m.id}><td>{formatIst(m.at)}</td><td>{MOVEMENT_LABEL[m.type] || m.type}</td><td>{num(m.quantity)}</td><td>{num(m.before)} → {num(m.after)}</td><td>{m.by}</td></tr>
              ))}
            </tbody>
          </table></div>
        </div>
      )}
    </div>
  );
}
