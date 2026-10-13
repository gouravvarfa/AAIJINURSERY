import { useEffect, useState } from "react";
import { formatIst } from "../communications/time";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";

export default function CustomerLogs() {
  const [items, setItems] = useState(null);

  useEffect(() => {
    api.get("/admin/customer-logs").then(setItems);
  }, []);

  return (
    <div>
      <div className="admin-page-head">
        <h1>Customer Logs</h1>
      </div>

      {!items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>No customer activity recorded yet.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Customer</th>
                <th>Email</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{formatIst(item.created_at)}</td>
                  <td>{item.customer_name}</td>
                  <td>{item.customer_email}</td>
                  <td>
                    <span className="badge badge-muted">{item.action.replace(/_/g, " ")}</span>
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
