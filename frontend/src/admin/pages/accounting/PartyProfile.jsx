import { useEffect, useState } from "react";
import { formatIst, formatIstDate } from "../../communications/time";
import { Link, useParams } from "react-router-dom";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import ExportButton from "../../accounting/ExportButton";
import {
  invoiceBadgeClass,
  salesOrderBadgeClass,
  billBadgeClass,
  purchaseOrderBadgeClass,
  expenseBadgeClass,
  sourceBadgeClass,
} from "../../accounting/accountingStatus";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "timeline", label: "Timeline" },
  { id: "sales-orders", label: "Sales Orders" },
  { id: "invoices", label: "Invoices" },
  { id: "bills", label: "Purchase Bills" },
  { id: "payments", label: "Payments" },
  { id: "expenses", label: "Expenses" },
  { id: "items", label: "Items" },
  { id: "statement", label: "Statement" },
];

function money(n) {
  return `₹${(n || 0).toLocaleString()}`;
}

function typeIcon(source) {
  return source === "online" ? "🟢" : "🔵";
}

export default function PartyProfile() {
  const { id } = useParams();
  const [party, setParty] = useState(null);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState("overview");
  const [sourceFilter, setSourceFilter] = useState("");
  const [tabData, setTabData] = useState(null);
  const [tabLoadedFor, setTabLoadedFor] = useState(null);

  function loadParty() {
    setParty(null);
    setError("");
    api
      .get(`/admin/accounting/contacts/${id}`)
      .then(setParty)
      .catch((err) => setError(err.message || "Could not load this party."));
  }

  useEffect(loadParty, [id]);

  useEffect(() => {
    if (activeTab === "overview") return;
    setTabData(null);
    const key = `${activeTab}-${sourceFilter}`;
    let url = "";
    if (activeTab === "timeline") {
      url = `/admin/accounting/parties/${id}/timeline${sourceFilter ? `?source=${sourceFilter}` : ""}`;
    } else if (activeTab === "sales-orders") {
      const params = new URLSearchParams({ contact_id: id });
      if (sourceFilter) params.set("source", sourceFilter);
      url = `/admin/accounting/sales-orders?${params.toString()}`;
    } else if (activeTab === "invoices") {
      const params = new URLSearchParams({ contact_id: id });
      if (sourceFilter) params.set("source", sourceFilter);
      url = `/admin/accounting/invoices?${params.toString()}`;
    } else if (activeTab === "bills") {
      url = `/admin/accounting/bills?contact_id=${id}`;
    } else if (activeTab === "payments") {
      Promise.all([
        api.get(`/admin/accounting/payments-in?contact_id=${id}`),
        api.get(`/admin/accounting/payments-out?contact_id=${id}`),
      ]).then(([ins, outs]) => {
        let combined = [
          ...ins.map((p) => ({ ...p, direction: "in" })),
          ...outs.map((p) => ({ ...p, direction: "out" })),
        ];
        if (sourceFilter) combined = combined.filter((p) => p.source === sourceFilter);
        combined.sort((a, b) => new Date(b.payment_date) - new Date(a.payment_date));
        setTabData(combined);
        setTabLoadedFor(key);
      });
      return;
    } else if (activeTab === "expenses") {
      url = `/admin/accounting/expenses?contact_id=${id}`;
    } else if (activeTab === "items") {
      url = `/admin/accounting/parties/${id}/items`;
    } else if (activeTab === "statement") {
      url = `/admin/accounting/parties/${id}/statement${sourceFilter ? `?source=${sourceFilter}` : ""}`;
    }

    if (url) {
      api.get(url).then((result) => {
        let rows = result;
        if (["bills", "expenses"].includes(activeTab) && sourceFilter) {
          rows = (Array.isArray(result) ? result : []).filter((r) => r.source === sourceFilter);
        }
        setTabData(rows);
        setTabLoadedFor(key);
      });
    }
  }, [activeTab, sourceFilter, id]);

  if (error && !party) return <div className="alert alert-error">{error}</div>;
  if (!party) return <Loading />;

  const channelLabel =
    party.channels?.length === 2 ? "Online + Offline" : party.channels?.length === 1 ? party.channels[0] : "No activity yet";

  return (
    <div>
      <div className="admin-page-head">
        <div>
          <h1 style={{ marginBottom: 4 }}>{party.name}</h1>
          <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span className="badge badge-muted" style={{ textTransform: "capitalize" }}>{party.contact_type}</span>
            <span className={`badge ${party.channels?.length === 2 ? "badge-accent" : sourceBadgeClass(party.channels?.[0])}`}>
              {channelLabel}
            </span>
            <span className={`badge ${party.is_active ? "badge-accent" : "badge-muted"}`}>
              {party.is_active ? "Active" : "Inactive"}
            </span>
          </span>
        </div>
        <Link className="btn btn-sm btn-outline dark" to="/admin/accounting/parties">
          &larr; Back to Parties
        </Link>
      </div>

      <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", color: "var(--color-text-muted)", fontSize: "0.9rem" }}>
          {party.phone && <span>📞 {party.phone}</span>}
          {party.email && <span>✉️ {party.email}</span>}
          {party.gstin && <span>GSTIN: {party.gstin}</span>}
          {party.address && <span>📍 {party.address}</span>}
        </div>
      </div>

      <div className="stat-cards" style={{ marginBottom: 24 }}>
        <div className="stat-card"><div className="num">{money(party.total_sales)}</div><div className="label">Total Sales</div></div>
        <div className="stat-card"><div className="num">{money(party.total_purchases)}</div><div className="label">Total Purchases</div></div>
        <div className="stat-card"><div className="num">{money(party.total_paid)}</div><div className="label">Total Received</div></div>
        <div className="stat-card"><div className="num">{money(party.total_paid_out)}</div><div className="label">Total Paid Out</div></div>
        <div className="stat-card"><div className="num">{money(party.outstanding)}</div><div className="label">Receivable</div></div>
        <div className="stat-card"><div className="num">{money(party.payable)}</div><div className="label">Payable</div></div>
        <div className="stat-card"><div className="num">{money(party.online_sales)}</div><div className="label">Online Sales</div></div>
        <div className="stat-card"><div className="num">{money(party.offline_sales)}</div><div className="label">Offline Sales</div></div>
        <div className="stat-card"><div className="num">{party.orders_count}</div><div className="label">Sales Orders</div></div>
        <div className="stat-card"><div className="num">{party.invoices_count}</div><div className="label">Invoices</div></div>
        <div className="stat-card"><div className="num">{party.payments_count}</div><div className="label">Payments</div></div>
        <div className="stat-card">
          <div className="num" style={{ fontSize: "1rem" }}>
            {party.last_transaction_date ? new Date(party.last_transaction_date).toLocaleDateString() : "-"}
          </div>
          <div className="label">Last Transaction</div>
        </div>
      </div>

      <nav className="analytics-jump-nav" style={{ marginBottom: 16 }}>
        {TABS.map((t) => (
          <a
            key={t.id}
            href="#"
            onClick={(e) => {
              e.preventDefault();
              setActiveTab(t.id);
            }}
            style={t.id === activeTab ? { fontWeight: 700, textDecoration: "underline" } : undefined}
          >
            {t.label}
          </a>
        ))}
      </nav>

      {activeTab !== "overview" && activeTab !== "items" && (
        <div style={{ marginBottom: 16 }}>
          <select className="form-control" style={{ maxWidth: 180 }} value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
            <option value="">All Sources</option>
            <option value="online">Online</option>
            <option value="offline">Offline</option>
          </select>
        </div>
      )}

      {activeTab === "overview" && <OverviewTab party={party} />}

      {activeTab === "timeline" && (
        !tabData || tabLoadedFor !== `timeline-${sourceFilter}` ? <Loading /> : <TimelineTab rows={tabData} />
      )}

      {activeTab === "sales-orders" && (
        !tabData || tabLoadedFor !== `sales-orders-${sourceFilter}` ? <Loading /> : <SalesOrdersTab rows={tabData} />
      )}

      {activeTab === "invoices" && (
        !tabData || tabLoadedFor !== `invoices-${sourceFilter}` ? <Loading /> : <InvoicesTab rows={tabData} />
      )}

      {activeTab === "bills" && (
        !tabData || tabLoadedFor !== `bills-${sourceFilter}` ? <Loading /> : <BillsTab rows={tabData} />
      )}

      {activeTab === "payments" && (
        !tabData || tabLoadedFor !== `payments-${sourceFilter}` ? <Loading /> : <PaymentsTab rows={tabData} />
      )}

      {activeTab === "expenses" && (
        !tabData || tabLoadedFor !== `expenses-${sourceFilter}` ? <Loading /> : <ExpensesTab rows={tabData} />
      )}

      {activeTab === "items" && (
        !tabData || tabLoadedFor !== "items-" ? <Loading /> : <ItemsTab data={tabData} />
      )}

      {activeTab === "statement" && (
        !tabData || tabLoadedFor !== `statement-${sourceFilter}` ? (
          <Loading />
        ) : (
          <StatementTab data={tabData} partyId={id} sourceFilter={sourceFilter} />
        )
      )}
    </div>
  );
}

