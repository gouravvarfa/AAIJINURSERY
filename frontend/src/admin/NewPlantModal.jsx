import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api";

// A small "create plant" popup used inside Add Purchase. It reuses the normal plant API (POST /admin/plants).
// The plant is created INACTIVE (not shown on the website) with no stock; stock only arrives when the purchase is saved.
export default function NewPlantModal({ existingPlants, onCreated, onClose }) {
  const [categories, setCategories] = useState([]);
  const [form, setForm] = useState({ name: "", category_id: "", price: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [catOpen, setCatOpen] = useState(false);
  const [catName, setCatName] = useState("");
  const [catError, setCatError] = useState("");
  const [catBusy, setCatBusy] = useState(false);
  const submitting = useRef(false); // blocks a second click while the first one is still being sent

  useEffect(() => {
    api.get("/admin/categories").then(setCategories).catch(() => setError("Could not load the categories."));
  }, []);

  const name = form.name.trim();
  const same = existingPlants.find((p) => p.name.trim().toLowerCase() === name.toLowerCase());
  const price = Number(form.price);
  const ready = name && form.category_id && form.price !== "" && price > 0 && !same;

  async function addCategory() {
    const n = catName.trim();
    if (!n || catBusy) return;
    const dup = categories.find((c) => c.name.trim().toLowerCase() === n.toLowerCase());
    if (dup) {
      setForm((f) => ({ ...f, category_id: String(dup.id) }));
      setCatOpen(false);
      setCatName("");
      return;
    }
    setCatBusy(true);
    setCatError("");
    try {
      const created = await api.post("/admin/categories", { name: n });
      setCategories((list) => [...list, created]);
      setForm((f) => ({ ...f, category_id: String(created.id) }));
      setCatOpen(false);
      setCatName("");
    } catch (err) {
      setCatError(err.message || "Could not create the category.");
    } finally {
      setCatBusy(false);
    }
  }

  async function save(e) {
    e.preventDefault();
    e.stopPropagation(); // this popup sits inside the purchase form: its submit must never save the purchase
    if (submitting.current || !ready) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      const plant = await api.post("/admin/plants", { name, category_id: Number(form.category_id), price, stock_quantity: 0, is_active: false });
      onCreated(plant);
    } catch (err) {
      setError(err.message || "Could not create the plant.");
      submitting.current = false;
      setBusy(false);
    }
  }

  return createPortal(
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="Add new plant">
      <div className="modal-card">
        <button type="button" className="modal-close" aria-label="Close" onClick={onClose} disabled={busy}>&times;</button>
        <h3 style={{ marginTop: 0 }}>Add New Plant</h3>
        <p className="stock-hint" style={{ marginTop: 0 }}>
          The plant is saved as <strong>inactive</strong>: it will not show on the website until you add its photo and details on the Plants page and make it active. It gets no stock until this purchase is saved.
        </p>
        {error && <div className="alert alert-error">{error}</div>}
        {same && <div className="alert alert-warning">A plant called "{same.name}" already exists. Close this and choose it from the list instead of creating it again.</div>}
        <form onSubmit={save}>
          <div className="form-group">
            <label htmlFor="np_name">Plant name</label>
            <input id="np_name" className="form-control" required maxLength={150} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus />
          </div>
          <div className="form-group">
            <label htmlFor="np_cat">Category</label>
            <div style={{ display: "flex", gap: 8 }}>
              <select id="np_cat" className="form-control" style={{ flex: 1 }} required value={form.category_id} onChange={(e) => setForm({ ...form, category_id: e.target.value })}>
                <option value="">Select a category...</option>
                {categories.map((c) => (<option key={c.id} value={c.id}>{c.name}</option>))}
              </select>
              <button type="button" className="btn btn-sm btn-outline dark" onClick={() => setCatOpen((v) => !v)}>+ New category</button>
            </div>
            {catOpen && (
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <input className="form-control" style={{ flex: 1 }} placeholder="New category name" maxLength={120} value={catName} onChange={(e) => setCatName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCategory(); } }} aria-label="New category name" />
                <button type="button" className="btn btn-sm btn-primary" disabled={catBusy || !catName.trim()} onClick={addCategory}>{catBusy ? "Adding..." : "Add"}</button>
              </div>
            )}
            {catError && <small style={{ color: "#b3261e" }}>{catError}</small>}
          </div>
          <div className="form-group">
            <label htmlFor="np_price">Selling price (₹)</label>
            <input id="np_price" className="form-control" required inputMode="decimal" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value.replace(/[^0-9.]/g, "") })} />
          </div>
          <button className="btn btn-primary" disabled={busy || !ready}>{busy ? "Creating..." : "Create plant"}</button>{" "}
          <button type="button" className="btn btn-outline dark" onClick={onClose} disabled={busy}>Cancel</button>
        </form>
      </div>
    </div>,
    document.body
  );
}
