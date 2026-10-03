import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../api";
import { Loading, Empty } from "../../../components/Loading";
import SearchBox from "../../accounting/SearchBox";
import ExportButton from "../../accounting/ExportButton";
import { billBadgeClass } from "../../accounting/accountingStatus";

export default function Bills() {
  const [items, setItems] = useState(null);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState("");

  function load() {
    setItems(null);
    setError("");
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (q) params.set("q", q);
    const query = params.toString() ? `?${params.toString()}` : "";
    api.get(`/admin/accounting/bills${query}`).then(setItems).catch((err) => setError(err.message || "Could not load bills."));
  }

  useEffect(load, [status, q]);

  return (
    <div>
      <div className="admin-page-head">
        <h1>Bills</h1>
        <div className="admin-page-head-controls">
          <select className="form-control admin-control-sm" style={{ maxWidth: 200 }} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All Statuses</option>
            <option value="Unpaid">Unpaid</option>
            <option value="PartiallyPaid">Partially Paid</option>
            <option value="Paid">Paid</option>
            <option value="Voided">Voided</option>
          </select>
          <SearchBox value={q} onChange={setQ} placeholder="Search by bill # or supplier..." />
          <ExportButton baseUrl="/api/admin/accounting/export/bills.xlsx" />
        </div>
      </div>

      {error ? (
        <div className="alert alert-error">
          {error} <button type="button" className="btn btn-outline dark" onClick={load}>Retry</button>
        </div>
      ) : !items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>No bills yet. Convert a Purchase Order, or log one directly from the Purchases page.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Bill #</th>
                <th>Supplier</th>
                <th>Date</th>
                <th>Total</th>
                <th>Balance Due</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{item.invoice_number || `#${item.id}`}</td>
                  <td>{item.contact?.name || item.supplier || "-"}</td>
                  <td>{new Date(item.purchase_date).toLocaleDateString()}</td>
                  <td>₹{item.total_cost.toLocaleString()}</td>
                  <td>₹{item.balance_due.toLocaleString()}</td>
                  <td>
                    <span className={`badge ${billBadgeClass(item.status)}`}>{item.status}</span>
                  </td>
                  <td>
                    <Link className="btn btn-sm btn-outline dark" to={`/admin/accounting/bills/${item.id}`}>
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
