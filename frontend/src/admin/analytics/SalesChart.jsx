import { useEffect, useState } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";
import { rangeQuery } from "./useAnalyticsFilters";
import ChartTooltip from "./ChartTooltip";
import ExportMenu from "./ExportMenu";

const GRANULARITIES = [
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "yearly", label: "Yearly" },
];

export default function SalesChart({ filters }) {
  const [granularity, setGranularity] = useState("daily");
  const [data, setData] = useState(null);

  useEffect(() => {
    setData(null);
    const params = new URLSearchParams(rangeQuery(filters));
    params.set("granularity", granularity);
    if (filters.categoryId) params.set("category_id", filters.categoryId);
    if (filters.plantId) params.set("plant_id", filters.plantId);
    api.get(`/admin/analytics/sales?${params.toString()}`).then(setData);
  }, [granularity, filters.range, filters.dateFrom, filters.dateTo, filters.source, filters.categoryId, filters.plantId]);

  return (
    <section id="sales" className="analytics-section">
      <div className="admin-page-head">
        <h2>Sales Overview</h2>
        <div className="analytics-toggle-group">
          {GRANULARITIES.map((g) => (
            <button
              key={g.value}
              type="button"
              className={`btn btn-sm ${granularity === g.value ? "btn-primary" : "btn-outline dark"}`}
              onClick={() => setGranularity(g.value)}
            >
              {g.label}
            </button>
          ))}
          <ExportMenu filename="sales-report" rows={data?.points} sectionId="sales" />
        </div>
      </div>

      {!data ? (
        <Loading />
      ) : !data.has_data ? (
        <Empty>No Data Available for this period.</Empty>
      ) : (
        <div className="analytics-chart-scroll">
          <ResponsiveContainer width="100%" height={320} minWidth={480}>
            <ComposedChart data={data.points}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis dataKey="period" tick={{ fontSize: 12 }} />
              <YAxis yAxisId="left" tick={{ fontSize: 12 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 12 }} />
              <Tooltip
                content={
                  <ChartTooltip
                    formatter={(entry) =>
                      entry.dataKey === "revenue"
                        ? `Revenue: ₹${entry.value}`
                        : entry.dataKey === "orders"
                        ? `Orders: ${entry.value}`
                        : `Plants sold: ${entry.value}`
                    }
                  />
                }
              />
              <Bar yAxisId="left" dataKey="orders" name="Orders" fill="var(--color-accent-light)" radius={[4, 4, 0, 0]} />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="revenue"
                name="Revenue"
                stroke="var(--color-primary)"
                strokeWidth={2}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
