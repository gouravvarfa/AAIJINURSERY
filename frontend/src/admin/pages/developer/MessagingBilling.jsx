import { useEffect, useState } from "react";
import { api } from "../../../api";
import { Loading } from "../../../components/Loading";

const rupees = (n) => `₹${Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const when = (iso) => (iso ? new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" }) : "-");
const dayLabel = (d) => new Date(`${d}T00:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" });
const CATEGORY_LABEL = { UTILITY: "Utility (order/delivery/invoice)", MARKETING: "Marketing (review, welcome)", AUTHENTICATION: "Authentication", SERVICE: "Free (customer replied)" };

// Developer-only: the WhatsApp (Meta) prepaid balance. Top-ups are entered
// here; spend is Meta's own billed cost, so nobody has to open Meta to see
// what is left.
export default function MessagingBilling() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [date, setDate] = useState("");

  function load(refresh = false) {
    setBusy(true);
    api
      .get(`/admin/messaging-billing${refresh ? "?refresh=true" : ""}`)
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((err) => setError(err.message || "Could not load the billing details."))
      .finally(() => setBusy(false));
  }

  useEffect(() => load(), []);

  async function addTopup(e) {
    e.preventDefault();
    setError("");
    try {
      await api.post("/admin/messaging-billing/topups", {
        amount: Number(amount),
        note,
        topup_date: date ? `${date}T12:00:00+05:30` : null,
      });
      setAmount("");
      setNote("");
      setDate("");
      load(true);
    } catch (err) {
      setError(err.message || "Could not add the top-up.");
    }
  }

  async function removeTopup(t) {
    if (!window.confirm(`Remove the ${rupees(t.amount)} top-up from ${when(t.topup_date)}? Only do this if it was entered by mistake.`)) return;
    try {
      await api.delete(`/admin/messaging-billing/topups/${t.id}`);
      load(true);
    } catch (err) {
      setError(err.message || "Could not remove the top-up.");
    }
  }

  if (!data && !error) return <Loading />;

  return (
    <div>
      <div className="admin-page-head">
        <h1>Messaging Bill</h1>
        <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => load(true)}>
          {busy ? "Refreshing..." : "Refresh from Meta"}
        </button>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {data?.error && <div className="alert alert-error">{data.error}</div>}

      {data && (
        <>
          {data.low_balance && (
            <div className="alert alert-error">
              Balance is below {rupees(data.low_balance_limit)}. Add money in Meta Business Manager before WhatsApp messages start failing.
            </div>
          )}

          <div className="admin-form-card" style={{ marginBottom: 20 }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 28 }}>
              <div>
                <div style={{ color: "var(--color-text-muted)" }}>Balance left</div>
                <div style={{ fontSize: "2rem", fontWeight: 700, color: data.low_balance ? "#a52a1d" : "#1f7a45" }}>{rupees(data.balance)}</div>
              </div>
              <div>
                <div style={{ color: "var(--color-text-muted)" }}>Total added</div>
                <div style={{ fontSize: "1.4rem", fontWeight: 600 }}>{rupees(data.total_added)}</div>
              </div>
              <div>
                <div style={{ color: "var(--color-text-muted)" }}>Total spent</div>
                <div style={{ fontSize: "1.4rem", fontWeight: 600 }}>{rupees(data.total_spent)}</div>
              </div>
              <div>
                <div style={{ color: "var(--color-text-muted)" }}>Messages</div>
                <div style={{ fontSize: "1.4rem", fontWeight: 600 }}>{data.messages_billed_or_free}</div>
              </div>
            </div>
            <p style={{ color: "var(--color-text-muted)", fontSize: "0.82rem", margin: "14px 0 0" }}>
              Spend is the cost Meta itself reports; Meta can take a few hours to update. Meta does not share the remaining balance, so
              balance = money you added below &minus; Meta&apos;s spend. {data.fetched_at && <>Updated {when(data.fetched_at)}.</>}
            </p>
          </div>

          <div className="admin-form-card" style={{ marginBottom: 20 }}>
            <h3 style={{ marginTop: 0 }}>Add money you put in Meta</h3>
            <form onSubmit={addTopup} style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "flex-end" }}>
              <label style={{ display: "grid", gap: 4 }}>
                Amount (₹)
                <input type="number" min="1" step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} style={{ width: 130 }} />
              </label>
              <label style={{ display: "grid", gap: 4 }}>
                Date (blank = now)
                <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
              </label>
              <label style={{ display: "grid", gap: 4, flex: "1 1 180px" }}>
                Note
                <input type="text" maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. UPI recharge" />
              </label>
              <button type="submit" className="btn btn-primary">Add</button>
            </form>
          </div>

          <div className="admin-form-card" style={{ marginBottom: 20 }}>
            <h3 style={{ marginTop: 0 }}>Money added</h3>
            {data.topups.length === 0 ? (
              <p style={{ color: "var(--color-text-muted)", margin: 0 }}>Nothing added yet. Add your first recharge above to start the balance.</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="admin-table">
                  <thead>
                    <tr><th>When</th><th>Amount</th><th>Note</th><th>By</th><th /></tr>
                  </thead>
                  <tbody>
                    {data.topups.map((t) => (
                      <tr key={t.id}>
                        <td>{when(t.topup_date)}</td>
                        <td>{rupees(t.amount)}</td>
                        <td>{t.note || "-"}</td>
                        <td>{t.added_by}</td>
                        <td><button type="button" className="btn btn-secondary btn-sm" onClick={() => removeTopup(t)}>Remove</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="admin-form-card" style={{ marginBottom: 20 }}>
            <h3 style={{ marginTop: 0 }}>Spent, by message type</h3>
            {data.by_category.length === 0 ? (
              <p style={{ color: "var(--color-text-muted)", margin: 0 }}>No spend reported yet.</p>
            ) : (
              <table className="admin-table">
                <thead><tr><th>Type</th><th>Messages</th><th>Cost</th></tr></thead>
                <tbody>
                  {data.by_category.map((c) => (
                    <tr key={c.category}><td>{CATEGORY_LABEL[c.category] || c.category}</td><td>{c.volume}</td><td>{rupees(c.cost)}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="admin-form-card">
            <h3 style={{ marginTop: 0 }}>Day-by-day history</h3>
            {data.days.length === 0 ? (
              <p style={{ color: "var(--color-text-muted)", margin: 0 }}>No messages billed since your first top-up.</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="admin-table">
                  <thead>
                    <tr><th>Day</th><th>Utility</th><th>Marketing</th><th>Free</th><th>Total msgs</th><th>Cost</th></tr>
                  </thead>
                  <tbody>
                    {data.days.map((d) => (
                      <tr key={d.date}>
                        <td>{dayLabel(d.date)}</td>
                        <td>{d.utility}</td>
                        <td>{d.marketing}</td>
                        <td>{d.free}</td>
                        <td>{d.volume}</td>
                        <td>{rupees(d.cost)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
