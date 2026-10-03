import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import SourceFilter from "../../accounting/SourceFilter";
import SearchBox from "../../accounting/SearchBox";
import ExportButton from "../../accounting/ExportButton";
import { invoiceBadgeClass, sourceBadgeClass } from "../../accounting/accountingStatus";

export default function Invoices() {
  const [items, setItems] = useState(null);
  const [source, setSource] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState("");

  function load() {
    setItems(null);
    setError("");
    const params = new URLSearchParams();
    if (source) params.set("source", source);
    if (status) params.set("status", status);
    if (q) params.set("q", q);
    const query = params.toString() ? `?${params.toString()}` : "";
    api.get(`/admin/accounting/invoices${query}`).then(setItems).catch((err) => setError(err.message || "Could not load invoices."));
  }

  useEffect(load, [source, status, q]);

  return (
    <div>
      <div className="admin-page-head">
        <h1>Invoices</h1>
        <div className="admin-page-head-controls">
          <SourceFilter value={source} onChange={setSource} />
          <select className="form-control admin-control-sm" style={{ maxWidth: 180 }} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All Statuses</option>
            <option value="Sent">Sent</option>
            <option value="PartiallyPaid">Partially Paid</option>
            <option value="Paid">Paid</option>
            <option value="Overdue">Overdue</option>
            <option value="Voided">Voided</option>
          </select>
          <SearchBox value={q} onChange={setQ} placeholder="Search by invoice # or contact name..." />
          <ExportButton baseUrl="/api/admin/accounting/export/invoices.xlsx" />
        </div>
      </div>

      {error ? (
        <div className="alert alert-error">
          {error} <button type="button" className="btn btn-outline dark" onClick={load}>Retry</button>
        </div>
      ) : !items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>No invoices yet.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Invoice #</th>
                <th>Contact</th>
                <th>Date</th>
                <th>Total</th>
                <th>Balance Due</th>
                <th>Status</th>
                <th>Source</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{item.invoice_number}</td>
                  <td>{item.contact?.name || "-"}</td>
                  <td>{new Date(item.invoice_date).toLocaleDateString()}</td>
                  <td>₹{item.total_amount.toLocaleString()}</td>
                  <td>₹{item.balance_due.toLocaleString()}</td>
                  <td>
                    <span className={`badge ${invoiceBadgeClass(item.status)}`}>{item.status}</span>
                  </td>
                  <td>
                    <span className={`badge ${sourceBadgeClass(item.source)}`}>
                      {item.source === "online" ? "Online" : "Offline"}
                    </span>
                  </td>
                  <td>
                    <Link className="btn btn-sm btn-outline dark" to={`/admin/accounting/invoices/${item.id}`}>
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
