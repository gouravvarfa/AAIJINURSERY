import { DELIVERY_FILTERS, deliveryAlert, formatDeliveryDate } from "./deliveryAlert";

export function DeliveryFilter({ value, onChange }) {
  return (
    <select
      className="form-control admin-control-sm"
      style={{ maxWidth: 190 }}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label="Filter by delivery date"
    >
      {DELIVERY_FILTERS.map((f) => (
        <option key={f.value} value={f.value}>
          {f.label}
        </option>
      ))}
    </select>
  );
}

// "15 Oct 2026" + a small coloured dot (red / orange / green) with a short
// text label, so the state never depends on colour alone.
export default function DeliveryDateCell({ info, deliveryDate }) {
  const text = formatDeliveryDate(deliveryDate);
  if (!text) return <span className="dl-none">Not set</span>;
  return (
    <span className="dl-cell">
      <span>{text}</span>
      {info && (
        <span className={`dl-pill dl-${info.level}`} title={info.label}>
          <span className="dl-dot" aria-hidden="true" />
          <span className="dl-label">{info.label}</span>
        </span>
      )}
    </span>
  );
}
