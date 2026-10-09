import { useEffect, useState } from "react";
import { api } from "../../api";
import PlantPickerField from "./PlantPickerField";

// Repeatable {plant, description, quantity, unit_price} rows for a manually
// entered (offline) Sales Order -- modeled on PurchaseItemsField.jsx's
// add/remove/update-row pattern. plant_id is optional: a line can just be a
// free-text description (e.g. a service charge) with no linked product.
//
// When a tray-size variant is picked, quantity means "number of trays" and
// unit_price the per-tray price -- the same convention the website's own
// tray orders already use (OrderItem.variant_id/tray_size).
export default function SalesOrderItemsField({ value, onChange }) {
  const rows = value || [];
  const [plants, setPlants] = useState([]);
  const [categories, setCategories] = useState([]);

  useEffect(() => {
    api.get("/admin/plants").then(setPlants);
    api.get("/admin/categories").then(setCategories);
  }, []);

  function updateRow(index, key, val) {
    onChange(rows.map((row, i) => (i === index ? { ...row, [key]: val } : row)));
  }

  function removeRow(index) {
    onChange(rows.filter((_, i) => i !== index));
  }

  function addRow() {
    onChange([...rows, { plant_id: "", variant_id: "", description: "", quantity: 1, unit_price: 0 }]);
  }

  function selectPlant(index, plantId) {
    const plant = plants.find((p) => p.id === Number(plantId));
    onChange(
      rows.map((row, i) =>
        i === index
          ? {
              ...row,
              plant_id: plantId ? Number(plantId) : "",
              variant_id: "", // a new plant starts per-unit; pick a tray size explicitly
              description: plant ? plant.name : row.description,
              unit_price: plant ? plant.discount_price || plant.price : row.unit_price,
            }
          : row
      )
    );
  }

  function selectVariant(index, variantId, plant) {
    const variant = plant?.variants.find((v) => v.id === Number(variantId));
    onChange(
      rows.map((row, i) =>
        i === index
          ? {
              ...row,
              variant_id: variantId ? Number(variantId) : "",
              // Per-tray price when a tray is picked; back to the plain
              // per-unit price when cleared.
              unit_price: variant ? variant.price : plant ? plant.discount_price || plant.price : row.unit_price,
            }
          : row
      )
    );
  }

  return (
    <div className="variants-field">
      {rows.map((row, i) => {
        const plant = plants.find((p) => p.id === Number(row.plant_id));
        return (
          <div className="variant-row" key={`row-${i}`}>
            <div className="variant-row-inputs">
              <label style={{ flex: "2 1 260px", minWidth: 240 }}>
                Plant (optional)
                <PlantPickerField
                  plants={plants}
                  categories={categories}
                  row={row}
                  onSelectPlant={(plantId) => selectPlant(i, plantId)}
                  onSelectVariant={(variantId) => selectVariant(i, variantId, plant)}
                  onPlantCreated={(p) => setPlants((prev) => [...prev, p])}
                />
              </label>
              <label>
                Description
                <input
                  type="text"
                  className="form-control"
                  value={row.description}
                  onChange={(e) => updateRow(i, "description", e.target.value)}
                />
              </label>
              <label>
                {row.variant_id ? "Number of trays" : "Quantity"}
                <input
                  type="number"
                  className="form-control"
                  value={row.quantity}
                  onChange={(e) => updateRow(i, "quantity", e.target.valueAsNumber || 0)}
                />
              </label>
              <label>
                {row.variant_id ? "Price per tray (₹)" : "Unit Price (₹)"}
                <input
                  type="number"
                  step="any"
                  className="form-control"
                  value={row.unit_price}
                  onChange={(e) => updateRow(i, "unit_price", e.target.valueAsNumber || 0)}
                />
              </label>
            </div>
            {row.quantity > 0 && row.unit_price > 0 && (
              <small style={{ color: "var(--color-text-muted)" }}>
                Line total: ₹{(row.quantity * row.unit_price).toLocaleString()}
                {row.variant_id ? ` (${row.quantity} trays)` : ""}
              </small>
            )}
            <button type="button" className="btn btn-sm btn-danger" onClick={() => removeRow(i)}>
              Remove
            </button>
          </div>
        );
      })}
      <button type="button" className="btn btn-sm btn-outline dark" onClick={addRow}>
        + Add Line Item
      </button>
    </div>
  );
}
