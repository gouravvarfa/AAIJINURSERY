import { useEffect, useState } from "react";
import { formatIstDate } from "../communications/time";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";

export default function Customers() {
  const [items, setItems] = useState(null);

  useEffect(() => {
    api.get("/admin/customers").then(setItems);
  }, []);

  return (
    <div>
      <div className="admin-page-head">
        <h1>Customers</h1>
      </div>

      {!items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>No registered customers yet.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Email</th>
                <th>Phone</th>
                <th>Registered</th>
                <th>Orders</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td>#{c.id}</td>
                  <td>{c.name}</td>
                  <td>{c.email}</td>
                  <td>{c.mobile || "-"}</td>
                  <td>{c.created_at ? formatIstDate(c.created_at) : "-"}</td>
                  <td>
                    <span className="badge badge-muted">{c.order_count}</span>
                  </td>
                  <td>
                    <Link className="btn btn-sm btn-outline dark" to={`/admin/customers/${c.id}`}>
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
