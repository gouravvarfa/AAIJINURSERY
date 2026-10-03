import { useEffect, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";
import { rangeQuery } from "./useAnalyticsFilters";
import ChartTooltip from "./ChartTooltip";

const COLORS = [
  "var(--color-primary)",
  "var(--color-accent)",
  "var(--color-gold)",
  "var(--color-accent-light)",
  "var(--color-primary-light)",
  "var(--color-text-muted)",
];

export default function CategoryBreakdown({ filters, onSelectCategory }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    setData(null);
    api.get(`/admin/analytics/categories?${rangeQuery(filters)}`).then(setData);
  }, [filters.range, filters.dateFrom, filters.dateTo, filters.source]);

  return (
    <section id="categories" className="analytics-section">
      <div className="admin-page-head">
        <h2>Category Sales Breakdown</h2>
      </div>

      {!data ? (
        <Loading />
      ) : !data.has_data ? (
        <Empty>No Data Available for this period.</Empty>
      ) : (
        <div className="analytics-split-layout">
          <div className="analytics-chart-scroll">
            <ResponsiveContainer width="100%" height={280} minWidth={280}>
              <PieChart>
                <Pie
                  data={data.categories}
                  dataKey="revenue"
                  nameKey="category_name"
                  innerRadius={60}
                  outerRadius={100}
                  onClick={(entry) => onSelectCategory?.(entry.category_id)}
                  style={{ cursor: "pointer" }}
                >
                  {data.categories.map((c, i) => (
                    <Cell key={c.category_id} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  content={
                    <ChartTooltip formatter={(entry) => `${entry.name || entry.payload.category_name}: ₹${entry.value}`} />
                  }
                />
              </PieChart>
            </ResponsiveContainer>
          </div>

          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Plants Sold</th>
                  <th>Revenue</th>
                  <th>Orders</th>
                  <th>% of Sales</th>
                </tr>
              </thead>
              <tbody>
                {data.categories.map((c, i) => (
                  <tr
                    key={c.category_id}
                    onClick={() => onSelectCategory?.(c.category_id)}
                    style={{ cursor: "pointer" }}
                  >
                    <td>
                      <span
                        className="analytics-color-dot"
                        style={{ background: COLORS[i % COLORS.length] }}
                      />
                      {c.category_name}
                    </td>
                    <td>{c.plants_sold}</td>
                    <td>₹{c.revenue.toLocaleString()}</td>
                    <td>{c.orders}</td>
                    <td>{c.pct_of_sales}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
