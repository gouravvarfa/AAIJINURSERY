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
  const [showContactModal, setShowContactModal] = useState(false);
  const [newContact, setNewContact] = useState({ name: "", phone: "", email: "", address: "" });
  const [contactSaving, setContactSaving] = useState(false);
  const [contactError, setContactError] = useState("");

  async function handleCreateContact(e) {
    e.preventDefault();
    if (!newContact.name.trim()) {
      setContactError("Name is required.");
      return;
    }
    setContactSaving(true);
    setContactError("");
    try {
      const created = await api.post("/admin/accounting/contacts", {
        contact_type: "supplier",
        name: newContact.name.trim(),
        phone: newContact.phone.trim(),
        email: newContact.email.trim(),
        address: newContact.address.trim(),
      });
      setContacts((prev) => [...prev, created]);
      setForm((f) => ({ ...f, contact_id: created.id }));
      setShowContactModal(false);
      setNewContact({ name: "", phone: "", email: "", address: "" });
    } catch (err) {
      setContactError(err.message || "Could not create contact.");
    } finally {
      setContactSaving(false);
    }
  }

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
          variant_id: i.variant_id || null,
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
              <div style={{ display: "flex", gap: 8 }}>
                <select
                  id="contact_id"
                  className="form-control"
                  required
                  value={form.contact_id}
                  onChange={(e) => setForm((f) => ({ ...f, contact_id: e.target.value }))}
                  style={{ flex: 1 }}
                >
                  <option value="">Select a supplier...</option>
                  {contacts.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
                <button type="button" className="btn btn-sm btn-outline dark" onClick={() => setShowContactModal(true)}>
                  + New Contact
                </button>
              </div>
            </div>

            {showContactModal && (
              <div className="modal-overlay" role="dialog" aria-modal="true">
                <div className="modal-card">
                  <h3>New Supplier Contact</h3>
                  {contactError && <div className="alert alert-error">{contactError}</div>}
                  <form onSubmit={handleCreateContact}>
                    <div className="form-group">
                      <label htmlFor="new_contact_name">Name</label>
                      <input
                        id="new_contact_name"
                        className="form-control"
                        required
                        autoFocus
                        value={newContact.name}
                        onChange={(e) => setNewContact((c) => ({ ...c, name: e.target.value }))}
                      />
                    </div>
                    <div className="form-group">
                      <label htmlFor="new_contact_phone">Mobile</label>
                      <input
                        id="new_contact_phone"
                        className="form-control"
                        value={newContact.phone}
                        onChange={(e) => setNewContact((c) => ({ ...c, phone: e.target.value }))}
                      />
                    </div>
                    <div className="form-group">
                      <label htmlFor="new_contact_email">Email</label>
                      <input
                        id="new_contact_email"
                        type="email"
                        className="form-control"
                        value={newContact.email}
                        onChange={(e) => setNewContact((c) => ({ ...c, email: e.target.value }))}
                      />
                    </div>
                    <div className="form-group">
                      <label htmlFor="new_contact_address">Address</label>
                      <textarea
                        id="new_contact_address"
                        className="form-control"
                        value={newContact.address}
                        onChange={(e) => setNewContact((c) => ({ ...c, address: e.target.value }))}
                      />
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button className="btn btn-primary" disabled={contactSaving}>
                        {contactSaving ? "Saving..." : "Create Contact"}
                      </button>
                      <button
                        type="button"
                        className="btn btn-outline dark"
                        onClick={() => {
                          setShowContactModal(false);
                          setContactError("");
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            )}
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
