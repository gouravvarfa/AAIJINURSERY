import { useEffect, useState } from "react";
import { formatIst } from "../communications/time";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";

export default function ActivityLog() {
  const [items, setItems] = useState(null);

  useEffect(() => {
    api.get("/admin/activity-log").then(setItems);
  }, []);

  return (
    <div>
      <div className="admin-page-head">
        <h1>Activity Log</h1>
      </div>

      {!items ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>No activity recorded yet.</Empty>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Admin</th>
                <th>Action</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{formatIst(item.created_at)}</td>
                  <td>{item.admin_username}</td>
                  <td>
                    <span className="badge badge-muted">{item.action.replace(/_/g, " ")}</span>
                  </td>
                  <td>{item.detail || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
