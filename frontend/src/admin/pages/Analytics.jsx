import { useEffect, useState } from "react";
import { api } from "../../api";
import { Loading } from "../../components/Loading";
import { useAnalyticsFilters, rangeQuery } from "../analytics/useAnalyticsFilters";
import DateRangePicker from "../analytics/DateRangePicker";
import KpiCard from "../analytics/KpiCard";
import SalesChart from "../analytics/SalesChart";
import SalesBySource from "../analytics/SalesBySource";
import CategoryBreakdown from "../analytics/CategoryBreakdown";
import TopPlants from "../analytics/TopPlants";
import PlantsPerformanceTable from "../analytics/PlantsPerformanceTable";
import YearlyMonthlyPanel from "../analytics/YearlyMonthlyPanel";
import CustomerAnalytics from "../analytics/CustomerAnalytics";
import PurchaseAnalytics from "../analytics/PurchaseAnalytics";
import InventoryAnalytics from "../analytics/InventoryAnalytics";
import ProfitAnalytics from "../analytics/ProfitAnalytics";
import OrderStatusChart from "../analytics/OrderStatusChart";
import SalesTrends from "../analytics/SalesTrends";
import { printWholePage } from "../analytics/exportUtils";

const JUMP_NAV = [
  { id: "sales", label: "Sales" },
  { id: "sales-by-source", label: "Sales by Source" },
  { id: "categories", label: "Categories" },
  { id: "top-plants", label: "Top Plants" },
  { id: "plants", label: "All Plants" },
  { id: "yearly", label: "Yearly" },
  { id: "customers", label: "Customers" },
  { id: "purchases", label: "Purchases" },
  { id: "inventory", label: "Inventory" },
  { id: "profit", label: "Profit" },
  { id: "order-status", label: "Order Status" },
  { id: "trends", label: "Trends" },
];

export default function Analytics() {
  const filters = useAnalyticsFilters();
  const [summary, setSummary] = useState(null);
  const [visits, setVisits] = useState(null);

  useEffect(() => {
    setSummary(null);
    api.get(`/admin/analytics/summary?${rangeQuery(filters)}`).then(setSummary);
  }, [filters.range, filters.dateFrom, filters.dateTo]);

  useEffect(() => {
    api.get("/admin/analytics/visits").then(setVisits);
  }, []);

  return (
    <div>
      <div className="admin-page-head">
        <div>
          <h1>Data Analytics</h1>
          <p style={{ color: "var(--color-text-muted)", margin: "4px 0 0", fontSize: "0.9rem" }}>
            Complete overview of your nursery business performance
          </p>
        </div>
        <div className="analytics-header-actions">
          <DateRangePicker
            range={filters.range}
            dateFrom={filters.dateFrom}
            dateTo={filters.dateTo}
            onRangeChange={filters.setRange}
            onFromChange={filters.setDateFrom}
            onToChange={filters.setDateTo}
          />
          <button type="button" className="btn btn-sm btn-primary" onClick={printWholePage}>
            ⬇ Export Report
          </button>
        </div>
      </div>

      <nav className="analytics-jump-nav">
        {JUMP_NAV.map((item) => (
          <a key={item.id} href={`#${item.id}`}>
            {item.label}
          </a>
        ))}
      </nav>

      {(filters.categoryId || filters.plantId || filters.customerId || filters.status) && (
        <div className="analytics-drilldown-banner">
          Filtered view active.
          <button type="button" className="btn btn-sm btn-outline dark" onClick={filters.clearDrilldown}>
            Clear filter
          </button>
        </div>
      )}

      {!summary ? (
        <Loading />
      ) : (
        <div className="stat-cards" style={{ marginBottom: 28 }}>
          <KpiCard label="Total Revenue" value={`₹${summary.total_sales.toLocaleString()}`} changePct={summary.sales_change_pct} sublabel={summary.range_label} />
          <KpiCard
            label="Total Orders"
            value={summary.total_orders}
            sublabel={`${summary.orders_completed} completed · ${summary.orders_pending} pending · ${summary.orders_cancelled} cancelled`}
          />
          <KpiCard
            label="Total Customers"
            value={summary.total_customers}
            sublabel={`${summary.new_customers_this_period} new · ${summary.returning_customers} returning`}
          />
          <KpiCard label="Plants Sold" value={summary.plants_sold} sublabel={`${summary.varieties_sold} varieties`} />
          <KpiCard
            label="Inventory"
            value={summary.inventory_total}
            sublabel={`${summary.inventory_low_stock} low · ${summary.inventory_out_of_stock} out of stock`}
          />
          <KpiCard label="Purchase Cost" value={`₹${summary.total_purchase_cost.toLocaleString()}`} />
          <KpiCard
            label="Gross Profit"
            value={summary.gross_profit != null ? `₹${summary.gross_profit.toLocaleString()}` : "N/A"}
            sublabel={summary.profit_margin_pct != null ? `${summary.profit_margin_pct}% margin` : "Log a purchase to see profit"}
          />
          {visits && (
            <KpiCard
              label="Website Visitors"
              value={visits.total_visits.toLocaleString()}
              sublabel={`${visits.visits_today} today · ${visits.visits_this_week} this week · ${visits.visits_this_month} this month`}
            />
          )}
        </div>
      )}

      <SalesChart filters={filters} />
      <SalesBySource filters={filters} />
      <CategoryBreakdown filters={filters} onSelectCategory={filters.setCategoryId} />
      <TopPlants filters={filters} onSelectPlant={filters.setPlantId} />
      <PlantsPerformanceTable filters={filters} />
      <YearlyMonthlyPanel />
      <CustomerAnalytics filters={filters} />
      <PurchaseAnalytics filters={filters} />
      <InventoryAnalytics />
      <ProfitAnalytics filters={filters} />
      <OrderStatusChart filters={filters} />
      <SalesTrends />
    </div>
  );
}
