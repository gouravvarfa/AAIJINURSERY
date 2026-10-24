import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../../../api";
import SearchSelect from "../../accounting/SearchSelect";
import { Loading, Empty } from "../../../components/Loading";
import SupplyLinesField, { blankLine } from "../../accounting/SupplyLinesField";
import { lineProblem, useSupplyMeta } from "../../accounting/supplyCommon";
import SearchBox from "../../accounting/SearchBox";
import ExportButton from "../../accounting/ExportButton";
import { purchaseOrderBadgeClass } from "../../accounting/accountingStatus";

function todayDateInput() {
  return new Date().toISOString().slice(0, 10);
}

export default function PurchaseOrders() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const editId = searchParams.get("edit");
  const [editingOrder, setEditingOrder] = useState(null); // the saved order being edited, if any
  const [items, setItems] = useState(null);
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("list");
  const [contacts, setContacts] = useState([]);
  const supply = useSupplyMeta();
  const [form, setForm] = useState({ contact_id: "", order_date: todayDateInput(), notes: "", supplier_bill_number: "", items: [blankLine()] });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [showContactModal, setShowContactModal] = useState(false);
  const [newContact, setNewContact] = useState({ name: "", phone: "", email: "", address: "" });
  const [contactSaving, setContactSaving] = useState(false);
  const [contactError, setContactError] = useState("");

  async function handleCreateContact() {
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

  // "/admin/accounting/purchase-orders?edit=ID" (the Edit button on the detail
  // page) opens this same form, pre-filled, and saves with PUT.
  useEffect(() => {
    if (!editId) {
      setEditingOrder(null);
      return;
    }
    setError("");
    Promise.all([api.get("/admin/accounting/purchase-orders/" + editId), api.get("/admin/accounting/contacts")])
      .then(([order, contactList]) => {
        setContacts(contactList);
        setEditingOrder(order);
        setForm({
          contact_id: order.contact_id,
          order_date: String(order.order_date).slice(0, 10),
          notes: order.notes || "",
          supplier_bill_number: order.supplier_bill_number || "",
          items: order.items.map((i) => ({
            item_kind: i.item_kind || "plant",
            plant_id: i.plant_id || "",
            variant_id: i.variant_id || "",
            description: i.description,
            company: i.company || "",
            lot_number: i.lot_number || "",
            quantity: i.quantity,
            unit: i.unit || "",
            unit_price: i.unit_price,
            mfg_date: i.mfg_date || "",
            expiry_date: i.expiry_date || "",
            packet_size: i.packet_size || "",
            packet_unit: i.packet_unit || "g",
            storage_location: i.storage_location || "",
            line_notes: i.line_notes || "",
          })),
        });
        setMode("form");
      })
      .catch((err) => {
        setLoadError(err.message || "Could not open this order for editing.");
        setMode("list");
      });
  }, [editId]);

  function leaveForm() {
    if (editingOrder) navigate("/admin/accounting/purchase-orders/" + editingOrder.id);
    else setMode("list");
  }

  function startCreate() {
    setEditingOrder(null);
    setForm({ contact_id: "", order_date: todayDateInput(), notes: "", supplier_bill_number: "", items: [blankLine()] });
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
    if (!form.items.length) {
      setError("Add at least one item.");
      return;
    }
    for (let n = 0; n < form.items.length; n += 1) {
      const problem = lineProblem(form.items[n], n + 1, supply);
      if (problem) {
        setError(problem);
        return;
      }
    }
    setSaving(true);
    setError("");
    try {
      const body = {
        contact_id: Number(form.contact_id),
        order_date: form.order_date,
        notes: form.notes,
        supplier_bill_number: form.supplier_bill_number,
        items: form.items.map((i) => ({
          item_kind: i.item_kind,
          plant_id: i.plant_id ? Number(i.plant_id) : null,
          variant_id: i.variant_id || null,
          description: i.description,
          company: i.company,
          lot_number: i.lot_number,
          quantity: Number(i.quantity),
          unit: i.unit || supply.kind(i.item_kind).default_unit,
          unit_price: Number(i.unit_price) || 0,
          mfg_date: i.mfg_date || null,
          expiry_date: i.expiry_date || null,
          packet_size: i.packet_size ? Number(i.packet_size) : null,
          packet_unit: i.packet_unit || "",
          storage_location: i.storage_location,
          line_notes: i.line_notes,
        })),
      };
      if (editingOrder) {
        await api.put("/admin/accounting/purchase-orders/" + editingOrder.id, body);
        navigate("/admin/accounting/purchase-orders/" + editingOrder.id);
        return;
      }
      await api.post("/admin/accounting/purchase-orders", body);
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
          <h1>{editingOrder ? `Edit Purchase Order ${editingOrder.order_number}` : "New Purchase Order"}</h1>
          <button className="btn btn-sm btn-outline dark" onClick={leaveForm}>
            {editingOrder ? "Cancel" : "Back to List"}
          </button>
        </div>
        <div className="admin-form-card">
          {error && <div className="alert alert-error">{error}</div>}
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="contact_id">Supplier</label>
              <div style={{ display: "flex", gap: 8 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <SearchSelect
                    id="contact_id"
                    options={contacts.map((c) => ({
                      value: c.id,
                      label: c.name,
                      hint: [c.phone, c.source === "online" ? "website customer" : ""].filter(Boolean).join(" · "),
                      search: `${c.phone} ${c.email}`,
                    }))}
                    value={form.contact_id}
                    onChange={(v) => setForm((f) => ({ ...f, contact_id: v }))}
                    placeholder="Select a supplier..."
                    searchPlaceholder="Search supplier by name or mobile number"
                    emptyText="No contact matches. Use + New Contact to add one."
                  />
                </div>
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
                  <div>
                    <div className="form-group">
                      <label htmlFor="new_contact_name">Name</label>
                      <input
                        id="new_contact_name"
                        className="form-control"
                        required
                        autoFocus
                        value={newContact.name}
                        onChange={(e) => setNewContact((c) => ({ ...c, name: e.target.value }))}
                        onKeyDown={(e) => e.key === "Enter" && handleCreateContact()}
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
                      <button type="button" className="btn btn-primary" disabled={contactSaving} onClick={handleCreateContact}>
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
                  </div>
                </div>
              </div>
            )}
            <div className="form-group">
              <label htmlFor="supplier_bill_number">Supplier Bill Number (optional)</label>
              <input
                id="supplier_bill_number"
                className="form-control"
                maxLength={80}
                value={form.supplier_bill_number}
                onChange={(e) => setForm((f) => ({ ...f, supplier_bill_number: e.target.value }))}
                placeholder="The number printed on the supplier's bill"
              />
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
              <SupplyLinesField
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
              {saving ? "Saving..." : editingOrder ? "Save Changes" : "Save Purchase Order"}
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
                <th>Supplier Bill #</th>
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
                  <td>{item.supplier_bill_number || "-"}</td>
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
