import { useSearchParams } from "react-router-dom";

// Lifts all analytics filter state into the URL (via useSearchParams) so every
// section reads from one shared source, filtered views are bookmarkable/
// shareable, and a click anywhere (e.g. a category bar) can update the URL and
// have every dependent section re-fetch automatically.
export function useAnalyticsFilters() {
  const [params, setParams] = useSearchParams();

  function get(key, fallback) {
    return params.get(key) ?? fallback;
  }

  function set(key, value) {
    const next = new URLSearchParams(params);
    if (value === null || value === undefined || value === "") {
      next.delete(key);
    } else {
      next.set(key, value);
    }
    setParams(next, { replace: true });
  }

  const categoryId = get("category", "");
  const plantId = get("plant", "");
  const customerId = get("customer", "");
  const status = get("status", "");

  return {
    range: get("range", "month"),
    dateFrom: get("from", ""),
    dateTo: get("to", ""),
    categoryId: categoryId ? Number(categoryId) : null,
    plantId: plantId ? Number(plantId) : null,
    customerId: customerId ? Number(customerId) : null,
    status: status || null,
    // "" = All (online + offline), "online", "offline" -- shared across
    // every analytics section the same way range/category/plant already are.
    source: get("source", ""),
    setRange: (v) => set("range", v),
    setDateFrom: (v) => set("from", v),
    setDateTo: (v) => set("to", v),
    setCategoryId: (v) => set("category", v),
    setPlantId: (v) => set("plant", v),
    setCustomerId: (v) => set("customer", v),
    setStatus: (v) => set("status", v),
    setSource: (v) => set("source", v),
    clearDrilldown: () => {
      const next = new URLSearchParams(params);
      next.delete("category");
      next.delete("plant");
      next.delete("customer");
      next.delete("status");
      setParams(next, { replace: true });
    },
  };
}

// Builds the range/date_from/date_to query-string fragment shared by nearly
// every analytics endpoint.
export function rangeQuery({ range, dateFrom, dateTo, source }) {
  const params = new URLSearchParams({ range });
  if (range === "custom") {
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
  }
  if (source) params.set("source", source);
  return params.toString();
}
