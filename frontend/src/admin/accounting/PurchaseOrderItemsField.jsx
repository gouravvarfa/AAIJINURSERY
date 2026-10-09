import { useEffect, useState } from "react";
import { api } from "../../api";
import PlantPickerField from "./PlantPickerField";

// Repeatable {plant, description, quantity, unit_price} rows for a Purchase
// Order -- modeled on SalesOrderItemsField.jsx, but plant_id is required
// (not optional) since converting to a Bill increments that plant's real
// stock, mirroring the existing PurchaseItemsField.jsx business rule.
//
// When a tray-size variant is picked, quantity means "number of trays
// received" and unit_price stays the admin's own entered per-tray cost
// (purchase cost is never derived from the sale price, unlike Sales Order).
export default function PurchaseOrderItemsField({ value, onChange }) {
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
              variant_id: "", // a newly picked plant starts per-unit; pick a tray size explicitly
              description: plant ? plant.name : row.description,
            }
          : row
      )
    );
  }

  function selectVariant(index, variantId) {
    onChange(rows.map((row, i) => (i === index ? { ...row, variant_id: variantId ? Number(variantId) : "" } : row)));
  }

  return (
    <div className="variants-field">
      {rows.map((row, i) => (
        <div className="variant-row" key={`row-${i}`}>
          <div className="variant-row-inputs">
            <label>
              Plant
              <PlantPickerField
                plants={plants}
                categories={categories}
                row={row}
                onSelectPlant={(plantId) => selectPlant(i, plantId)}
                onSelectVariant={(variantId) => selectVariant(i, variantId)}
                onPlantCreated={(p) => setPlants((prev) => [...prev, p])}
              />
            </label>
            <label>
              {row.variant_id ? "Number of trays received" : "Quantity"}
              <input
                type="number"
                className="form-control"
                value={row.quantity}
                onChange={(e) => updateRow(i, "quantity", e.target.valueAsNumber || 0)}
              />
            </label>
            <label>
              {row.variant_id ? "Cost per tray (₹)" : "Unit Cost (₹)"}
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
      ))}
      <button type="button" className="btn btn-sm btn-outline dark" onClick={addRow}>
        + Add Line Item
      </button>
    </div>
  );
}
