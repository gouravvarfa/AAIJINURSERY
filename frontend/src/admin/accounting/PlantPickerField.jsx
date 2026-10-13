import { useState } from "react";
import { api } from "../../api";
import SearchSelect from "./SearchSelect";

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
export default function PlantPickerField({ plants, categories, row, onSelectPlant, onSelectVariant, onPlantCreated, onCategoryCreated, plantPlaceholder }) {
  const [showModal, setShowModal] = useState(false);
  const [draft, setDraft] = useState({ name: "", category_id: "", price: "" });
  const [saving, setSaving] = useState(false);
  const [modalError, setModalError] = useState("");
  const [showCategoryModal, setShowCategoryModal] = useState(false);
  const [newCategoryName, setNewCategoryName] = useState("");
  const [categorySaving, setCategorySaving] = useState(false);
  const [categoryError, setCategoryError] = useState("");

  async function handleCreateCategory() {
    if (!newCategoryName.trim()) {
      setCategoryError("Name is required.");
      return;
    }
    setCategorySaving(true);
    setCategoryError("");
    try {
      const created = await api.post("/admin/categories", { name: newCategoryName.trim() });
      onCategoryCreated(created);
      setDraft((d) => ({ ...d, category_id: created.id }));
      setShowCategoryModal(false);
      setNewCategoryName("");
    } catch (err) {
      setCategoryError(err.message || "Could not create category.");
    } finally {
      setCategorySaving(false);
    }
  }

  const plant = plants.find((p) => p.id === Number(row.plant_id));
  const variants = plant?.variants || [];

  async function handleCreate() {
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
      <div className="plant-picker">
        <SearchSelect
          options={plants.map((p) => ({ value: p.id, label: p.name, hint: p.category?.name, search: p.sku }))}
          value={row.plant_id || ""}
          onChange={onSelectPlant}
          placeholder={plantPlaceholder || "No linked plant..."}
          clearLabel={plantPlaceholder || "No linked plant..."}
          searchPlaceholder="Search plant by name..."
          emptyText="No plant matches. Use + New Plant to add it."
        />
        <button
          type="button"
          className="btn btn-sm btn-outline dark"
          onClick={() => setShowModal(true)}
        >
          + New Plant
        </button>
      </div>

      {variants.length > 0 && (
        <label className="line-item-field plant-picker-tray">
          <span className="line-item-label">Tray size</span>
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
            <div>
              <div className="form-group">
                <label htmlFor="new_plant_name">Name</label>
                <input
                  id="new_plant_name"
                  className="form-control"
                  required
                  autoFocus
                  value={draft.name}
                  onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                  onKeyDown={(e) => e.key === "Enter" && handleCreate()}
                />
              </div>
              <div className="form-group">
                <label htmlFor="new_plant_category">Category</label>
                <div style={{ display: "flex", gap: 8 }}>
                  <select
                    id="new_plant_category"
                    className="form-control"
                    required
                    value={draft.category_id}
                    onChange={(e) => setDraft((d) => ({ ...d, category_id: e.target.value }))}
                    style={{ flex: 1 }}
                  >
                    <option value="">Select category...</option>
                    {categories.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn btn-sm btn-outline dark"
                    style={{ flexShrink: 0, whiteSpace: "nowrap" }}
                    onClick={() => setShowCategoryModal(true)}
                  >
                    + New Category
                  </button>
                </div>
              </div>

              {showCategoryModal && (
                <div className="modal-overlay" role="dialog" aria-modal="true" style={{ zIndex: 1 }}>
                  <div className="modal-card">
                    <h3>New Category</h3>
                    {categoryError && <div className="alert alert-error">{categoryError}</div>}
                    <div>
                      <div className="form-group">
                        <label htmlFor="new_category_name">Name</label>
                        <input
                          id="new_category_name"
                          className="form-control"
                          required
                          autoFocus
                          value={newCategoryName}
                          onChange={(e) => setNewCategoryName(e.target.value)}
                          onKeyDown={(e) => e.key === "Enter" && handleCreateCategory()}
                        />
                      </div>
                      <div style={{ display: "flex", gap: 8 }}>
                        <button type="button" className="btn btn-primary" disabled={categorySaving} onClick={handleCreateCategory}>
                          {categorySaving ? "Saving..." : "Create Category"}
                        </button>
                        <button
                          type="button"
                          className="btn btn-outline dark"
                          onClick={() => {
                            setShowCategoryModal(false);
                            setCategoryError("");
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}
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
                <button type="button" className="btn btn-primary" disabled={saving} onClick={handleCreate}>
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
            </div>
          </div>
        </div>
      )}
    </>
  );
}
