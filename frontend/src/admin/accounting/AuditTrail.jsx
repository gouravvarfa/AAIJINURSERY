import { useEffect, useState } from "react";
import { formatIst } from "../communications/time";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";

// Field-level change history for any Accounting document -- reads from the
// same accounting_audit_log table every write endpoint already records into
// via record_change(), just never had a UI to view it until now.
export default function AuditTrail({ tableName, recordId }) {
  const [entries, setEntries] = useState(null);

  useEffect(() => {
    setEntries(null);
    api
      .get(`/admin/accounting/audit-log?table_name=${tableName}&record_id=${recordId}`)
      .then(setEntries);
  }, [tableName, recordId]);

  return (
    <div className="admin-form-card no-print" style={{ maxWidth: "none" }}>
      <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Audit Trail</h2>
      {!entries ? (
        <Loading />
      ) : entries.length === 0 ? (
        <Empty>No recorded changes yet.</Empty>
      ) : (
        <div className="admin-order-status-history">
          {entries.map((e) => (
            <div key={e.id} className="admin-order-status-history-item">
              <strong>
                {e.action === "create" && "Created"}
                {e.action === "update" && `Updated ${e.field_name}`}
                {e.action === "void" && "Voided"}
                {e.action === "convert" && "Converted"}
                {!["create", "update", "void", "convert"].includes(e.action) && e.action}
              </strong>
              {e.field_name && e.action === "update" && (
                <div className="meta">
                  {e.old_value ?? "(empty)"} &rarr; {e.new_value ?? "(empty)"}
                </div>
              )}
              <div className="meta">
                {formatIst(e.changed_at)} &middot; by {e.changed_by || "system"}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