function OverviewTab({ party }) {
  return (
    <div className="admin-form-card" style={{ maxWidth: "none" }}>
      <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Party Details</h2>
      <div className="form-group"><label>Type</label><div style={{ textTransform: "capitalize" }}>{party.contact_type}</div></div>
      <div className="form-group"><label>Source (record created via)</label><div>{party.source === "online" ? "Online (website)" : "Offline (manual)"}</div></div>
      <div className="form-group"><label>Channels used</label><div>{party.channels?.length ? party.channels.join(" + ") : "None yet"}</div></div>
      <div className="form-group" style={{ marginBottom: 0 }}><label>Created</label><div>{formatIstDate(party.created_at)}</div></div>
    </div>
  );
}

function TimelineTab({ rows }) {
  if (rows.length === 0) return <Empty>No activity yet for this filter.</Empty>;
  return (
    <div className="admin-order-status-history">
      {rows.map((r, i) => (
        <div key={i} className="admin-order-status-history-item">
          <strong>{typeIcon(r.source)} {r.label}</strong>
          {r.amount != null && <span> -- ₹{r.amount.toLocaleString()}</span>}
          <div className="meta">{formatIst(r.date)} &middot; {r.reference}</div>
        </div>
      ))}
    </div>
  );
}

function SalesOrdersTab({ rows }) {
  if (rows.length === 0) return <Empty>No sales orders for this party.</Empty>;
  return (
    <div className="admin-table-wrap">
      <table className="admin-table">
        <thead><tr><th>Order #</th><th>Date</th><th>Amount</th><th>Status</th><th>Source</th><th>Actions</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.order_number}</td>
              <td>{new Date(r.order_date).toLocaleDateString()}</td>
              <td>{money(r.total_amount)}</td>
              <td><span className={`badge ${salesOrderBadgeClass(r.status)}`}>{r.status}</span></td>
              <td><span className={`badge ${sourceBadgeClass(r.source)}`}>{r.source}</span></td>
              <td><Link className="btn btn-sm btn-outline dark" to={`/admin/accounting/sales-orders/${r.id}`}>View</Link></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InvoicesTab({ rows }) {
  if (rows.length === 0) return <Empty>No invoices for this party.</Empty>;
  return (
    <div className="admin-table-wrap">
      <table className="admin-table">
        <thead><tr><th>Invoice #</th><th>Date</th><th>Amount</th><th>Paid</th><th>Balance</th><th>Status</th><th>Source</th><th>Actions</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.invoice_number}</td>
              <td>{new Date(r.invoice_date).toLocaleDateString()}</td>
              <td>{money(r.total_amount)}</td>
              <td>{money(r.amount_paid)}</td>
              <td>{money(r.balance_due)}</td>
              <td><span className={`badge ${invoiceBadgeClass(r.status)}`}>{r.status}</span></td>
              <td><span className={`badge ${sourceBadgeClass(r.source)}`}>{r.source}</span></td>
              <td><Link className="btn btn-sm btn-outline dark" to={`/admin/accounting/invoices/${r.id}`}>View</Link></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BillsTab({ rows }) {
  if (rows.length === 0) return <Empty>No purchase bills for this party.</Empty>;
  return (
    <div className="admin-table-wrap">
      <table className="admin-table">
        <thead><tr><th>Bill #</th><th>Date</th><th>Amount</th><th>Paid</th><th>Balance</th><th>Status</th><th>Source</th><th>Actions</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.invoice_number || `#${r.id}`}</td>
              <td>{new Date(r.purchase_date).toLocaleDateString()}</td>
              <td>{money(r.total_cost)}</td>
              <td>{money(r.amount_paid)}</td>
              <td>{money(r.balance_due)}</td>
              <td><span className={`badge ${billBadgeClass(r.status)}`}>{r.status}</span></td>
              <td><span className={`badge ${sourceBadgeClass(r.source)}`}>{r.source}</span></td>
              <td><Link className="btn btn-sm btn-outline dark" to={`/admin/accounting/bills/${r.id}`}>View</Link></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PaymentsTab({ rows }) {
  if (rows.length === 0) return <Empty>No payments for this party.</Empty>;
  return (
    <div className="admin-table-wrap">
      <table className="admin-table">
        <thead><tr><th>Date</th><th>Direction</th><th>Amount</th><th>Method</th><th>Reference</th><th>Source</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.direction}-${r.id}`}>
              <td>{new Date(r.payment_date).toLocaleDateString()}</td>
              <td>{r.direction === "in" ? "Money Received" : "Payment Out"}</td>
              <td>{money(r.amount)}</td>
              <td>{r.method}</td>
              <td>{r.reference || "-"}</td>
              <td><span className={`badge ${sourceBadgeClass(r.source)}`}>{r.source}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExpensesTab({ rows }) {
  if (rows.length === 0) return <Empty>No expenses linked to this party.</Empty>;
  return (
    <div className="admin-table-wrap">
      <table className="admin-table">
        <thead><tr><th>Category</th><th>Date</th><th>Amount</th><th>Status</th><th>Source</th><th>Actions</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.category}</td>
              <td>{new Date(r.expense_date).toLocaleDateString()}</td>
              <td>{money(r.total_amount)}</td>
              <td><span className={`badge ${expenseBadgeClass(r.status)}`}>{r.status}</span></td>
              <td><span className={`badge ${sourceBadgeClass(r.source)}`}>{r.source}</span></td>
              <td><Link className="btn btn-sm btn-outline dark" to={`/admin/accounting/expenses/${r.id}`}>View</Link></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ItemsTab({ data }) {
  return (
    <>
      <h3 style={{ fontSize: "1rem" }}>Items Sold to This Party</h3>
      {data.sold.length === 0 ? (
        <Empty>No sales items yet.</Empty>
      ) : (
        <div className="admin-table-wrap" style={{ marginBottom: 24 }}>
          <table className="admin-table">
            <thead><tr><th>Item</th><th>Quantity</th><th>Total Value</th><th>Last Purchase</th></tr></thead>
            <tbody>
              {data.sold.map((r, i) => (
                <tr key={i}>
                  <td>{r.name}</td>
                  <td>{r.quantity}</td>
                  <td>{money(r.total_value)}</td>
                  <td>{r.last_transaction ? new Date(r.last_transaction).toLocaleDateString() : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h3 style={{ fontSize: "1rem" }}>Items Purchased From This Party</h3>
      {data.purchased.length === 0 ? (
        <Empty>No purchase items yet.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead><tr><th>Item</th><th>Quantity</th><th>Total Value</th><th>Last Purchase</th></tr></thead>
            <tbody>
              {data.purchased.map((r, i) => (
                <tr key={i}>
                  <td>{r.name}</td>
                  <td>{r.quantity}</td>
                  <td>{money(r.total_value)}</td>
                  <td>{r.last_transaction ? new Date(r.last_transaction).toLocaleDateString() : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function StatementTab({ data, partyId, sourceFilter }) {
  return (
    <>
      <div style={{ marginBottom: 12 }}>
        <ExportButton
          baseUrl={`/api/admin/accounting/parties/${partyId}/export-statement.xlsx${sourceFilter ? `?source=${sourceFilter}` : ""}`}
          label="Export Statement"
        />
      </div>
      {data.rows.length === 0 ? (
        <Empty>No statement entries for this filter.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead><tr><th>Date</th><th>Transaction</th><th>Reference</th><th>Source</th><th>Debit</th><th>Credit</th><th>Balance</th></tr></thead>
            <tbody>
              {data.rows.map((r, i) => (
                <tr key={i}>
                  <td>{new Date(r.date).toLocaleDateString()}</td>
                  <td>{r.transaction}</td>
                  <td>{r.reference}</td>
                  <td><span className={`badge ${sourceBadgeClass(r.source)}`}>{r.source}</span></td>
                  <td>{r.debit ? money(r.debit) : "-"}</td>
                  <td>{r.credit ? money(r.credit) : "-"}</td>
                  <td><strong>{money(r.balance)}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
