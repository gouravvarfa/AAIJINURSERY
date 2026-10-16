import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";
import { StockHelp, num } from "../stock/stockUi";
import { sanitizeQuantityText } from "../../utils/quantity";
import { SeedPacketAlerts } from "./stock/SeedPackets";

// Stock: how many plants are ready, how many orders are waiting, and what to do.
function advice(r) {
  const make = r.to_produce > 0 ? { to: `/admin/stock/add?plant=${r.plant_id}&variant=${r.variant_id || ""}`, action: "Add plants" } : null;
  if (r.outstanding_demand > 0 && r.available_stock > 0) {
    return { text: r.to_produce > 0 ? `Give the ready plants to the waiting orders, then make ${num(r.to_produce)} more ${r.unit}` : "Give the ready plants to the waiting orders", tone: r.to_produce > 0 ? "red" : "orange", to: "/admin/stock/allocations", action: "Give to orders", make };
  }
  if (r.to_produce > 0) return { text: `Make ${num(r.to_produce)} more ${r.unit}`, tone: "red", ...make, make: null };
  if (r.outstanding_demand > 0) return { text: "Orders are waiting for the nursery", tone: "orange" };
  return { text: "All good", tone: "green" };
}

// "Low stock" uses the same limit the rest of the app already uses for low-stock plants (20 or fewer ready).
const LOW_LIMIT = 20;
const statusOf = (r) => (r.available_stock <= 0 ? "out" : r.available_stock <= LOW_LIMIT ? "low" : "in");
const STATUS_TEXT = { in: "In Stock", low: "Low Stock", out: "Out of Stock" };
const FILTERS = [["all", "All Plants"], ["low", "Low Stock"], ["out", "Out of Stock"], ["prod", "In Production"], ["action", "Needs action"]];

function Icon({ name }) {
  const paths = {
    seeds: "M12 3c3 3 5 6 5 9a5 5 0 0 1-10 0c0-3 2-6 5-9z",
    ready: "M5 20c0-8 4-13 14-14-1 10-6 14-14 14zM5 20l7-7",
    extra: "M12 3l2.4 5.6L20 10l-4.2 3.8L17 20l-5-3-5 3 1.2-6.2L4 10l5.6-1.4z",
    prod: "M12 7v5l3 2M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18z",
    avail: "M5 12.5l4.5 4.5L19 7.5",
    low: "M12 4l9 16H3zM12 10v4M12 17v.5",
    out: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 8v5M12 16v.5",
  };
  return <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}

function Menu({ children }) {
  return (
    <details className="sm-menu" onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) e.currentTarget.removeAttribute("open"); }}>
      <summary className="sm-more" aria-label="More actions">⋯</summary>
      <div className="sm-menu-list">{children}</div>
    </details>
  );
}

