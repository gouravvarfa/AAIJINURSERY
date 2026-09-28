import { useEffect, useState } from "react";
import { api } from "../api";
import { Loading, Empty } from "../components/Loading";
import VariantsField from "./VariantsField";
import PurchaseItemsField from "./PurchaseItemsField";
import SalesOrderItemsField from "./accounting/SalesOrderItemsField";
import SearchBox from "./accounting/SearchBox";
import ExportButton from "./accounting/ExportButton";

const emptyValue = (field) => {
  if (field.type === "checkbox") return field.default ?? false;
  if (field.type === "number") return field.default ?? 0;
  return field.default ?? "";
};

function blankForm(fields) {
  const obj = {};
  fields.forEach((f) => {
    obj[f.name] = emptyValue(f);
  });
  return obj;
}

export default function CrudPage({
  title,
  resource,
  fields,
  columns,
  idKey = "id",
  allowEdit = true,
  allowDelete = true,
  deleteConfirmMessage,
  exportUrl,
  searchable = false,
  searchPlaceholder = "Search...",
}) {
  const [items, setItems] = useState(null);
  const [mode, setMode] = useState("list"); // list | form
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(() => blankForm(fields));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");

  function load() {
    setItems(null);
    const query = searchable && q ? `?q=${encodeURIComponent(q)}` : "";
    api.get(`${resource}${query}`).then(setItems);
  }

  useEffect(load, [resource, q]);

  function startCreate() {
    setForm(blankForm(fields));
    setEditingId(null);
    setError("");
    setMode("form");
  }

  function startEdit(item) {
    const obj = {};
    fields.forEach((f) => {
      obj[f.name] = item[f.sourceKey || f.name] ?? emptyValue(f);
    });
    setForm(obj);
    setEditingId(item[idKey]);
    setError("");
    setMode("form");
  }

  async function handleDelete(item) {
    const message = deleteConfirmMessage
      ? deleteConfirmMessage(item)
      : `Delete "${item[columns[0].key]}"? This cannot be undone.`;
    if (!confirm(message)) return;
    await api.del(`${resource}/${item[idKey]}`);
    load();
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    // An empty optional date input submits "" -- send null instead so
    // Optional[datetime] fields on the backend don't reject it as invalid.
    const payload = { ...form };
    fields.forEach((f) => {
      if (f.type === "date" && payload[f.name] === "") {
        payload[f.name] = null;
      }
    });
    try {
      if (editingId) {
        await api.put(`${resource}/${editingId}`, payload);
      } else {
        await api.post(resource, payload);
      }
      setMode("list");
      load();
    } catch (err) {
      setError(err.message || "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  function updateField(name, value) {
    setForm((f) => ({ ...f, [name]: value }));
  }

  if (mode === "form") {
    return (
      <div>
        <div className="admin-page-head">
          <h1>{editingId ? `Edit ${title}` : `Add ${title}`}</h1>
          <button className="btn btn-sm btn-outline dark" onClick={() => setMode("list")}>
            Back to List
          </button>
        </div>
        <div className="admin-form-card">
          {error && <div className="alert alert-error">{error}</div>}
          <form onSubmit={handleSubmit}>
            {fields.map((field) => (
              <div className="form-group" key={field.name}>
                <label htmlFor={field.name}>{field.label}</label>
                {field.type === "textarea" ? (
                  <textarea
                    id={field.name}
                    className="form-control"
                    required={field.required}
                    value={form[field.name]}
                    onChange={(e) => updateField(field.name, e.target.value)}
                  />
                ) : field.type === "checkbox" ? (
                  <div className="checkbox-row">
                    <input
                      id={field.name}
                      type="checkbox"
                      checked={!!form[field.name]}
                      onChange={(e) => updateField(field.name, e.target.checked)}
                    />
                    <span>{field.checkboxLabel || "Yes"}</span>
                  </div>
                ) : field.type === "variants" ? (
                  <VariantsField
                    value={form[field.name]}
                    onChange={(next) => updateField(field.name, next)}
                    pricePerUnit={form.price}
                  />
                ) : field.type === "purchase_items" ? (
                  <PurchaseItemsField
                    value={form[field.name]}
                    onChange={(next) => updateField(field.name, next)}
                  />
                ) : field.type === "sales_order_items" ? (
                  <SalesOrderItemsField
                    value={form[field.name]}
                    onChange={(next) => updateField(field.name, next)}
                  />
                ) : field.type === "date" ? (
                  <input
                    id={field.name}
                    type="date"
                    className="form-control"
                    required={field.required}
                    value={form[field.name] ? String(form[field.name]).slice(0, 10) : ""}
                    onChange={(e) => updateField(field.name, e.target.value)}
                  />
                ) : field.type === "select" ? (
                  <select
                    id={field.name}
                    className="form-control"
                    required={field.required}
                    value={form[field.name]}
                    onChange={(e) => updateField(field.name, Number(e.target.value) || e.target.value)}
                  >
                    <option value="">Select...</option>
                    {field.options.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    id={field.name}
                    type={field.type === "number" ? "number" : "text"}
                    step={field.type === "number" ? "any" : undefined}
                    className="form-control"
                    required={field.required}
                    placeholder={field.placeholder}
                    value={form[field.name]}
                    onChange={(e) =>
                      updateField(
                        field.name,
                        field.type === "number" ? e.target.valueAsNumber || 0 : e.target.value
                      )
                    }
                  />
                )}
                {field.help && (
                  <small style={{ color: "var(--color-text-muted)" }}>{field.help}</small>
                )}
              </div>
            ))}
            <button className="btn btn-primary" disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="admin-page-head">
        <h1>{title}</h1>
        <div style={{ display: "flex", gap: 8 }}>
          {exportUrl && <ExportButton baseUrl={exportUrl} />}
          <button className="btn btn-sm btn-primary" onClick={startCreate}>
            + Add {title}
          </button>
        </div>
      </div>

      {searchable && (
        <div style={{ marginBottom: 16 }}>
          <SearchBox value={q} onChange={setQ} placeholder={searchPlaceholder} />
        </div>
      )}

      {!items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>No {title.toLowerCase()} yet. Add your first one.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                {columns.map((col) => (
                  <th key={col.key}>{col.label}</th>
                ))}
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item[idKey]}>
                  {columns.map((col) => (
                    <td key={col.key}>{col.render ? col.render(item) : String(item[col.key] ?? "")}</td>
                  ))}
                  <td>
                    <div className="row-actions">
                      {(typeof allowEdit === "function" ? allowEdit(item) : allowEdit) && (
                        <button className="btn btn-sm btn-outline dark" onClick={() => startEdit(item)}>
                          Edit
                        </button>
                      )}
                      {(typeof allowDelete === "function" ? allowDelete(item) : allowDelete) && (
                        <button className="btn btn-sm btn-danger" onClick={() => handleDelete(item)}>
                          Delete
                        </button>
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
