// Shared Online/Offline/All dropdown used on every Accounting list page so
// the source filter looks and behaves identically everywhere.
export default function SourceFilter({ value, onChange }) {
  return (
    <select
      className="form-control admin-control-sm"
      style={{ maxWidth: 160 }}
      value={value || ""}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">All Sources</option>
      <option value="online">Online</option>
      <option value="offline">Offline</option>
    </select>
  );
}
