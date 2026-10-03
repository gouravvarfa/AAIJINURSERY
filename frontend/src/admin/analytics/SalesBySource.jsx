import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";
import { rangeQuery } from "./useAnalyticsFilters";
import ChartTooltip from "./ChartTooltip";
import KpiCard from "./KpiCard";

function money(v) {
  return `₹${(v || 0).toLocaleString()}`;
}

// Sales by Source -- website orders (synced automatically into Accounting as
// source="online" invoices) vs. manually entered offline/in-person sales
// (source="offline" invoices). Reuses the existing accounting reports
// endpoint (GET /api/admin/accounting/reports/sales) rather than duplicating
// its revenue logic; the `source` param there is additive (defaults to the
// same unfiltered behavior the Accounting Reports page already relies on).
// Driven by the SAME global filters.source used by every other section on
// this page (set via the Source toggle in the page header), not its own
// separate control.
export default function SalesBySource({ filters }) {
  const [data, setData] = useState(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    setData(null);
    setUnavailable(false);
    const params = new URLSearchParams(rangeQuery(filters));
    api
      .get(`/admin/accounting/reports/sales?${params.toString()}`)
      .then(setData)
      .catch(() => setUnavailable(true));
  }, [filters.range, filters.dateFrom, filters.dateTo, filters.source]);

  // A custom role without Accounting access simply won't see this section --
  // never a broken/error-looking widget on their Analytics page.
  if (unavailable) return null;

  return (
    <section id="sales-by-source" className="analytics-section">
      <div className="admin-page-head">
        <h2>Sales by Source</h2>
      </div>

      {!data ? (
        <Loading />
      ) : data.invoice_count === 0 ? (
        <Empty>No Data Available for this period.</Empty>
      ) : (
        <>
          <div className="stat-cards" style={{ marginBottom: 20 }}>
            <KpiCard
              label={filters.source === "online" ? "Online Sales" : filters.source === "offline" ? "Offline Sales" : "Total Sales"}
              value={money(data.total_sales)}
              sublabel={`${data.invoice_count} invoice${data.invoice_count === 1 ? "" : "s"} · ${data.range_label}`}
            />
            <KpiCard label="Online Sales" value={money(data.online_sales)} sublabel="Website orders" />
            <KpiCard label="Offline Sales" value={money(data.offline_sales)} sublabel="Manually entered" />
          </div>

          {data.rows.length > 0 && (
            <div className="analytics-chart-scroll">
              <ResponsiveContainer width="100%" height={260} minWidth={480}>
                <LineChart data={data.rows}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="period" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip content={<ChartTooltip formatter={(entry) => `Amount: ₹${entry.value}`} />} />
                  <Line type="monotone" dataKey="amount" name="Amount" stroke="var(--color-primary)" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </section>
  );
}
