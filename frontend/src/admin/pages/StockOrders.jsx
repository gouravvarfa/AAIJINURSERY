import { useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../context/AuthContext";
import { Loading, Empty } from "../../components/Loading";

const n = (v) => Number(v || 0).toLocaleString("en-IN");
const fmtDate = (d) => (d ? new Date(d).toLocaleDateString() : "-");

// Stock team's list of customer orders: who ordered what, how much is already
// in stock, how many to grow (with a buffer for plants lost while growing) and
// how many came out good. No prices or payments are shown here.
export default function StockOrders() {
  const { hasPermission } = useAuth();
  const canEdit = hasPermission("inventory", "EDIT");
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [onlyPending, setOnlyPending] = useState(true);
  const [error, setError] = useState("");
  const [drafts, setDrafts] = useState({}); // line_id -> typed prepare quantity
  const [busy, setBusy] = useState(null);
  const [ready, setReady] = useState(null); // line being marked ready
  const [readyForm, setReadyForm] = useState({ good: "", to_customer: "" });
  const [readyError, setReadyError] = useState("");

  function load() {
    setError("");
    const params = new URLSearchParams();
    if (q.trim()) params.set("q", q.trim());
    if (onlyPending) params.set("only_pending", "true");
    const query = params.toString() ? `?${params.toString()}` : "";
    api.get(`/admin/stock-orders${query}`).then(setData).catch((err) => setError(err.message || "Could not load orders."));
  }
  useEffect(load, [q, onlyPending]);

  async function savePrepare(row) {
    const raw = drafts[row.line_id];
    const value = raw === "" || raw == null ? 0 : Number(raw);
    if (!Number.isInteger(value) || value < 0) {
      setError("Enter a whole number (0 or more).");
      return;
    }
    setBusy(row.line_id);
    setError("");
    try {
      await api.put(`/admin/stock-orders/lines/${row.line_id}/prepare`, { prepare_quantity: value });
      setDrafts((d) => {
        const next = { ...d };
        delete next[row.line_id];
        return next;
      });
      load();
    } catch (err) {
      setError(err.message || "Could not save.");
    } finally {
      setBusy(null);
    }
  }

  function openReady(row) {
    const target = row.prepare_quantity ? Math.max(row.prepare_quantity - row.prepared_quantity, 1) : row.pending;
    setReady(row);
    setReadyError("");
    setReadyForm({ good: String(target), to_customer: String(Math.min(target, row.pending)) });
  }

  async function submitReady() {
    const good = Number(readyForm.good);
    const toCustomer = Number(readyForm.to_customer);
    if (!Number.isInteger(good) || good < 1) {
      setReadyError("Enter how many came out good.");
      return;
    }
    if (!Number.isInteger(toCustomer) || toCustomer < 0) {
      setReadyError("Customer's share must be 0 or more.");
      return;
    }
    if (toCustomer > good) {
      setReadyError("Customer's share can't be more than the good plants.");
      return;
    }
    if (toCustomer > ready.pending) {
      setReadyError(`This order only needs ${ready.pending} more.`);
      return;
    }
    setBusy(ready.line_id);
    setReadyError("");
    try {
      await api.post(`/admin/stock-orders/lines/${ready.line_id}/ready`, { good, to_customer: toCustomer });
      setReady(null);
      load();
    } catch (err) {
      setReadyError(err.message || "Could not save.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <div className="admin-page-head">
        <h1>Stock Orders</h1>
        <div className="admin-page-head-controls">
          <input
            className="form-control"
            style={{ minWidth: 220 }}
            placeholder="Search customer, order # or plant..."
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={onlyPending} onChange={(e) => setOnlyPending(e.target.checked)} />
            Only lines still needing plants
          </label>
          <button type="button" className="btn btn-outline dark" onClick={load}>Refresh</button>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}

      {!data && !error ? (
        <Loading />
      ) : data ? (
        <>
          <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 28 }}>
              <div><div className="dl-none">Order lines</div><div style={{ fontSize: "1.5rem", fontWeight: 700 }}>{n(data.totals.lines)}</div></div>
              <div><div className="dl-none">Still needed</div><div style={{ fontSize: "1.5rem", fontWeight: 700 }}>{n(data.totals.pending)}</div></div>
              <div><div className="dl-none">Short of stock</div><div style={{ fontSize: "1.5rem", fontWeight: 700, color: data.totals.shortage ? "#b3261e" : undefined }}>{n(data.totals.shortage)}</div></div>
            </div>
            <p style={{ margin: "12px 0 0", color: "var(--color-text-muted)", fontSize: "0.82rem" }}>
              "Needed" = what the customer ordered minus what is already given from stock. "To grow" is your own target and can be
              higher than "Needed" to cover plants that get damaged. It never changes the customer's order or bill.
            </p>
          </div>

          {data.items.length === 0 ? (
            <Empty>{onlyPending ? "No order is waiting for plants right now." : "No open orders."}</Empty>
          ) : (
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Customer</th>
                    <th>Order #</th>
                    <th>Plant</th>
                    <th>Ordered</th>
                    <th>Given from stock</th>
                    <th>Needed</th>
                    <th>In stock now</th>
                    <th>To grow</th>
                    <th>Ready so far</th>
                    <th>Delivery</th>
                    {canEdit && <th>Actions</th>}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((r) => {
                    const typed = drafts[r.line_id];
                    const value = typed !== undefined ? typed : r.prepare_quantity ?? "";
                    const extra = r.prepare_quantity ? r.prepare_quantity - r.pending : 0;
                    return (
                      <tr key={r.line_id}>
                        <td>
                          {r.customer_name}
                          {r.order_notes && <div style={{ color: "var(--color-text-muted)", fontSize: "0.78rem" }}>{r.order_notes}</div>}
                        </td>
                        <td>{r.order_number}</td>
                        <td>{r.product}</td>
                        <td>{n(r.quantity)} {r.unit}</td>
                        <td>{n(r.allocated)}</td>
                        <td>{n(r.pending)}</td>
                        <td>
                          {n(r.available_stock)}
                          {r.shortage > 0 && <span className="dl-pill dl-red" style={{ marginLeft: 6 }}><span className="dl-label">short {n(r.shortage)}</span></span>}
                        </td>
                        <td>
                          {canEdit && r.pending > 0 ? (
                            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                              <input
                                type="number"
                                min={0}
                                className="form-control"
                                style={{ width: 84 }}
                                value={value}
                                placeholder={String(r.pending)}
                                onChange={(e) => setDrafts((d) => ({ ...d, [r.line_id]: e.target.value }))}
                                aria-label={`Quantity to grow for ${r.customer_name}`}
                              />
                              {typed !== undefined && (
                                <button type="button" className="btn btn-sm btn-primary" disabled={busy === r.line_id} onClick={() => savePrepare(r)}>
                                  Save
                                </button>
                              )}
                            </div>
                          ) : (
                            r.prepare_quantity ?? "-"
                          )}
                          {typed === undefined && extra > 0 && (
                            <div style={{ color: "var(--color-text-muted)", fontSize: "0.78rem" }}>+{n(extra)} extra</div>
                          )}
                        </td>
                        <td>{r.prepared_quantity ? n(r.prepared_quantity) : "-"}</td>
                        <td>{fmtDate(r.delivery_date)}</td>
                        {canEdit && (
                          <td>
                            {r.pending > 0 ? (
                              <button type="button" className="btn btn-sm btn-outline dark" onClick={() => openReady(r)}>
                                Mark ready
                              </button>
                            ) : (
                              "Done"
                            )}
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          <AlertNumbers canEdit={canEdit} />
        </>
      ) : null}

      {ready && (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal-card">
            <h3>Mark ready - {ready.product}</h3>
            <p style={{ margin: "0 0 12px", color: "var(--color-text-muted)" }}>
              {ready.customer_name} ({ready.order_number}) still needs {n(ready.pending)} {ready.unit}.
            </p>
            {readyError && <div className="alert alert-error">{readyError}</div>}
            <div className="form-group">
              <label htmlFor="ready_good">How many came out good</label>
              <input
                id="ready_good"
                type="number"
                min={1}
                className="form-control"
                autoFocus
                value={readyForm.good}
                onChange={(e) => setReadyForm((f) => ({ ...f, good: e.target.value }))}
              />
            </div>
            <div className="form-group">
              <label htmlFor="ready_customer">Of these, give to this customer</label>
              <input
                id="ready_customer"
                type="number"
                min={0}
                max={ready.pending}
                className="form-control"
                value={readyForm.to_customer}
                onChange={(e) => setReadyForm((f) => ({ ...f, to_customer: e.target.value }))}
              />
            </div>
            <p style={{ margin: "0 0 12px" }}>
              Goes to general stock: <strong>{n(Math.max(0, Number(readyForm.good || 0) - Number(readyForm.to_customer || 0)))}</strong>
            </p>
            <div style={{ display: "flex", gap: 8 }}>
              <button type="button" className="btn btn-primary" disabled={busy === ready.line_id} onClick={submitReady}>
                {busy === ready.line_id ? "Saving..." : "Save"}
              </button>
              <button type="button" className="btn btn-outline dark" onClick={() => setReady(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// WhatsApp numbers that get a message whenever a new Sales Order is saved.
function AlertNumbers({ canEdit }) {
  const [list, setList] = useState(null);
  const [form, setForm] = useState({ name: "", mobile: "" });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  function load() {
    api.get("/admin/stock-orders/alert-recipients").then(setList).catch(() => setList([]));
  }
  useEffect(load, []);

  async function add(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.post("/admin/stock-orders/alert-recipients", form);
      setForm({ name: "", mobile: "" });
      load();
    } catch (err) {
      setError(err.message || "Could not add number.");
    } finally {
      setSaving(false);
    }
  }

  async function remove(id) {
    if (!confirm("Stop sending new-order WhatsApp alerts to this number?")) return;
    try {
      await api.del(`/admin/stock-orders/alert-recipients/${id}`);
      load();
    } catch (err) {
      setError(err.message || "Could not remove number.");
    }
  }

  return (
    <div className="admin-form-card" style={{ maxWidth: "none", marginTop: 24 }}>
      <h3 style={{ marginTop: 0 }}>New-order WhatsApp alerts</h3>
      <p style={{ color: "var(--color-text-muted)", fontSize: "0.85rem" }}>
        These numbers get a WhatsApp message with the customer's name whenever a new Sales Order is saved.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      {list === null ? (
        <Loading />
      ) : list.length === 0 ? (
        <p>No number added yet.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: "0 0 12px" }}>
          {list.map((r) => (
            <li key={r.id} style={{ display: "flex", gap: 12, alignItems: "center", padding: "4px 0" }}>
              <span>{r.name || "Stock team"} - {r.mobile}</span>
              {canEdit && (
                <button type="button" className="btn btn-sm btn-danger" onClick={() => remove(r.id)}>Remove</button>
              )}
            </li>
          ))}
        </ul>
      )}
      {canEdit && (
        <form onSubmit={add} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            className="form-control"
            style={{ maxWidth: 200 }}
            placeholder="Name"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          />
          <input
            className="form-control"
            style={{ maxWidth: 200 }}
            placeholder="Mobile (10 digits)"
            required
            value={form.mobile}
            onChange={(e) => setForm((f) => ({ ...f, mobile: e.target.value }))}
          />
          <button className="btn btn-primary" disabled={saving}>{saving ? "Adding..." : "Add number"}</button>
        </form>
      )}
    </div>
  );
}
