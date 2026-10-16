import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import CustomerBalanceCard from "./CustomerBalanceCard";

const rs = (n) => `₹${Math.abs(Number(n) || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const newId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
const METHODS = ["Cash", "Bank", "UPI", "Card", "Online", "Other"];
const KIND = { advance: "Advance", overpayment: "Extra payment kept as advance", void_transfer: "From a voided invoice" };

// Advance money, refunds, voided-invoice payments and linked customers for one customer.
export default function CustomerAccountPanel({ contactId }) {
  const [pos, setPos] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [tick, setTick] = useState(0);
  const [form, setForm] = useState({ amount: "", method: "Cash", reference: "", notes: "" });
  const [refund, setRefund] = useState(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const requestId = useRef(newId());

  useEffect(() => {
    api.get(`/admin/accounting/customers/${contactId}/position`).then(setPos).catch((e) => setError(e.message || "Could not load the account."));
    api.get("/admin/accounting/contact-links/suggestions").then((all) => setSuggestions(all.filter((s) => s.a.id === Number(contactId) || s.b.id === Number(contactId)))).catch(() => {});
  }, [contactId, tick]);

  async function run(fn, done) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await fn();
      setMsg(done);
      setTick((t) => t + 1);
    } catch (e) {
      setError(e.message || "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const receive = (e) => {
    e.preventDefault();
    run(async () => {
      await api.post(`/admin/accounting/customers/${contactId}/receipts`, { amount: Number(form.amount), method: form.method, reference: form.reference, notes: form.notes, request_id: requestId.current });
      requestId.current = newId();
      setForm({ amount: "", method: "Cash", reference: "", notes: "" });
    }, "Advance saved.");
  };
  const doRefund = (e) => {
    e.preventDefault();
    run(async () => {
      await api.post(`/admin/accounting/receipts/${refund.id}/refund`, { amount: Number(refund.amount), method: refund.method, reason: refund.reason });
      setRefund(null);
    }, "Refund recorded.");
  };

  if (!pos) return error ? <div className="alert alert-error">{error}</div> : null;
  const other = (s) => (s.a.id === Number(contactId) ? s.b : s.a);
  return (
    <section className="acct-panel">
      <h2>Customer account</h2>
      <CustomerBalanceCard contactId={contactId} refreshKey={tick} />
      {msg && <div className="alert alert-success" role="status">{msg}</div>}
      {error && <div className="alert alert-error">{error}</div>}

      {pos.unresolved_void_payments.length > 0 && (
        <div className="acct-warn">
          <strong>Payments on voided invoices need a decision</strong>
          <p>Until you decide, the money is kept as this customer's credit (nothing is lost). Choose what really happened to it.</p>
          {pos.unresolved_void_payments.map((u) => (
            <div key={u.invoice_id} className="acct-row">
              <span>{u.invoice_number} ({u.status}): <b>{rs(u.amount)}</b> was paid</span>
              <span>
                <button type="button" className="btn btn-sm btn-outline dark" disabled={busy} onClick={() => run(() => api.post(`/admin/accounting/invoices/${u.invoice_id}/resolve-void-payments`, { action: "advance" }), "Kept as advance.")}>Keep as advance</button>{" "}
                <button type="button" className="btn btn-sm btn-outline dark" disabled={busy} onClick={() => window.confirm(`Record that ${rs(u.amount)} was refunded to the customer?`) && run(() => api.post(`/admin/accounting/invoices/${u.invoice_id}/resolve-void-payments`, { action: "refund", notes: "Refunded after the invoice was voided" }), "Refund recorded.")}>Refund</button>
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="acct-grid">
        <form onSubmit={receive} className="acct-card">
          <h3>Receive advance</h3>
          <p className="stock-hint">Money from the customer that is not for one bill yet. It is used on a later invoice.</p>
          <label>Amount (₹)<input className="form-control" required inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value.replace(/[^0-9.]/g, "") })} /></label>
          <label>Method
            <select className="form-control" value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })}>{METHODS.map((m) => <option key={m}>{m}</option>)}</select>
          </label>
          <label>Reference (optional)<input className="form-control" maxLength={120} value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} /></label>
          <label>Notes (optional)<input className="form-control" maxLength={1000} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></label>
          <button className="btn btn-primary" disabled={busy || !Number(form.amount)}>{busy ? "Saving..." : "Save advance"}</button>
        </form>

        <div className="acct-card">
          <h3>Advance history</h3>
          {pos.receipts.length === 0 ? <p className="stock-hint">No advance yet.</p> : pos.receipts.map((r) => (
            <div key={r.id} className={`acct-receipt${r.status === "Reversed" ? " reversed" : ""}`}>
              <div className="acct-row">
                <span><b>{rs(r.amount)}</b> · {KIND[r.kind] || r.kind}{r.status === "Reversed" ? " (reversed)" : ""}<small>{new Date(r.payment_date).toLocaleDateString("en-IN")} · {r.method}{r.reference ? ` · ${r.reference}` : ""}</small></span>
                {r.status === "Active" && <span className="acct-left">{rs(r.remaining)} left</span>}
              </div>
              {r.allocations.map((a) => <small key={a.id} className="acct-sub">Used {rs(a.amount)} on <Link to={`/admin/accounting/invoices/${a.invoice_id}`}>{a.invoice_number}</Link>{a.live ? "" : " (voided: returned)"}</small>)}
              {r.refunds.map((f) => <small key={f.id} className="acct-sub">Refunded {rs(f.amount)} ({f.reason})</small>)}
              {r.status === "Active" && (
                <div className="acct-actions">
                  {r.remaining > 0 && <button type="button" className="btn btn-sm btn-outline dark" onClick={() => setRefund({ id: r.id, amount: String(r.remaining), method: "Cash", reason: "" })}>Refund</button>}
                  {r.kind !== "void_transfer" && r.allocations.length === 0 && r.refunds.length === 0 && <button type="button" className="btn btn-sm btn-outline dark" disabled={busy} onClick={() => window.confirm("Reverse this advance? Use this only if it was entered by mistake.") && run(() => api.post(`/admin/accounting/receipts/${r.id}/reverse`, {}), "Advance reversed.")}>Reverse (entered by mistake)</button>}
                </div>
              )}
            </div>
          ))}
          {refund && (
            <form onSubmit={doRefund} className="acct-refund">
              <h4>Refund to customer</h4>
              <label>Amount (₹)<input className="form-control" required inputMode="decimal" value={refund.amount} onChange={(e) => setRefund({ ...refund, amount: e.target.value.replace(/[^0-9.]/g, "") })} /></label>
              <label>Method<select className="form-control" value={refund.method} onChange={(e) => setRefund({ ...refund, method: e.target.value })}>{METHODS.map((m) => <option key={m}>{m}</option>)}</select></label>
              <label>Reason<input className="form-control" required minLength={3} value={refund.reason} onChange={(e) => setRefund({ ...refund, reason: e.target.value })} /></label>
              <button className="btn btn-primary" disabled={busy || !Number(refund.amount) || refund.reason.trim().length < 3}>Record refund</button>{" "}
              <button type="button" className="btn btn-outline dark" onClick={() => setRefund(null)}>Cancel</button>
            </form>
          )}
        </div>
      </div>

      <div className="acct-card">
        <h3>Same customer, two accounts?</h3>
        {pos.linked_contacts.length > 1 && (
          <p className="stock-hint">Linked and counted together: {pos.linked_contacts.map((c) => `${c.name}${c.phone ? ` (${c.phone})` : ""}`).join(" + ")}</p>
        )}
        {suggestions.length === 0 && pos.linked_contacts.length <= 1 && <p className="stock-hint">No other account with the same mobile number was found. Records are never merged automatically.</p>}
        {suggestions.map((s) => (
          <div key={`${s.a.id}-${s.b.id}`} className="acct-row">
            <span>{other(s).name} <small>({other(s).source === "online" ? "website" : "phone/counter"}, same mobile {s.phone}, balance {other(s).net >= 0 ? rs(other(s).net) : `${rs(other(s).net)} advance`})</small></span>
            <span>
              <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={() => window.confirm(`Treat ${other(s).name} and this customer as ONE customer? Their balances will be added together. Nothing is merged or deleted, and you can unlink later.`) && run(() => api.post("/admin/accounting/contact-links/confirm", { contact_a_id: s.a.id, contact_b_id: s.b.id }), "Linked. Balances are now counted together.")}>Same customer: link</button>{" "}
              <button type="button" className="btn btn-sm btn-outline dark" disabled={busy} onClick={() => run(() => api.post("/admin/accounting/contact-links/reject", { contact_a_id: s.a.id, contact_b_id: s.b.id }), "Marked as different customers.")}>Different person</button>
            </span>
          </div>
        ))}
        <LinkedList contactId={contactId} tick={tick} busy={busy} onUnlink={(id) => run(() => api.post(`/admin/accounting/contact-links/${id}/unlink`, {}), "Unlinked. Balances are separate again.")} />
      </div>
    </section>
  );
}

function LinkedList({ contactId, tick, busy, onUnlink }) {
  const [links, setLinks] = useState([]);
  useEffect(() => {
    api.get("/admin/accounting/contact-links?status=Confirmed").then((all) => setLinks(all.filter((l) => l.a.id === Number(contactId) || l.b.id === Number(contactId)))).catch(() => {});
  }, [contactId, tick]);
  return links.map((l) => (
    <div key={l.id} className="acct-row">
      <span>Linked: {l.a.name} + {l.b.name}</span>
      <button type="button" className="btn btn-sm btn-outline dark" disabled={busy} onClick={() => window.confirm("Unlink these accounts? Their balances become separate again.") && onUnlink(l.id)}>Unlink</button>
    </div>
  ));
}
