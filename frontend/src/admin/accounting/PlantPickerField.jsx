import { useState } from "react";
import { api } from "../../api";

// One row's plant + tray-size picker, shared by Sales Order and Purchase
// Order line-item fields. Keeps "+ New Plant" and the tray-size dropdown in
// one place so both forms behave identically without duplicating this logic.
//
// Props:
//   plants: full plant list (with .variants), owned by the parent
//   categories: category list for the "new plant" modal
//   row: { plant_id, variant_id, ... } -- only these two fields are read
//   onSelectPlant(plantId): plant changed (or cleared)
//   onSelectVariant(variantId | ""): tray-size option changed (or cleared -> per-unit)
//   onPlantCreated(plant): a new plant was saved -- parent adds it to its list
export default function PlantPickerField({ plants, categories, row, onSelectPlant, onSelectVariant, onPlantCreated }) {
  const [showModal, setShowModal] = useState(false);
  const [draft, setDraft] = useState({ name: "", category_id: "", price: "" });
  const [saving, setSaving] = useState(false);
  const [modalError, setModalError] = useState("");

  const plant = plants.find((p) => p.id === Number(row.plant_id));
  const variants = plant?.variants || [];

  async function handleCreate(e) {
    e.preventDefault();
    if (!draft.name.trim() || !draft.category_id) {
      setModalError("Name and category are required.");
      return;
    }
    setSaving(true);
    setModalError("");
    try {
      const created = await api.post("/admin/plants", {
        name: draft.name.trim(),
        category_id: Number(draft.category_id),
        price: Number(draft.price) || 0,
      });
      onPlantCreated(created);
      onSelectPlant(created.id);
      setShowModal(false);
      setDraft({ name: "", category_id: "", price: "" });
    } catch (err) {
      setModalError(err.message || "Could not create plant.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <select
          className="form-control"
          value={row.plant_id || ""}
          onChange={(e) => onSelectPlant(e.target.value)}
          style={{ flex: "1 1 180px", minWidth: 160 }}
        >
          <option value="">No linked plant...</option>
          {plants.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn btn-sm btn-outline dark"
          style={{ flexShrink: 0, whiteSpace: "nowrap" }}
          onClick={() => setShowModal(true)}
        >
          + New Plant
        </button>
      </div>

      {variants.length > 0 && (
        <label>
          Tray size
          <select
            className="form-control"
            value={row.variant_id || ""}
            onChange={(e) => onSelectVariant(e.target.value)}
          >
            <option value="">Per unit (no tray)</option>
            {variants.map((v) => (
              <option key={v.id} value={v.id}>
                Tray of {v.tray_size} -- ₹{v.price.toLocaleString()}/tray
              </option>
            ))}
          </select>
        </label>
      )}

      {showModal && (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal-card">
            <h3>New Plant</h3>
            {modalError && <div className="alert alert-error">{modalError}</div>}
            <form onSubmit={handleCreate}>
              <div className="form-group">
                <label htmlFor="new_plant_name">Name</label>
                <input
                  id="new_plant_name"
                  className="form-control"
                  required
                  autoFocus
                  value={draft.name}
                  onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                />
              </div>
              <div className="form-group">
                <label htmlFor="new_plant_category">Category</label>
                <select
                  id="new_plant_category"
                  className="form-control"
                  required
                  value={draft.category_id}
                  onChange={(e) => setDraft((d) => ({ ...d, category_id: e.target.value }))}
                >
                  <option value="">Select category...</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label htmlFor="new_plant_price">Price (₹)</label>
                <input
                  id="new_plant_price"
                  type="number"
                  step="any"
                  className="form-control"
                  value={draft.price}
                  onChange={(e) => setDraft((d) => ({ ...d, price: e.target.value }))}
                />
              </div>
              <p style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
                Tray-size options, images and other details can be added later from the Plants page.
              </p>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn btn-primary" disabled={saving}>
                  {saving ? "Saving..." : "Create Plant"}
                </button>
                <button
                  type="button"
                  className="btn btn-outline dark"
                  onClick={() => {
                    setShowModal(false);
                    setModalError("");
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
