import { useState } from "react";

// Export link with an optional From/To date range appended as query params
// -- leaving both blank exports everything, same as before this existed.
export default function ExportButton({ baseUrl, label = "Export" }) {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const params = new URLSearchParams();
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  const href = params.toString() ? `${baseUrl}?${params.toString()}` : baseUrl;

  return (
    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
      <input
        type="date"
        className="form-control admin-control-sm"
        style={{ maxWidth: 150 }}
        value={dateFrom}
        onChange={(e) => setDateFrom(e.target.value)}
        title="From date (optional)"
      />
      <input
        type="date"
        className="form-control admin-control-sm"
        style={{ maxWidth: 150 }}
        value={dateTo}
        onChange={(e) => setDateTo(e.target.value)}
        title="To date (optional)"
      />
      <a className="btn btn-sm btn-outline dark" href={href} target="_blank" rel="noreferrer">
        {label}
      </a>
    </div>
  );
}
