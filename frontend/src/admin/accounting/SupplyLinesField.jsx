import { useEffect, useState } from "react";
import { api } from "../../api";
import { PlantLink, qtyText, useSuggestions, useSupplyMeta } from "./supplyCommon";

const money = (n) => `₹${(Number(n) || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
export const blankLine = (kind = "seed_packet", unit = "packets") => ({ item_kind: kind, description: "", plant_id: "", company: "", lot_number: "", quantity: "", unit, unit_price: "", mfg_date: "", expiry_date: "", packet_size: "", packet_unit: "g", storage_location: "", line_notes: "" });

// One line of a Purchase Order: a seed packet, medicine, fertilizer or other supply, with its own lot number and expiry.
// (Plants are not bought here. Older orders that already had plant lines show them as read-only rows.)
export default function SupplyLinesField({ value, onChange }) {
  const rows = value || [];
  const { meta, kind, whole } = useSupplyMeta();
  const [plants, setPlants] = useState([]);
  const [more, setMore] = useState({});
  useEffect(() => { api.get("/admin/plants").then(setPlants).catch(() => {}); }, []);
  const set = (i, patch) => onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  return (
    <div className="sl-lines">
      {rows.map((row, i) => (
        <LineCard key={`line-${i}`} row={row} n={i + 1} meta={meta} kind={kind} whole={whole} plants={plants} showMore={Boolean(more[i])}
          toggleMore={() => setMore({ ...more, [i]: !more[i] })} onChange={(patch) => set(i, patch)} onRemove={() => onChange(rows.filter((_, idx) => idx !== i))}
          onPlantCreated={(pl) => setPlants((list) => [...list, pl].sort((a, b) => a.name.localeCompare(b.name)))} />
      ))}
      <button type="button" className="btn btn-sm btn-outline dark" onClick={() => onChange([...rows, blankLine()])}>+ Add Item</button>
      {rows.length > 0 && <p className="sl-total">Order total: <strong>{money(rows.reduce((n, r) => n + (Number(r.quantity) || 0) * (Number(r.unit_price) || 0), 0))}</strong></p>}
    </div>
  );
}

function LineCard({ row, n, meta, kind, whole, plants, showMore, toggleMore, onChange, onRemove, onPlantCreated }) {
  const sug = useSuggestions(row.item_kind === "plant" ? "" : row.item_kind);
  const k = kind(row.item_kind);
  const listId = `sl-names-${n}`;
  const total = (Number(row.quantity) || 0) * (Number(row.unit_price) || 0);
  if (row.item_kind === "plant") {
    return (
      <div className="sl-card sl-legacy">
        <div className="sl-head"><strong>Line {n}</strong><span className="badge badge-muted">Plant (older order)</span><button type="button" className="btn btn-sm btn-danger" onClick={onRemove}>Remove</button></div>
        <div className="sl-grid">
          <div className="sl-wide"><span className="sl-label">Plant</span><div>{row.description}</div></div>
          <label><span className="sl-label">Quantity</span><input className="form-control" inputMode="decimal" value={row.quantity} onChange={(e) => onChange({ quantity: qtyText(e.target.value) })} /></label>
          <label><span className="sl-label">Unit cost (₹)</span><input className="form-control" inputMode="decimal" value={row.unit_price} onChange={(e) => onChange({ unit_price: qtyText(e.target.value) })} /></label>
        </div>
      </div>
    );
  }
  return (
    <div className="sl-card">
      <div className="sl-head">
        <strong>Line {n}</strong>
        <select className="form-control sl-kind" aria-label={`Line ${n} item type`} value={row.item_kind} onChange={(e) => onChange({ item_kind: e.target.value, unit: kind(e.target.value).default_unit, plant_id: e.target.value === "seed_packet" ? row.plant_id : "" })}>
          {meta.kinds.map((x) => (<option key={x.key} value={x.key}>{x.label}</option>))}
        </select>
        <button type="button" className="btn btn-sm btn-danger" onClick={onRemove}>Remove</button>
      </div>
      <div className="sl-grid">
        <label className="sl-wide"><span className="sl-label">{row.item_kind === "seed_packet" ? "Seed name / variety" : "Item name"} *</span>
          <input className="form-control" list={listId} maxLength={200} value={row.description} onChange={(e) => onChange({ description: e.target.value })} placeholder={row.item_kind === "medicine" ? "e.g. Neem oil" : row.item_kind === "fertilizer" ? "e.g. Urea" : row.item_kind === "seed_packet" ? "e.g. Hybrid 1057" : "e.g. Seedling trays"} />
          <datalist id={listId}>{sug.names.map((x) => (<option key={x} value={x} />))}</datalist>
        </label>
        {row.item_kind === "seed_packet" && (
          <div className="sl-wide"><span className="sl-label">Plant (optional)</span><PlantLink id={`sl-plant-${n}`} plants={plants} value={row.plant_id} onChange={(v) => onChange({ plant_id: v })} onPlantCreated={onPlantCreated} /></div>
        )}
        <label><span className="sl-label">{row.item_kind === "seed_packet" ? "Company / brand *" : "Company / brand"}</span><input className="form-control" maxLength={150} list={`sl-co-${n}`} value={row.company} onChange={(e) => onChange({ company: e.target.value })} />
          <datalist id={`sl-co-${n}`}>{sug.companies.map((x) => (<option key={x} value={x} />))}</datalist></label>
        <label><span className="sl-label">Lot / batch number{k.lot_required ? " *" : ""}</span><input className="form-control" maxLength={80} value={row.lot_number} onChange={(e) => onChange({ lot_number: e.target.value })} /></label>
        <label><span className="sl-label">Quantity *</span><input className="form-control" inputMode="decimal" value={row.quantity} onChange={(e) => onChange({ quantity: qtyText(e.target.value) })} /></label>
        <label><span className="sl-label">Unit</span>
          <select className="form-control" value={row.unit || k.default_unit} onChange={(e) => onChange({ unit: e.target.value })}>{meta.units.map((u) => (<option key={u.key} value={u.key}>{u.key}</option>))}</select></label>
        <label><span className="sl-label">Unit cost (₹)</span><input className="form-control" inputMode="decimal" value={row.unit_price} onChange={(e) => onChange({ unit_price: qtyText(e.target.value) })} /></label>
        <label><span className="sl-label">Expiry date{k.expiry_required ? " *" : ""}</span><input className="form-control" type="date" value={row.expiry_date} onChange={(e) => onChange({ expiry_date: e.target.value })} /></label>
      </div>
      <div className="sl-foot">
        <button type="button" className="sl-more" onClick={toggleMore}>{showMore ? "Fewer details" : "More details (manufacturing date, packet size, storage, notes)"}</button>
        <span className="sl-linetotal">Line total <strong>{money(total)}</strong>{row.unit && !whole(row.unit) && Number(row.quantity) ? ` · ${row.quantity} ${row.unit}` : ""}</span>
      </div>
      {showMore && (
        <div className="sl-grid sl-extra">
          <label><span className="sl-label">Manufacturing date</span><input className="form-control" type="date" value={row.mfg_date} onChange={(e) => onChange({ mfg_date: e.target.value })} /></label>
          {row.item_kind === "seed_packet" && (
            <div className="sl-pair"><label><span className="sl-label">Packet size</span><input className="form-control" inputMode="decimal" value={row.packet_size} onChange={(e) => onChange({ packet_size: qtyText(e.target.value) })} /></label>
              <label><span className="sl-label">Size unit</span><select className="form-control" value={row.packet_unit || "g"} onChange={(e) => onChange({ packet_unit: e.target.value })}>{["g", "kg", "mg", "seeds", "pcs", "ml", "litre"].map((u) => (<option key={u}>{u}</option>))}</select></label></div>
          )}
          <label><span className="sl-label">Storage location</span><input className="form-control" maxLength={120} value={row.storage_location} onChange={(e) => onChange({ storage_location: e.target.value })} /></label>
          <label className="sl-wide"><span className="sl-label">Notes</span><input className="form-control" maxLength={1000} value={row.line_notes} onChange={(e) => onChange({ line_notes: e.target.value })} /></label>
        </div>
      )}
    </div>
  );
}
