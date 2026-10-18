import { useEffect, useState } from "react";
import { api } from "../api";

// Supplier on Add Purchase: pick a real supplier (the purchase then goes into that supplier's account) or just type a name as before.
export default function SupplierField({ form, updateField }) {
  const [suppliers, setSuppliers] = useState([]);

  useEffect(() => {
    Promise.all([api.get("/admin/accounting/contacts?contact_type=supplier"), api.get("/admin/accounting/contacts?contact_type=both")])
      .then(([a, b]) => setSuppliers([...a, ...b].sort((x, y) => x.name.localeCompare(y.name))))
      .catch(() => {});
  }, []);

  const chosen = form.supplier_contact_id ? suppliers.find((s) => s.id === Number(form.supplier_contact_id)) : null;
  return (
    <div>
      <select
        id="supplier_contact_id"
        className="form-control"
        value={form.supplier_contact_id || ""}
        onChange={(e) => {
          const id = e.target.value ? Number(e.target.value) : "";
          updateField("supplier_contact_id", id);
          if (id) updateField("supplier", "");
        }}
      >
        <option value="">No supplier account (optional)</option>
        {suppliers.map((s) => (<option key={s.id} value={s.id}>{s.name}{s.phone ? ` (${s.phone})` : ""}</option>))}
      </select>
      {chosen ? (
        <small style={{ color: "var(--color-text-muted)" }}>
          This purchase goes into {chosen.name}'s account as <strong>Unpaid</strong> (they are owed the total). Record the payment later in Accounting, Payments Out.
          {chosen.payable > 0 ? ` Already owed to them: ₹${chosen.payable.toLocaleString("en-IN")}.` : ""}
        </small>
      ) : (
        <input
          id="supplier"
          className="form-control"
          style={{ marginTop: 8 }}
          placeholder="Or type a supplier name (not linked to any account)"
          value={form.supplier || ""}
          onChange={(e) => updateField("supplier", e.target.value)}
        />
      )}
    </div>
  );
}
