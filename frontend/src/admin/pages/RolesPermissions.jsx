import { useEffect, useState } from "react";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";

const ACTION_LABELS = {
  VIEW: "View",
  CREATE: "Create",
  EDIT: "Edit",
  DELETE: "Delete",
  EXPORT: "Export",
  PRINT: "Print",
  APPROVE: "Approve",
  CANCEL: "Cancel",
};

const MODULE_LABELS = {
  website: "Website",
  products: "Products / Plants",
  orders: "Orders",
  customers: "Customers",
  analytics: "Analytics",
  accounting: "Accounting",
  delivery: "Delivery",
  labour: "Employees & Labour",
  communications: "Communications (WhatsApp)",
  inventory: "Inventory",
  reports: "Reports",
  ai_assistant: "Ask AAIJI (Chatbot)",
  users_roles: "Users & Roles (Developer only)",
  system_health: "System Health (Developer only)",
};

function blankMatrix(modules) {
  const matrix = {};
  for (const m of modules) {
    matrix[m] = { can_view: false, can_create: false, can_edit: false, can_delete: false, can_export: false, can_print: false, can_approve: false, can_cancel: false };
  }
  return matrix;
}

export default function RolesPermissions() {
  const [catalog, setCatalog] = useState(null);
  const [roles, setRoles] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [matrix, setMatrix] = useState({});
  const [newRoleName, setNewRoleName] = useState("");
  const [newRoleDesc, setNewRoleDesc] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function load() {
    api.get("/admin/rbac/catalog").then(setCatalog);
    api.get("/admin/rbac/roles").then((data) => {
      setRoles(data);
      if (!selectedId && data.length) setSelectedId(data[0].id);
    });
  }

  useEffect(load, []);

  const selectedRole = roles?.find((r) => r.id === selectedId) || null;

  useEffect(() => {
    if (!selectedRole || !catalog) return;
    const m = blankMatrix(catalog.modules);
    for (const p of selectedRole.permissions) {
      m[p.module] = {
        can_view: p.can_view, can_create: p.can_create, can_edit: p.can_edit, can_delete: p.can_delete,
        can_export: p.can_export, can_print: p.can_print, can_approve: p.can_approve, can_cancel: p.can_cancel,
      };
    }
    setMatrix(m);
  }, [selectedId, roles, catalog]);

  function toggle(module, field) {
    setMatrix((m) => ({ ...m, [module]: { ...m[module], [field]: !m[module][field] } }));
  }

  async function handleCreateRole(e) {
    e.preventDefault();
    setError("");
    try {
      const role = await api.post("/admin/rbac/roles", { name: newRoleName, description: newRoleDesc });
      setNewRoleName("");
      setNewRoleDesc("");
      setShowCreate(false);
      const updated = await api.get("/admin/rbac/roles");
      setRoles(updated);
      setSelectedId(role.id);
    } catch (err) {
      setError(err.message || "Could not create role.");
    }
  }

  async function handleSaveMatrix() {
    if (!selectedRole) return;
    setSaving(true);
    setError("");
    try {
      const permissions = Object.entries(matrix).map(([module, flags]) => ({ module, ...flags }));
      const updated = await api.put(`/admin/rbac/roles/${selectedRole.id}`, { permissions });
      setRoles((rs) => rs.map((r) => (r.id === updated.id ? updated : r)));
    } catch (err) {
      setError(err.message || "Could not save permissions.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteRole(role) {
    if (!confirm(`Delete role "${role.name}"? This cannot be undone.`)) return;
    try {
      await api.del(`/admin/rbac/roles/${role.id}`);
      setSelectedId(null);
      load();
    } catch (err) {
      alert(err.message || "Could not delete role.");
    }
  }

  if (!roles || !catalog) return <Loading />;

  return (
    <div>
      <div className="admin-page-head">
        <h1>Roles & Permissions</h1>
        <button className="btn btn-sm btn-primary" onClick={() => setShowCreate((s) => !s)}>
          {showCreate ? "Cancel" : "+ Create Role"}
        </button>
      </div>

      {showCreate && (
        <div className="admin-form-card">
          <form onSubmit={handleCreateRole}>
            <div className="form-group">
              <label>Role Name</label>
              <input className="form-control" required value={newRoleName} onChange={(e) => setNewRoleName(e.target.value)} />
            </div>
            <div className="form-group">
              <label>Description</label>
              <input className="form-control" value={newRoleDesc} onChange={(e) => setNewRoleDesc(e.target.value)} />
            </div>
            <button className="btn btn-primary">Create Role</button>
          </form>
        </div>
      )}

      <div style={{ display: "flex", gap: 24, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div className="admin-table-wrap" style={{ minWidth: 280, flex: "0 0 280px" }}>
          <table className="admin-table">
            <thead>
              <tr>
                <th>Role</th>
                <th>Users</th>
              </tr>
            </thead>
            <tbody>
              {roles.map((r) => (
                <tr
                  key={r.id}
                  onClick={() => setSelectedId(r.id)}
                  style={{ cursor: "pointer", background: r.id === selectedId ? "var(--color-surface-alt, #f2f2f2)" : undefined }}
                >
                  <td>
                    {r.name}
                    {r.is_system && (
                      <span className="badge badge-accent" style={{ marginLeft: 8 }}>
                        System
                      </span>
                    )}
                  </td>
                  <td>{r.user_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ flex: "1 1 500px", minWidth: 320 }}>
          {!selectedRole ? (
            <Empty>Select a role to view its permissions.</Empty>
          ) : (
            <>
              <h3 style={{ marginTop: 0 }}>{selectedRole.name}</h3>
              {selectedRole.description && (
                <p style={{ color: "var(--color-text-muted)", fontSize: "0.88rem" }}>{selectedRole.description}</p>
              )}
              {error && <div className="alert alert-error">{error}</div>}
              {selectedRole.is_system ? (
                <p style={{ color: "var(--color-text-muted)", fontSize: "0.88rem" }}>
                  System roles are fixed and cannot be edited or deleted.
                </p>
              ) : null}

              <div className="admin-table-wrap">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Module</th>
                      {catalog.actions.map((a) => (
                        <th key={a} style={{ textAlign: "center" }}>
                          {ACTION_LABELS[a] || a}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {catalog.modules.map((mod) => (
                      <tr key={mod}>
                        <td>{MODULE_LABELS[mod] || mod}</td>
                        {catalog.actions.map((a) => {
                          const field = `can_${a.toLowerCase()}`;
                          return (
                            <td key={a} style={{ textAlign: "center" }}>
                              <input
                                type="checkbox"
                                disabled={selectedRole.is_system}
                                checked={Boolean(matrix[mod]?.[field])}
                                onChange={() => toggle(mod, field)}
                              />
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {!selectedRole.is_system && (
                <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
                  <button className="btn btn-primary" disabled={saving} onClick={handleSaveMatrix}>
                    {saving ? "Saving..." : "Save Permissions"}
                  </button>
                  <button
                    className="btn btn-danger"
                    disabled={selectedRole.user_count > 0}
                    title={selectedRole.user_count > 0 ? "Reassign users before deleting this role" : ""}
                    onClick={() => handleDeleteRole(selectedRole)}
                  >
                    Delete Role
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
