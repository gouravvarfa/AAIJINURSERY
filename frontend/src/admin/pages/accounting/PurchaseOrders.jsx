import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import PurchaseOrderItemsField from "../../accounting/PurchaseOrderItemsField";
import SearchBox from "../../accounting/SearchBox";
import ExportButton from "../../accounting/ExportButton";
import { purchaseOrderBadgeClass } from "../../accounting/accountingStatus";

function todayDateInput() {
  return new Date().toISOString().slice(0, 10);
}

export default function PurchaseOrders() {
  const [items, setItems] = useState(null);
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("list");
  const [contacts, setContacts] = useState([]);
  const [form, setForm] = useState({ contact_id: "", order_date: todayDateInput(), notes: "", items: [] });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");

  function load() {
    setItems(null);
    setLoadError("");
    const query = q ? `?q=${encodeURIComponent(q)}` : "";
    api.get(`/admin/accounting/purchase-orders${query}`).then(setItems).catch((err) => setLoadError(err.message || "Could not load purchase orders."));
  }

  useEffect(load, [q]);

  function startCreate() {
    setForm({ contact_id: "", order_date: todayDateInput(), notes: "", items: [] });
    setError("");
    api.get("/admin/accounting/contacts").then(setContacts);
    setMode("form");
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!form.contact_id) {
      setError("Please select a supplier contact.");
      return;
    }
    if (!form.items.length || form.items.some((i) => !i.plant_id)) {
      setError("Add at least one line item, and select a plant for every line.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api.post("/admin/accounting/purchase-orders", {
        contact_id: Number(form.contact_id),
        order_date: form.order_date,
        notes: form.notes,
        items: form.items.map((i) => ({
          plant_id: Number(i.plant_id),
          description: i.description,
          quantity: i.quantity,
          unit_price: i.unit_price,
        })),
      });
      setMode("list");
      load();
    } catch (err) {
      setError(err.message || "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  if (mode === "form") {
    return (
      <div>
        <div className="admin-page-head">
          <h1>New Purchase Order</h1>
          <button className="btn btn-sm btn-outline dark" onClick={() => setMode("list")}>
            Back to List
          </button>
        </div>
        <div className="admin-form-card">
          {error && <div className="alert alert-error">{error}</div>}
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="contact_id">Supplier</label>
              <select
                id="contact_id"
                className="form-control"
                required
                value={form.contact_id}
                onChange={(e) => setForm((f) => ({ ...f, contact_id: e.target.value }))}
              >
                <option value="">Select a supplier...</option>
                {contacts.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="order_date">Order Date</label>
              <input
                id="order_date"
                type="date"
                className="form-control"
                required
                value={form.order_date}
                onChange={(e) => setForm((f) => ({ ...f, order_date: e.target.value }))}
              />
            </div>
            <div className="form-group">
              <label>Line Items</label>
              <PurchaseOrderItemsField
                value={form.items}
                onChange={(next) => setForm((f) => ({ ...f, items: next }))}
              />
            </div>
            <div className="form-group">
              <label htmlFor="notes">Notes</label>
              <textarea
                id="notes"
                className="form-control"
                value={form.notes}
                onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              />
            </div>
            <button className="btn btn-primary" disabled={saving}>
              {saving ? "Saving..." : "Save Purchase Order"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="admin-page-head">
        <h1>Purchase Orders</h1>
        <div className="admin-page-head-controls">
          <SearchBox value={q} onChange={setQ} placeholder="Search by order # or supplier name..." />
          <ExportButton baseUrl="/api/admin/accounting/export/purchase-orders.xlsx" />
          <button className="btn btn-sm btn-primary" onClick={startCreate}>
            + New Purchase Order
          </button>
        </div>
      </div>

      {loadError ? (
        <div className="alert alert-error">
          {loadError} <button type="button" className="btn btn-outline dark" onClick={load}>Retry</button>
        </div>
      ) : !items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>No purchase orders yet. Create your first one.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Order #</th>
                <th>Supplier</th>
                <th>Date</th>
                <th>Total</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{item.order_number}</td>
                  <td>{item.contact?.name || "-"}</td>
                  <td>{new Date(item.order_date).toLocaleDateString()}</td>
                  <td>₹{item.total_amount.toLocaleString()}</td>
                  <td>
                    <span className={`badge ${purchaseOrderBadgeClass(item.status)}`}>{item.status}</span>
                  </td>
                  <td>
                    <Link className="btn btn-sm btn-outline dark" to={`/admin/accounting/purchase-orders/${item.id}`}>
                      View
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
