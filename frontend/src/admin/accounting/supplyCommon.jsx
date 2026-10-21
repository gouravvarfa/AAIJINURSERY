import { useEffect, useState } from "react";
import { api } from "../../api";
import NewPlantModal from "../NewPlantModal";
import SearchSelect from "./SearchSelect";

// The rules for seed packets / medicines / fertilizers / supplies come from the server, so the screens and the server always agree.
export function useSupplyMeta() {
  const [meta, setMeta] = useState({ kinds: [], units: [] });
  useEffect(() => {
    api.get("/admin/stock/seed-packets/meta").then(setMeta).catch(() => {});
  }, []);
  const kind = (key) => meta.kinds.find((k) => k.key === key) || { key, label: key, lot_required: false, expiry_required: false, default_unit: "packets" };
  const whole = (unit) => Boolean(meta.units.find((u) => u.key === unit)?.whole);
  return { meta, kind, whole };
}

// Names and companies typed before, offered again as suggestions (free text, no separate item master).
export function useSuggestions(kind) {
  const [s, setS] = useState({ names: [], companies: [] });
  useEffect(() => {
    api.get(`/admin/stock/seed-packets/suggestions?kind=${encodeURIComponent(kind || "")}`).then(setS).catch(() => {});
  }, [kind]);
  return s;
}

export const qtyText = (v) => String(v ?? "").replace(/[^0-9.]/g, "").replace(/^(\d*\.\d{0,3}).*$/, "$1").replace(/^(\d+)\.(?=.*\.)/, "$1");

// Plant link for a seed packet: searchable existing plant, "+ Create New Plant", or Unassigned / General stock.
export function PlantLink({ plants, value, onChange, onPlantCreated, id }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <SearchSelect
          id={id}
          options={plants.map((p) => ({ value: p.id, label: p.name + (p.is_active === false ? " (inactive)" : ""), hint: p.category?.name }))}
          value={value || ""}
          onChange={(v) => onChange(v ? Number(v) : "")}
          placeholder="Unassigned / General stock"
          clearLabel="Unassigned / General stock"
          searchPlaceholder="Search a plant by name"
          emptyText="No plant matches. Use + Create New Plant."
        />
      </div>
      <button type="button" className="btn btn-sm btn-outline dark" onClick={() => setOpen(true)}>+ Create New Plant</button>
      {open && (
        <NewPlantModal
          existingPlants={plants}
          note="The plant is saved as inactive: it will not show on the website until you add its photo and details on the Plants page and make it active. Seed packets are counted separately, so this adds no ready plant stock."
          onCreated={(pl) => { onPlantCreated?.(pl); onChange(pl.id); setOpen(false); }}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}

// A readable problem for one line, or "" when it is fine. The server checks again.
export function lineProblem(row, n, { kind, whole }) {
  const k = kind(row.item_kind);
  const label = `Line ${n}`;
  if (row.item_kind === "plant") return Number(row.quantity) > 0 ? "" : `${label}: write the quantity`;
  if (!row.description?.trim() && !(row.item_kind === "seed_packet" && row.plant_id)) return `${label}: write what the item is`;
  if (row.item_kind === "seed_packet" && !row.company?.trim()) return `${label}: write the seed company / brand`;
  if (k.lot_required && !row.lot_number?.trim()) return `${label}: the lot / batch number is required for ${k.label.toLowerCase()}s`;
  if (k.expiry_required && !row.expiry_date) return `${label}: the expiry date is required for ${k.label.toLowerCase()}s`;
  const q = Number(row.quantity);
  if (!(q > 0)) return `${label}: write the quantity`;
  if (whole(row.unit || k.default_unit) && Math.abs(q - Math.round(q)) > 1e-9) return `${label}: ${row.unit || k.default_unit} must be a whole number (use kg, g, litre or ml for fractions)`;
  if (row.expiry_date && row.mfg_date && row.mfg_date > row.expiry_date) return `${label}: manufacturing date is after the expiry date`;
  return "";
}
