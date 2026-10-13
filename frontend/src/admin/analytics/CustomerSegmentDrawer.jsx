import { useEffect, useState } from "react";
import { formatIstDate } from "../communications/time";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";

const SEGMENT_LABELS = {
  vip: "VIP Customers",
  regular: "Regular Customers",
  new: "New Customers",
  one_time: "One-Time Customers",
  inactive: "Inactive Customers",
};

export default function CustomerSegmentDrawer({ segment, onClose }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!segment) return;
    setData(null);
    api.get(`/admin/analytics/customers/segment/${segment}?page=1&limit=50`).then(setData);
  }, [segment]);

  if (!segment) return null;

  return (
    <div className="analytics-drawer-backdrop" onClick={onClose}>
      <div className="analytics-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="admin-page-head">
          <h2>{SEGMENT_LABELS[segment] || segment}</h2>
          <button type="button" className="btn btn-sm btn-outline dark" onClick={onClose}>
            Close
          </button>
        </div>
        {!data ? (
          <Loading />
        ) : data.items.length === 0 ? (
          <Empty>No customers in this segment.</Empty>
        ) : (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Contact</th>
                  <th>Spent</th>
                  <th>Orders</th>
                  <th>Last Order</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Link to={`/admin/customers/${c.id}`}>{c.name}</Link>
                    </td>
                    <td>
                      {c.email}
                      <br />
                      {c.mobile}
                    </td>
                    <td>₹{c.total_spent.toLocaleString()}</td>
                    <td>{c.order_count}</td>
                    <td>{c.last_order_at ? formatIstDate(c.last_order_at) : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
