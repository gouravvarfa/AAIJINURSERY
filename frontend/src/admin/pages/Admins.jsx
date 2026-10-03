import { Fragment, useEffect, useState } from "react";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";
import { useAuth } from "../../context/AuthContext";

const blankForm = { username: "", password: "", role: "admin", custom_role_id: "" };

const ROLE_LABELS = {
  admin: "Admin",
  developer: "Developer",
  super_access: "Super Access",
  custom: "Custom",
};

const ROLE_BADGE_CLASS = {
  developer: "badge-accent",
  super_access: "badge-gold",
};

function OverridesPanel({ item, onClose }) {
  const [overrides, setOverrides] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [form, setForm] = useState({ module: "", action: "VIEW", effect: "DENY", reason: "" });
  const [error, setError] = useState("");

  function load() {
    api.get(`/admin/rbac/users/${item.id}/overrides`).then(setOverrides);
  }

  useEffect(() => {
    load();
    api.get("/admin/rbac/catalog").then((c) => {
      setCatalog(c);
      setForm((f) => ({ ...f, module: c.modules[0] }));
    });
  }, [item.id]);

  async function handleAdd(e) {
    e.preventDefault();
    setError("");
    try {
      await api.post(`/admin/rbac/users/${item.id}/overrides`, form);
      load();
    } catch (err) {
      setError(err.message || "Could not add override.");
    }
  }

  async function handleRemove(overrideId) {
    await api.del(`/admin/rbac/users/${item.id}/overrides/${overrideId}`);
    load();
  }

  return (
    <div className="admin-form-card" style={{ marginTop: 8, marginBottom: 8 }}>
      <div className="admin-page-head">
        <h3 style={{ margin: 0 }}>Permission Overrides for {item.username}</h3>
        <button className="btn btn-sm btn-outline dark" onClick={onClose}>
          Close
        </button>
      </div>

      {!overrides || !catalog ? (
        <Loading />
      ) : (
        <>
          {overrides.length === 0 ? (
            <Empty>No overrides for this user.</Empty>
          ) : (
            <table className="admin-table" style={{ marginBottom: 14 }}>
              <thead>
                <tr>
                  <th>Module</th>
                  <th>Action</th>
                  <th>Effect</th>
                  <th>Reason</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {overrides.map((o) => (
                  <tr key={o.id}>
                    <td>{o.module}</td>
                    <td>{o.action}</td>
                    <td>
                      <span className={o.effect === "ALLOW" ? "badge badge-accent" : "badge badge-danger"}>
                        {o.effect}
                      </span>
                    </td>
                    <td>{o.reason || "—"}</td>
                    <td>
                      <button className="btn btn-sm btn-outline dark" onClick={() => handleRemove(o.id)}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {error && <div className="alert alert-error">{error}</div>}
          <form onSubmit={handleAdd} style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label>Module</label>
              <select
                className="form-control"
                value={form.module}
                onChange={(e) => setForm((f) => ({ ...f, module: e.target.value }))}
              >
                {catalog.modules.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label>Action</label>
              <select
                className="form-control"
                value={form.action}
                onChange={(e) => setForm((f) => ({ ...f, action: e.target.value }))}
              >
                {catalog.actions.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label>Effect</label>
              <select
                className="form-control"
                value={form.effect}
                onChange={(e) => setForm((f) => ({ ...f, effect: e.target.value }))}
              >
                <option value="DENY">DENY (take away)</option>
                <option value="ALLOW">ALLOW (grant extra)</option>
              </select>
            </div>
            <div className="form-group" style={{ marginBottom: 0, flex: 1, minWidth: 160 }}>
              <label>Reason (optional)</label>
              <input
                className="form-control"
                value={form.reason}
                onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
              />
            </div>
            <button className="btn btn-primary">Add Override</button>
          </form>
        </>
      )}
    </div>
  );
}

export default function Admins() {
  const [items, setItems] = useState(null);
  const [customRoles, setCustomRoles] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(blankForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [overridesFor, setOverridesFor] = useState(null);
  const { username, role } = useAuth();
  const isDeveloper = role === "developer";

  function load() {
    setItems(null);
    api.get("/admin/admins").then(setItems);
    api.get("/admin/rbac/roles").then((roles) => setCustomRoles(roles.filter((r) => !r.is_system)));
  }

  useEffect(load, []);

  async function handleCreate(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const payload = { ...form, custom_role_id: form.role === "custom" ? Number(form.custom_role_id) : null };
      await api.post("/admin/admins", payload);
      setForm(blankForm);
      setShowForm(false);
      load();
    } catch (err) {
      setError(err.message || "Could not create admin.");
    } finally {
      setSaving(false);
    }
  }

  async function handleResetPassword(item) {
    const password = prompt(`New password for "${item.username}":`);
    if (!password) return;
    try {
      await api.put(`/admin/admins/${item.id}/password`, { password });
      alert(`Password updated for "${item.username}". Their existing sessions have been signed out.`);
      load();
    } catch (err) {
      alert(err.message || "Could not reset password.");
    }
  }

  async function handleRoleChange(item, newRole, customRoleId) {
    if (newRole === item.role && (newRole !== "custom" || customRoleId === item.custom_role_id)) return;
    const roleLabel = newRole === "custom" ? customRoles.find((r) => r.id === customRoleId)?.name || "Custom" : ROLE_LABELS[newRole];
    const warning =
      newRole === "super_access"
        ? `Grant SUPER ACCESS to "${item.username}"? This gives complete access to every business module.`
        : item.role === "super_access"
        ? `Revoke Super Access from "${item.username}" and set their role to ${roleLabel}?`
        : `Change "${item.username}"'s role to ${roleLabel}?`;
    if (!confirm(warning)) return;
    try {
      await api.put(`/admin/admins/${item.id}/role`, {
        role: newRole,
        custom_role_id: newRole === "custom" ? customRoleId : null,
      });
      load();
    } catch (err) {
      alert(err.message || "Could not change role.");
    }
  }

  async function handleToggleActive(item) {
    const activating = !item.is_active;
    if (!confirm(`${activating ? "Enable" : "Disable"} account "${item.username}"?`)) return;
    try {
      await api.put(`/admin/rbac/admins/${item.id}/status?is_active=${activating}`, {});
      load();
    } catch (err) {
      alert(err.message || "Could not update account status.");
    }
  }

  async function handleToggleAskAaiji(item) {
    const enabling = !item.ask_aaiji_enabled;
    try {
      await api.put(`/admin/rbac/users/${item.id}/ask-aaiji?enabled=${enabling}`, {});
      load();
    } catch (err) {
      alert(err.message || "Could not update Ask AAIJI access.");
    }
  }

  async function handleRevokeSessions(item) {
    if (!confirm(`Sign "${item.username}" out of every device?`)) return;
    try {
      const result = await api.post(`/admin/rbac/users/${item.id}/revoke-all-sessions`);
      alert(`Signed out ${result.revoked_count} session(s) for "${item.username}".`);
    } catch (err) {
      alert(err.message || "Could not revoke sessions.");
    }
  }

  async function handleDelete(item) {
    if (!confirm(`Delete admin "${item.username}"? This cannot be undone.`)) return;
    try {
      await api.del(`/admin/admins/${item.id}`);
      load();
    } catch (err) {
      alert(err.message || "Could not delete admin.");
    }
  }

  return (
    <div>
      <div className="admin-page-head">
        <h1>Admins</h1>
        {isDeveloper && (
          <button className="btn btn-sm btn-primary" onClick={() => setShowForm((s) => !s)}>
            {showForm ? "Cancel" : "+ Add Admin"}
          </button>
        )}
      </div>

      {isDeveloper && showForm && (
        <div className="admin-form-card">
          {error && <div className="alert alert-error">{error}</div>}
          <form onSubmit={handleCreate}>
            <div className="form-group">
              <label htmlFor="new-username">Username</label>
              <input
                id="new-username"
                className="form-control"
                required
                value={form.username}
                onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
              />
            </div>
            <div className="form-group">
              <label htmlFor="new-password">Password</label>
              <input
                id="new-password"
                type="text"
                className="form-control"
                required
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
              />
            </div>
            <div className="form-group">
              <label htmlFor="new-role">Role</label>
              <select
                id="new-role"
                className="form-control"
                value={form.role}
                onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
              >
                <option value="admin">Admin</option>
                <option value="super_access">Super Access</option>
                <option value="custom">Custom Role</option>
                <option value="developer">Developer</option>
              </select>
            </div>
            {form.role === "custom" && (
              <div className="form-group">
                <label htmlFor="new-custom-role">Custom Role</label>
                <select
                  id="new-custom-role"
                  className="form-control"
                  required
                  value={form.custom_role_id}
                  onChange={(e) => setForm((f) => ({ ...f, custom_role_id: e.target.value }))}
                >
                  <option value="">Select a role...</option>
                  {customRoles.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
                {customRoles.length === 0 && (
                  <p style={{ fontSize: "0.82rem", color: "var(--color-text-muted)" }}>
                    No custom roles yet -- create one under Developer &rarr; Roles &amp; Permissions first.
                  </p>
                )}
              </div>
            )}
            <button className="btn btn-primary" disabled={saving}>
              {saving ? "Saving..." : "Create Admin"}
            </button>
          </form>
        </div>
      )}

      {!items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>No admins found.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Username</th>
                <th>Role</th>
                <th>Status</th>
                <th>Ask AAIJI</th>
                {isDeveloper && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <Fragment key={item.id}>
                  <tr>
                    <td>{item.id}</td>
                    <td>
                      {item.username}
                      {item.username === username && (
                        <span className="badge badge-accent" style={{ marginLeft: 8 }}>
                          You
                        </span>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${ROLE_BADGE_CLASS[item.role] || "badge-muted"}`}>
                        {item.role === "custom"
                          ? customRoles.find((r) => r.id === item.custom_role_id)?.name || "Custom"
                          : ROLE_LABELS[item.role] || item.role}
                      </span>
                    </td>
                    <td>
                      <span className={item.is_active ? "badge badge-accent" : "badge badge-danger"}>
                        {item.is_active ? "Active" : "Disabled"}
                      </span>
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        checked={item.ask_aaiji_enabled}
                        disabled={!isDeveloper || item.role === "developer"}
                        onChange={() => handleToggleAskAaiji(item)}
                        title={
                          item.role === "developer"
                            ? "Developer always has access"
                            : item.ask_aaiji_enabled
                            ? "Ask AAIJI is visible to this admin"
                            : "Ask AAIJI is hidden from this admin"
                        }
                      />
                    </td>
                    {isDeveloper && (
                      <td>
                        <div className="row-actions">
                          <select
                            className="form-control"
                            style={{ width: "auto", minWidth: 150, display: "inline-block" }}
                            value={item.role === "custom" ? `custom:${item.custom_role_id}` : item.role}
                            onChange={(e) => {
                              const val = e.target.value;
                              if (val.startsWith("custom:")) {
                                handleRoleChange(item, "custom", Number(val.slice(7)));
                              } else {
                                handleRoleChange(item, val);
                              }
                            }}
                          >
                            <option value="admin">Admin</option>
                            <option value="super_access">Super Access</option>
                            <option value="developer">Developer</option>
                            {customRoles.map((r) => (
                              <option key={r.id} value={`custom:${r.id}`}>
                                {r.name}
                              </option>
                            ))}
                            {customRoles.length === 0 && <option value="custom" disabled>No custom roles yet</option>}
                          </select>
                          <button className="btn btn-sm btn-outline dark" onClick={() => handleResetPassword(item)}>
                            Reset Password
                          </button>
                          <button className="btn btn-sm btn-outline dark" onClick={() => handleToggleActive(item)}>
                            {item.is_active ? "Disable" : "Enable"}
                          </button>
                          <button className="btn btn-sm btn-outline dark" onClick={() => handleRevokeSessions(item)}>
                            Revoke Sessions
                          </button>
                          <button
                            className="btn btn-sm btn-outline dark"
                            onClick={() => setOverridesFor(overridesFor === item.id ? null : item.id)}
                          >
                            Overrides
                          </button>
                          <button
                            className="btn btn-sm btn-danger"
                            disabled={item.username === username}
                            onClick={() => handleDelete(item)}
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                  {overridesFor === item.id && (
                    <tr>
                      <td colSpan={isDeveloper ? 6 : 5}>
                        <OverridesPanel item={item} onClose={() => setOverridesFor(null)} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