export default function StockDemand() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [seeds, setSeeds] = useState(null);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [statusSel, setStatusSel] = useState("all");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [fix, setFix] = useState(null);
  const [count, setCount] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [plants, setPlants] = useState([]);

  useEffect(() => { api.get("/admin/plants").then(setPlants).catch(() => {}); }, []);

  function load() {
    setError("");
    api.get("/admin/inventory/stock-demand").then(setData).catch((err) => setError(err.message || "Could not load the stock."));
    api.get("/admin/stock/seed-entries?status=open").then(setSeeds).catch(() => {});
  }
  useEffect(load, []);

  async function saveCount(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await api.post("/admin/stock/ready/adjust", { plant_id: fix.plant_id, variant_id: fix.variant_id, new_quantity: Number(count), reason });
      setMsg(r.changed_by === 0 ? "The count was already correct." : `Done. Ready stock changed by ${r.changed_by > 0 ? "+" : ""}${r.changed_by}.`);
      setFix(null);
      load();
    } catch (err) {
      setError(err.message || "Could not save the count.");
    } finally {
      setBusy(false);
    }
  }

  const info = Object.fromEntries(plants.map((p) => [p.id, p]));
  const growing = {}; // seeds still growing, per plant (open seed entries)
  (seeds?.items || []).forEach((i) => { growing[i.plant_id] = (growing[i.plant_id] || 0) + i.remaining; });
  const all = data?.items || [];
  const inProd = (r) => r.in_production > 0 || (growing[r.plant_id] || 0) > 0;
  const counts = {
    all: all.length,
    low: all.filter((r) => statusOf(r) === "low").length,
    out: all.filter((r) => statusOf(r) === "out").length,
    prod: all.filter(inProd).length,
    action: all.filter((r) => advice(r).tone !== "green").length,
  };
  const plantsReady = all.filter((r) => r.unit === "plants").reduce((n, r) => n + r.available_stock, 0);
  const traysReady = all.filter((r) => r.unit === "trays").reduce((n, r) => n + r.available_stock, 0);
  const st = seeds?.totals;
  const rows = all.filter((r) => {
    if (filter === "low" && statusOf(r) !== "low") return false;
    if (filter === "out" && statusOf(r) !== "out") return false;
    if (filter === "prod" && !inProd(r)) return false;
    if (filter === "action" && advice(r).tone === "green") return false;
    if (statusSel !== "all" && statusOf(r) !== statusSel) return false;
    return !q || r.name.toLowerCase().includes(q.toLowerCase());
  });
  const cards = [
    ["seeds", "Total Seeds Given", st ? num(st.seeds_given) : "-", "tone-green", "Open customer seed entries"],
    ["ready", "Plants Ready", st ? num(st.prepared) : "-", "tone-green", "Prepared for customers"],
    ["extra", "Extra Plants", st ? num(st.extra) : "-", "tone-amber", "Extra usable plants"],
    ["prod", "In Production", st ? num(st.remaining) : "-", "tone-blue", "Seeds still growing"],
    ["avail", "Available Stock", num(plantsReady), "tone-green", traysReady > 0 ? `plants + ${num(traysReady)} trays` : "plants ready now"],
    ["low", "Low Stock", num(counts.low), "tone-amber", `${LOW_LIMIT} or fewer ready`],
    ["out", "Out of Stock", num(counts.out), counts.out > 0 ? "tone-red" : "tone-green", counts.out > 0 ? "Immediate action" : "Nothing is out"],
  ];
  return (
    <div className="sm">
      <div className="sm-head">
        <div className="sm-title">
          <span className="sm-title-icon"><Icon name="ready" /></span>
          <div>
            <h1>Stock Management</h1>
            <p>Track seed orders, plant production and current stock.</p>
          </div>
        </div>
        <div className="sm-head-actions">
          <Link className="btn btn-primary sm-new" to="/admin/stock/add">+ New Stock Entry</Link>
          {data && counts.out > 0 && (
            <button type="button" className="sm-alert" onClick={() => setFilter("out")}>
              <span className="sm-alert-icon"><Icon name="out" /></span>
              <span><strong>{counts.out} {counts.out === 1 ? "Plant" : "Plants"} Out of Stock</strong><small>Need attention</small></span>
              <span aria-hidden="true">›</span>
            </button>
          )}
        </div>
      </div>
      <StockHelp
        id="stock-simple"
        title="How this works (3 easy steps)"
        steps={[
          "Look at this page: \"Ready now\" is what you can sell today. \"Orders waiting\" is what customers asked for.",
          "Plants made? Press \"Add plants\" and write how many came out good. They go into Ready now.",
          "Then open \"Orders Waiting\" and press \"Give from stock\" for each order.",
        ]}
        note={'If your count is different from the real plants in the nursery, press "Correct count" and write why.'}
      />
      {error && <div className="alert alert-error">{error}</div>}
      {msg && <div className="alert alert-success" role="status">{msg}</div>}
      <SeedPacketAlerts compact onOpen={() => navigate("/admin/stock/packets")} />
      <div className="sm-filters" role="tablist" aria-label="Filter plants">
        {FILTERS.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={filter === key} className={`sm-chip${filter === key ? " active" : ""}`} onClick={() => setFilter(key)}>
            {label}{data ? <em>{counts[key]}</em> : null}
          </button>
        ))}
        <Link className="sm-chip sm-chip-link" to="/admin/stock/allocations">Orders Waiting</Link>
        <Link className="sm-chip sm-chip-link" to="/admin/stock/seeds?new=1">+ New Seed Entry</Link>
      </div>
      <div className="sm-cards">
        {cards.map(([icon, label, value, tone, sub]) => (
          <div key={label} className={`sm-card ${tone}`}>
            <span className="sm-card-icon"><Icon name={icon} /></span>
            <div><small>{label}</small><strong>{value}</strong><em>{sub}</em></div>
          </div>
        ))}
      </div>
      <section className="sm-panel">
        <div className="sm-panel-head">
          <h2>Plant Stock Overview</h2>
          <div className="sm-panel-tools">
            <input className="form-control" placeholder="Search plant name..." value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search plants" />
            <select className="form-control" value={statusSel} onChange={(e) => setStatusSel(e.target.value)} aria-label="Status">
              <option value="all">All Status</option>
              <option value="in">In Stock</option>
              <option value="low">Low Stock</option>
              <option value="out">Out of Stock</option>
            </select>
          </div>
        </div>
        {!data && !error ? <Loading /> : data ? (
          rows.length === 0 ? <Empty>{filter === "all" && statusSel === "all" && !q ? "No plants found." : "No plants match these filters."}</Empty> : (
            <div className="admin-table-wrap sm-table-wrap">
              <table className="admin-table sm-table">
                <thead><tr><th>Plant</th><th className="num">Ready now</th><th className="num sm-col-alloc">Allocated</th><th className="num">Orders waiting</th><th className="num">Still to make</th><th>Status</th><th>Actions</th></tr></thead>
                <tbody>
                  {rows.map((r) => {
                    const a = advice(r);
                    const s = statusOf(r);
                    const p = info[r.plant_id];
                    return (
                      <tr key={`${r.plant_id}-${r.variant_id || 0}`} className={s === "out" ? "sm-row-out" : ""}>
                        <td>
                          <div className="sm-plant">
                            {p?.image_url ? <img src={p.image_url} alt="" loading="lazy" /> : <span className="sm-thumb-empty"><Icon name="ready" /></span>}
                            <div><strong>{r.name}</strong>{growing[r.plant_id] > 0 && <small>{num(growing[r.plant_id])} seeds growing</small>}{a.tone !== "green" && <span className={`sm-advice stock-advice-${a.tone}`}>{a.text}</span>}</div>
                          </div>
                        </td>
                        <td className="num"><strong>{num(r.available_stock)}</strong> <small>{r.unit}</small>{r.reserved_stock > 0 && <small className="sm-alloc-note">{num(r.reserved_stock)} allocated</small>}</td>
                        <td className="num sm-col-alloc">{num(r.reserved_stock)}</td>
                        <td className="num">{num(r.outstanding_demand)}</td>
                        <td className="num">{r.to_produce > 0 ? <span className="dl-pill dl-red"><span className="dl-label">{num(r.to_produce)}</span></span> : "-"}</td>
                        <td><span className={`sm-badge sm-badge-${s}`}>{STATUS_TEXT[s]}</span></td>
                                                <td>
                          <div className="sm-actions">
                            {p?.slug ? <Link className="btn btn-sm btn-outline dark" to={`/plants/${p.slug}`} target="_blank" rel="noreferrer">View</Link> : null}
                            <Menu>
                              {a.to && <Link to={a.to}>{a.action}</Link>}
                              {a.make && <Link to={a.make.to}>{a.make.action}</Link>}
                              <Link to={`/admin/stock/add?plant=${r.plant_id}&variant=${r.variant_id || ""}`}>Add plants</Link>
                              <button type="button" onClick={() => { setFix(r); setCount(String(r.available_stock)); setReason(""); setMsg(""); }}>Correct count</button>
                            </Menu>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )
        ) : null}
      </section>
      {fix && (
        <div className="admin-form-card" style={{ maxWidth: 560, marginTop: 20 }}>
          <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Correct count: {fix.name}</h2>
          <form onSubmit={saveCount}>
            <div className="form-group">
              <label htmlFor="fix-count">How many are ready now, after you counted? (the system says {num(fix.available_stock)})</label>
              <input id="fix-count" className="form-control" required inputMode="numeric" value={count} onChange={(e) => setCount(sanitizeQuantityText(e.target.value, 100000000))} autoFocus />
            </div>
            <div className="form-group">
              <label htmlFor="fix-reason">Why is it different? (required)</label>
              <input id="fix-reason" className="form-control" required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. 8 plants dried" />
            </div>
            <button className="btn btn-primary" disabled={busy || count === "" || reason.trim().length < 3}>{busy ? "Saving..." : "Save"}</button>{" "}
            <button type="button" className="btn btn-outline dark" onClick={() => setFix(null)}>Cancel</button>
          </form>
        </div>
      )}
    </div>
  );
}
