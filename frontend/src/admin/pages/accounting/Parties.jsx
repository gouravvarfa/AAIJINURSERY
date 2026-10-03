import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../api";
import { useAuth } from "../../../context/AuthContext";
import { Loading, Empty } from "../../../components/Loading";
import SearchBox from "../../accounting/SearchBox";
import ExportButton from "../../accounting/ExportButton";
import { sourceBadgeClass } from "../../accounting/accountingStatus";

const CONTACT_TYPES = ["customer", "supplier", "both"];

function channelBadges(channels) {
  if (!channels || channels.length === 0) return <span className="badge badge-muted">No activity</span>;
  if (channels.length === 2) return <span className="badge badge-accent">Online + Offline</span>;
  return (
    <span className={`badge ${sourceBadgeClass(channels[0])}`}>
      {channels[0] === "online" ? "Online" : "Offline"}
    </span>
  );
}

function emptyForm() {
  return { contact_type: "customer", name: "", email: "", phone: "", address: "", gstin: "", is_active: true };
}

export default function Parties() {
  const { role, hasPermission } = useAuth();
  // Custom-role admins are authorized by the module/action matrix, so hide
  // actions they lack. Other roles are gated by the legacy accounting_role on
  // the backend, which the frontend can't see -- keep showing the buttons for
  // them and let the backend enforce. The backend is the real security boundary.
  const isCustom = role === "custom";
  const canCreate = !isCustom || hasPermission("accounting", "CREATE");
  const canEdit = !isCustom || hasPermission("accounting", "EDIT");
  const canDelete = !isCustom || hasPermission("accounting", "DELETE");

  const [items, setItems] = useState(null);
  const [contactType, setContactType] = useState("");
  const [channelFilter, setChannelFilter] = useState("");
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("list"); // list | form
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(emptyForm());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [duplicates, setDuplicates] = useState(null);
  const [checkingDuplicates, setCheckingDuplicates] = useState(false);
  const [forceCreate, setForceCreate] = useState(false);

  function load() {
    setItems(null);
    const params = new URLSearchParams();
    if (contactType) params.set("contact_type", contactType);
    if (q) params.set("q", q);
    const query = params.toString() ? `?${params.toString()}` : "";
    api.get(`/admin/accounting/contacts${query}`).then(setItems);
  }

  useEffect(load, [contactType, q]);

  const filteredItems = items
    ? items.filter((item) => {
        if (!channelFilter) return true;
        if (channelFilter === "both") return item.channels?.length === 2;
        return item.channels?.length === 1 && item.channels[0] === channelFilter;
      })
    : items;

  function startCreate() {
    setForm(emptyForm());
    setEditingId(null);
    setError("");
    setDuplicates(null);
    setForceCreate(false);
    setMode("form");
  }

  function startEdit(item) {
    setForm({
      contact_type: item.contact_type, name: item.name, email: item.email,
      phone: item.phone, address: item.address, gstin: item.gstin, is_active: item.is_active,
    });
    setEditingId(item.id);
    setError("");
    setDuplicates(null);
    setForceCreate(true); // editing never needs a duplicate check
    setMode("form");
  }

  async function checkForDuplicates() {
    if (!form.phone && !form.email && !form.gstin) return;
    setCheckingDuplicates(true);
    try {
      const params = new URLSearchParams();
      if (form.phone) params.set("phone", form.phone);
      if (form.email) params.set("email", form.email);
      if (form.gstin) params.set("gstin", form.gstin);
      const result = await api.get(`/admin/accounting/parties/check-duplicate?${params.toString()}`);
      setDuplicates(result.matches);
    } finally {
      setCheckingDuplicates(false);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();

    if (!editingId && !forceCreate && duplicates === null) {
      await checkForDuplicates();
      return; // let the user review matches (if any) before submitting again
    }

    setSaving(true);
    setError("");
    try {
      if (editingId) {
        await api.put(`/admin/accounting/contacts/${editingId}`, form);
      } else {
        await api.post("/admin/accounting/contacts", form);
      }
      setMode("list");
      load();
    } catch (err) {
      setError(err.message || "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(item) {
    if (!confirm(`Delete party "${item.name}"? This cannot be undone.`)) return;
    try {
      await api.del(`/admin/accounting/contacts/${item.id}`);
      load();
    } catch (err) {
      alert(err.message || "Could not delete this party.");
    }
  }

  if (mode === "form") {
    return (
      <div>
        <div className="admin-page-head">
          <h1>{editingId ? "Edit Party" : "New Party"}</h1>
          <button className="btn btn-sm btn-outline dark" onClick={() => setMode("list")}>
            Back to List
          </button>
        </div>
        <div className="admin-form-card">
          {error && <div className="alert alert-error">{error}</div>}

          {duplicates && duplicates.length > 0 && (
            <div className="alert alert-error" style={{ marginBottom: 16 }}>
              <strong>Possible existing party found</strong> -- matching phone, email, or GSTIN.
              {duplicates.map((d) => (
                <div key={d.id} style={{ marginTop: 8, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span>
                    {d.name} &middot; {d.phone || d.email} &middot;{" "}
                    <span className={`badge ${sourceBadgeClass(d.source)}`}>{d.source}</span> &middot; matched on {d.matched_on}
                  </span>
                  <Link className="btn btn-sm btn-outline dark" to={`/admin/accounting/parties/${d.id}`}>
                    View This Party
                  </Link>
                </div>
              ))}
              <button
                type="button"
                className="btn btn-sm btn-primary"
                style={{ marginTop: 10 }}
                onClick={() => setForceCreate(true)}
              >
                This is a different party -- create new anyway
              </button>
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="contact_type">Type</label>
              <select
                id="contact_type"
                className="form-control"
                required
                value={form.contact_type}
                onChange={(e) => setForm((f) => ({ ...f, contact_type: e.target.value }))}
              >
                <option value="customer">Customer</option>
                <option value="supplier">Supplier</option>
                <option value="both">Both</option>
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="name">Name</label>
              <input
                id="name"
                type="text"
                className="form-control"
                required
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div className="form-group">
              <label htmlFor="phone">Phone</label>
              <input
                id="phone"
                type="text"
                className="form-control"
                value={form.phone}
                onChange={(e) => {
                  setForm((f) => ({ ...f, phone: e.target.value }));
                  setDuplicates(null);
                  setForceCreate(false);
                }}
              />
            </div>
            <div className="form-group">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="text"
                className="form-control"
                value={form.email}
                onChange={(e) => {
                  setForm((f) => ({ ...f, email: e.target.value }));
                  setDuplicates(null);
                  setForceCreate(false);
                }}
              />
            </div>
            <div className="form-group">
              <label htmlFor="address">Address</label>
              <textarea
                id="address"
                className="form-control"
                value={form.address}
                onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))}
              />
            </div>
            <div className="form-group">
              <label htmlFor="gstin">GSTIN</label>
              <input
                id="gstin"
                type="text"
                className="form-control"
                value={form.gstin}
                onChange={(e) => {
                  setForm((f) => ({ ...f, gstin: e.target.value }));
                  setDuplicates(null);
                  setForceCreate(false);
                }}
              />
            </div>
            <div className="checkbox-row" style={{ marginBottom: 16 }}>
              <input
                id="is_active"
                type="checkbox"
                checked={form.is_active}
                onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
              />
              <label htmlFor="is_active">Active</label>
            </div>
            <button className="btn btn-primary" disabled={saving || checkingDuplicates}>
              {checkingDuplicates
                ? "Checking for duplicates..."
                : saving
                ? "Saving..."
                : !editingId && !forceCreate
                ? "Check & Save"
                : "Save Party"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="admin-page-head">
        <h1>Parties</h1>
        <div className="admin-page-head-controls">
          <select className="form-control admin-control-sm" style={{ maxWidth: 180 }} value={contactType} onChange={(e) => setContactType(e.target.value)}>
            <option value="">All Types</option>
            <option value="customer">Customer</option>
            <option value="supplier">Supplier</option>
            <option value="both">Both</option>
          </select>
          <select className="form-control admin-control-sm" style={{ maxWidth: 180 }} value={channelFilter} onChange={(e) => setChannelFilter(e.target.value)}>
            <option value="">All Channels</option>
            <option value="online">Online Only</option>
            <option value="offline">Offline Only</option>
            <option value="both">Online + Offline</option>
          </select>
          <SearchBox value={q} onChange={setQ} placeholder="Search by name, email, or phone..." />
          <ExportButton baseUrl="/api/admin/accounting/export/contacts.xlsx" />
          {canCreate && (
            <button className="btn btn-sm btn-primary" onClick={startCreate}>
              + New Party
            </button>
          )}
        </div>
      </div>

      {!filteredItems ? (
        <Loading />
      ) : filteredItems.length === 0 ? (
        <Empty>No parties found.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Party Name</th>
                <th>Type</th>
                <th>Channel</th>
                <th>Phone</th>
                <th>Email</th>
                <th>Total Sales</th>
                <th>Total Purchases</th>
                <th>Outstanding</th>
                <th>Payable</th>
                <th>Last Transaction</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredItems.map((item) => (
                <tr key={item.id}>
                  <td>
                    <Link to={`/admin/accounting/parties/${item.id}`}>{item.name}</Link>
                  </td>
                  <td style={{ textTransform: "capitalize" }}>{item.contact_type}</td>
                  <td>{channelBadges(item.channels)}</td>
                  <td>{item.phone || "-"}</td>
                  <td>{item.email || "-"}</td>
                  <td>₹{item.total_sales.toLocaleString()}</td>
                  <td>₹{item.total_purchases.toLocaleString()}</td>
                  <td>₹{item.outstanding.toLocaleString()}</td>
                  <td>₹{item.payable.toLocaleString()}</td>
                  <td>{item.last_transaction_date ? new Date(item.last_transaction_date).toLocaleDateString() : "-"}</td>
                  <td>
                    <span className={`badge ${item.is_active ? "badge-accent" : "badge-muted"}`}>
                      {item.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td>
                    <div className="row-actions">
                      <Link className="btn btn-sm btn-outline dark" to={`/admin/accounting/parties/${item.id}`}>
                        View
                      </Link>
                      {item.source !== "online" && (
                        <>
                          {canEdit && (
                            <button className="btn btn-sm btn-outline dark" onClick={() => startEdit(item)}>
                              Edit
                            </button>
                          )}
                          {canDelete && (
                            <button className="btn btn-sm btn-danger" onClick={() => handleDelete(item)}>
                              Delete
                            </button>
                          )}
                        </>
                      )}
                    </div>
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