import { useEffect, useState } from "react";
import { api } from "../../api";

const rs = (n) => `₹${Math.abs(Number(n) || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

// What this customer owes (or has paid in advance) today. Same numbers everywhere: the server
// works it out once (Net = invoices - payments - advances). Linked contacts are included.
export default function CustomerBalanceCard({ contactId, refreshKey = 0, onLoaded }) {
  const [pos, setPos] = useState(null);

  useEffect(() => {
    if (!contactId) { setPos(null); return; }
    let live = true;
    api.get(`/admin/accounting/customers/${contactId}/position`).then((p) => { if (live) { setPos(p); onLoaded?.(p); } }).catch(() => { if (live) setPos(null); });
    return () => { live = false; };
  }, [contactId, refreshKey]);

  if (!contactId || !pos) return null;
  const owes = pos.net > 0;
  const credit = pos.net < 0;
  return (
    <div className={`cust-balance ${owes ? "owes" : credit ? "credit" : "clear"}`} role="status" aria-label="Customer balance">
      <div className="cust-balance-main">
        <small>{owes ? "Customer owes" : credit ? "Customer has advance" : "Account is clear"}</small>
        <strong>{owes || credit ? rs(pos.net) : "₹0"}</strong>
      </div>
      <div className="cust-balance-split">
        <span>Unpaid invoices <b>{rs(pos.due)}</b></span>
        <span>Advance with us <b>{rs(pos.advance)}</b></span>
      </div>
      {pos.linked_contacts?.length > 1 && (
        <small className="cust-balance-note">Includes linked accounts: {pos.linked_contacts.map((c) => c.name).join(", ")}</small>
      )}
      {pos.unresolved_void_amount > 0 && (
        <small className="cust-balance-warn">{rs(pos.unresolved_void_amount)} paid on a voided invoice is waiting for a decision (see Customer page).</small>
      )}
    </div>
  );
}
