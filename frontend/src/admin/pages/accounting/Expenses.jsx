import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import SearchBox from "../../accounting/SearchBox";
import ExportButton from "../../accounting/ExportButton";
import { expenseBadgeClass } from "../../accounting/accountingStatus";

function todayDateInput() {
  return new Date().toISOString().slice(0, 10);
}

const CATEGORIES = ["Rent", "Utilities", "Salaries", "Transport", "Marketing", "Supplies", "Maintenance", "Other"];

export default function Expenses() {
  const [items, setItems] = useState(null);
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("list");
  const [accounts, setAccounts] = useState([]);
  const [contacts, setContacts] = useState([]);
  const [form, setForm] = useState({
    category: "Other",
    account_id: "",
    contact_id: "",
    description: "",
    expense_date: todayDateInput(),
    amount: 0,
    tax_amount: 0,
    reference: "",
    notes: "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");

  function load() {
    setItems(null);
    setLoadError("");
    const query = q ? `?q=${encodeURIComponent(q)}` : "";
    api.get(`/admin/accounting/expenses${query}`).then(setItems).catch((err) => setLoadError(err.message || "Could not load expenses."));
  }

  useEffect(load, [q]);

  function startCreate() {
    setForm({
      category: "Other",
      account_id: "",
      contact_id: "",
      description: "",
      expense_date: todayDateInput(),
      amount: 0,
      tax_amount: 0,
      reference: "",
      notes: "",
    });
    setError("");
    api.get("/admin/accounting/accounts").then(setAccounts);
    api.get("/admin/accounting/contacts").then(setContacts);
    setMode("form");
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (form.amount <= 0) {
      setError("Amount must be greater than 0.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api.post("/admin/accounting/expenses", {
        category: form.category,
        account_id: form.account_id ? Number(form.account_id) : null,
        contact_id: form.contact_id ? Number(form.contact_id) : null,
        description: form.description,
        expense_date: form.expense_date,
        amount: form.amount,
        tax_amount: form.tax_amount,
        reference: form.reference,
        notes: form.notes,
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
          <h1>New Expense</h1>
          <button className="btn btn-sm btn-outline dark" onClick={() => setMode("list")}>
            Back to List
          </button>
        </div>
        <div className="admin-form-card">
          {error && <div className="alert alert-error">{error}</div>}
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label htmlFor="category">Category</label>
              <select
                id="category"
                className="form-control"
                value={form.category}
                onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="account_id">Chart of Accounts (optional)</label>
              <select
                id="account_id"
                className="form-control"
                value={form.account_id}
                onChange={(e) => setForm((f) => ({ ...f, account_id: e.target.value }))}
              >
                <option value="">No linked account</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.code} - {a.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="contact_id">Payee (optional)</label>
              <select
                id="contact_id"
                className="form-control"
                value={form.contact_id}
                onChange={(e) => setForm((f) => ({ ...f, contact_id: e.target.value }))}
              >
                <option value="">No linked contact</option>
                {contacts.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="description">Description</label>
              <input
                id="description"
                type="text"
                className="form-control"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              />
            </div>
            <div className="form-group">
              <label htmlFor="expense_date">Expense Date</label>
              <input
                id="expense_date"
                type="date"
                className="form-control"
                required
                value={form.expense_date}
                onChange={(e) => setForm((f) => ({ ...f, expense_date: e.target.value }))}
              />
            </div>
            <div className="form-group">
              <label htmlFor="amount">Amount (₹)</label>
              <input
                id="amount"
                type="number"
                step="any"
                className="form-control"
                required
                value={form.amount}
                onChange={(e) => setForm((f) => ({ ...f, amount: e.target.valueAsNumber || 0 }))}
              />
            </div>
            <div className="form-group">
              <label htmlFor="tax_amount">Tax Amount (optional)</label>
              <input
                id="tax_amount"
                type="number"
                step="any"
                className="form-control"
                value={form.tax_amount}
                onChange={(e) => setForm((f) => ({ ...f, tax_amount: e.target.valueAsNumber || 0 }))}
              />
            </div>
            <div className="form-group">
              <label htmlFor="reference">Reference (optional)</label>
              <input
                id="reference"
                type="text"
                className="form-control"
                value={form.reference}
                onChange={(e) => setForm((f) => ({ ...f, reference: e.target.value }))}
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
              {saving ? "Saving..." : "Save Expense"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="admin-page-head">
        <h1>Expenses</h1>
        <div className="admin-page-head-controls">
          <SearchBox value={q} onChange={setQ} placeholder="Search by category or description..." />
          <ExportButton baseUrl="/api/admin/accounting/export/expenses.xlsx" />
          <button className="btn btn-sm btn-primary" onClick={startCreate}>
            + New Expense
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
        <Empty>No expenses logged yet.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Description</th>
                <th>Date</th>
                <th>Amount</th>
                <th>Balance Due</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{item.category}</td>
                  <td>{item.description || "-"}</td>
                  <td>{new Date(item.expense_date).toLocaleDateString()}</td>
                  <td>₹{item.total_amount.toLocaleString()}</td>
                  <td>₹{item.balance_due.toLocaleString()}</td>
                  <td>
                    <span className={`badge ${expenseBadgeClass(item.status)}`}>{item.status}</span>
                  </td>
                  <td>
                    <Link className="btn btn-sm btn-outline dark" to={`/admin/accounting/expenses/${item.id}`}>
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
