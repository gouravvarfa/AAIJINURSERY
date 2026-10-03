import { useEffect, useState } from "react";
import { api } from "../../api";
import { Loading, Empty } from "../../components/Loading";
import { rangeQuery } from "./useAnalyticsFilters";
import ExportMenu from "./ExportMenu";

const SEARCH_DEBOUNCE_MS = 400;
const PAGE_SIZE = 20;

const STATUS_BADGE = {
  "Best Seller": "badge-accent",
  Growing: "badge-accent",
  Average: "badge-muted",
  "Low Sales": "badge-gold",
  "No Sales": "badge-muted",
};

const SORT_OPTIONS = [
  { value: "revenue", label: "Revenue" },
  { value: "sold", label: "Units Sold" },
  { value: "profit", label: "Profit" },
  { value: "stock", label: "Stock" },
  { value: "last_sold", label: "Last Sold" },
  { value: "name", label: "Name" },
];

export default function PlantsPerformanceTable({ filters }) {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [categoryId, setCategoryId] = useState(filters.categoryId ?? "");
  const [stockStatus, setStockStatus] = useState("");
  const [sortBy, setSortBy] = useState("revenue");
  const [sortDir, setSortDir] = useState("desc");
  const [page, setPage] = useState(1);
  const [categories, setCategories] = useState([]);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/admin/categories").then(setCategories);
  }, []);

  useEffect(() => {
    if (filters.categoryId) setCategoryId(filters.categoryId);
  }, [filters.categoryId]);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, categoryId, stockStatus, sortBy, sortDir]);

  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams(rangeQuery(filters));
    if (debouncedSearch) params.set("search", debouncedSearch);
    if (categoryId) params.set("category_id", categoryId);
    if (stockStatus) params.set("stock_status", stockStatus);
    params.set("sort_by", sortBy);
    params.set("sort_dir", sortDir);
    params.set("page", page);
    params.set("limit", PAGE_SIZE);

    let cancelled = false;
    api
      .get(`/admin/analytics/plants?${params.toString()}`)
      .then((data) => {
        if (!cancelled) setResult(data);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filters.range, filters.dateFrom, filters.dateTo, filters.source, debouncedSearch, categoryId, stockStatus, sortBy, sortDir, page]);

  return (
    <section id="plants" className="analytics-section">
      <div className="admin-page-head">
        <h2>All Plants Performance</h2>
        <ExportMenu
          filename="plants-performance"
          rows={result?.items?.map((p) => ({
            name: p.name,
            category: p.category_name,
            price: p.effective_price,
            purchase_cost: p.avg_purchase_cost ?? "",
            sold: p.total_sold,
            revenue: p.total_revenue,
            stock: p.stock_quantity,
            profit: p.profit ?? "",
            profit_pct: p.profit_pct ?? "",
            orders: p.order_count,
            status: p.performance_status,
          }))}
          sectionId="plants"
        />
      </div>

      <div className="admin-form-card" style={{ marginBottom: 20 }}>
        <div className="form-row">
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Search</label>
            <input
              className="form-control"
              placeholder="Search plant..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Category</label>
            <select className="form-control" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
              <option value="">All Categories</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Stock</label>
            <select className="form-control" value={stockStatus} onChange={(e) => setStockStatus(e.target.value)}>
              <option value="">All Status</option>
              <option value="in_stock">In Stock</option>
              <option value="low">Low Stock</option>
              <option value="out">Out of Stock</option>
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Sort By</label>
            <select className="form-control" value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Order</label>
            <select className="form-control" value={sortDir} onChange={(e) => setSortDir(e.target.value)}>
              <option value="desc">High to Low</option>
              <option value="asc">Low to High</option>
            </select>
          </div>
        </div>
      </div>

      {loading ? (
        <Loading />
      ) : !result || !result.has_data ? (
        <Empty>No Data Available.</Empty>
      ) : (
        <>
          <p style={{ color: "var(--color-text-muted)", fontSize: "0.9rem" }}>{result.total} plant(s) found</p>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Plant</th>
                  <th>Category</th>
                  <th>Price</th>
                  <th>Purchase Cost</th>
                  <th>Sold</th>
                  <th>Revenue</th>
                  <th>Stock</th>
                  <th>Profit</th>
                  <th>Profit %</th>
                  <th>Orders</th>
                  <th>Last Sold</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <img
                          src={p.image_url}
                          alt=""
                          style={{ width: 32, height: 32, borderRadius: 6, objectFit: "cover" }}
                        />
                        {p.name}
                      </div>
                    </td>
                    <td>{p.category_name}</td>
                    <td>₹{p.effective_price}</td>
                    <td>{p.avg_purchase_cost != null ? `₹${p.avg_purchase_cost}` : "N/A"}</td>
                    <td>{p.total_sold}</td>
                    <td>₹{p.total_revenue.toLocaleString()}</td>
                    <td>{p.stock_quantity}</td>
                    <td>{p.profit != null ? `₹${p.profit.toLocaleString()}` : "N/A"}</td>
                    <td>{p.profit_pct != null ? `${p.profit_pct}%` : "N/A"}</td>
                    <td>{p.order_count}</td>
                    <td>{p.last_sold_at ? new Date(p.last_sold_at).toLocaleDateString() : "-"}</td>
                    <td>
                      <span className={`badge ${STATUS_BADGE[p.performance_status] || "badge-muted"}`}>
                        {p.performance_status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {result.pages > 1 && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 18,
                marginTop: 24,
                fontSize: "0.9rem",
                color: "var(--color-text-muted)",
              }}
            >
              <button
                type="button"
                className="btn btn-outline dark btn-sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Prev
              </button>
              <span>
                Page {result.page} of {result.pages}
              </span>
              <button
                type="button"
                className="btn btn-outline dark btn-sm"
                disabled={page >= result.pages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
