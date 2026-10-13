import { useEffect, useState } from "react";
import { api } from "../../api";
import { formatIst } from "./time";

const STATUS_BADGE = {
  SENT: "badge-accent", DELIVERED: "badge-accent", READ: "badge-accent",
  QUEUED: "badge-gold", PROCESSING: "badge-gold",
  FAILED: "badge-danger", CANCELLED: "badge-muted",
};

// What each automatic event means to a person reading an order page.
const EVENT_LABEL = {
  ORDER_CREATED: "Order confirmed message",
  ORDER_ACCEPTED: "Order accepted",
  DELIVERY_FEASIBILITY_CONFIRMED: "Delivery confirmed message",
  DELIVERY_UNAVAILABLE: "Delivery unavailable",
  ORDER_PROCESSING: "Order processing",
  ORDER_PACKED: "Order packed",
  ORDER_DISPATCHED: "Order dispatched",
  OUT_FOR_DELIVERY: "Out for delivery",
  ORDER_DELIVERED: "Order delivered",
  ORDER_CANCELLED: "Order cancelled",
  PAYMENT_RECEIVED: "Payment received",
  INVOICE_CREATED: "Invoice created",
  GOOGLE_REVIEW_REQUEST: "Google review request",
  MANUAL_MESSAGE: "Manual message",
  TEST_MESSAGE: "Test message",
};

function eventLabel(code) {
  if (EVENT_LABEL[code]) return EVENT_LABEL[code];
  const text = code.replaceAll("_", " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const IN_FLIGHT = new Set(["QUEUED", "PROCESSING"]);

// One shared component embedded in Order/Delivery/Invoice/Customer detail
// pages alike -- always reads the SAME centralized message table via
// (source_module, source_id) or customer_id, never a per-module copy.
export default function WhatsAppActivity({ sourceModule, sourceId, customerId, title = "WhatsApp Activity" }) {
  const [items, setItems] = useState(null);

  function load() {
    const params = new URLSearchParams();
    if (sourceModule) params.set("source_module", sourceModule);
    if (sourceId != null) params.set("source_id", String(sourceId));
    if (customerId != null) params.set("customer_id", String(customerId));
    params.set("limit", "50");
    return api.get(`/admin/communications/messages?${params.toString()}`).then((d) => setItems(d.items)).catch(() => setItems((prev) => prev || []));
  }

  useEffect(() => {
    setItems(null);
    load();
  }, [sourceModule, sourceId, customerId]);

  // A message that is still queued/processing finishes within seconds --
  // keep checking so the row doesn't sit on "Processing" until a refresh.
  const hasInFlight = !!items && items.some((m) => IN_FLIGHT.has(m.status));
  useEffect(() => {
    if (!hasInFlight) return undefined;
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [hasInFlight, sourceModule, sourceId, customerId]);

  if (items === null) return null;
  if (items.length === 0) {
    return (
      <div className="admin-form-card" style={{ marginTop: 20, maxWidth: "none" }}>
        <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>{title}</h2>
        <p style={{ color: "var(--color-text-muted)", margin: 0 }}>No WhatsApp messages yet for this record.</p>
      </div>
    );
  }

  return (
    <div className="admin-form-card" style={{ marginTop: 20, maxWidth: "none" }}>
      <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>{title}</h2>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {items.map((m) => (
          <div key={m.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, fontSize: "0.9rem", borderBottom: "1px solid var(--color-border)", paddingBottom: 10 }}>
            <div>
              <strong>{eventLabel(m.event_type)}</strong>
              <div style={{ color: "var(--color-text-muted)", fontSize: "0.82rem" }}>{formatIst(m.created_at)}</div>
              {m.error_message && <div style={{ color: "var(--color-danger)", fontSize: "0.78rem" }}>{m.error_code}: {m.error_message}</div>}
            </div>
            <span className={`badge ${STATUS_BADGE[m.status] || "badge-muted"}`}>{m.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
