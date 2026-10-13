import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";

const STEPS = ["Ready", "Out for Delivery", "Arrived"];
const DONE = ["Delivered", "Partially Delivered", "Failed", "Cancelled"];

// Offline sales order: set the driver / vehicle and move the delivery along
// from the sales order itself, using the same delivery endpoints (and so the
// same customer WhatsApp updates) as the Delivery module.
export default function DeliveryPanel({ salesOrder }) {
  const [delivery, setDelivery] = useState(undefined); // undefined = loading, null = none yet
  const [drivers, setDrivers] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [driverId, setDriverId] = useState("");
  const [vehicleId, setVehicleId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [denied, setDenied] = useState(false);

  function load() {
    api
      .get(`/admin/delivery/deliveries?sales_order_id=${salesOrder.id}`)
      .then((rows) => {
        const open = rows.find((d) => !DONE.includes(d.status));
        const current = open || rows[0] || null;
        setDelivery(current);
        setDriverId(current?.driver_id ? String(current.driver_id) : "");
        setVehicleId(current?.vehicle_id ? String(current.vehicle_id) : "");
      })
      .catch(() => setDenied(true)); // no Delivery access: hide the panel
  }

  useEffect(() => {
    load();
    api.get("/admin/delivery/drivers").then(setDrivers).catch(() => {});
    api.get("/admin/delivery/vehicles").then(setVehicles).catch(() => {});
  }, [salesOrder.id]);

  function pickDriver(value) {
    setDriverId(value);
    const d = drivers.find((x) => String(x.id) === value);
    if (d?.assigned_vehicle_id) setVehicleId(String(d.assigned_vehicle_id));
    if (!value) setVehicleId("");
  }

  async function run(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
      load();
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const create = () =>
    run(() =>
      api.post("/admin/delivery/deliveries", {
        delivery_date: salesOrder.delivery_date || new Date().toISOString(),
        contact_id: salesOrder.contact_id,
        sales_order_id: salesOrder.id,
        driver_id: driverId ? Number(driverId) : null,
        vehicle_id: vehicleId ? Number(vehicleId) : null,
      })
    );
  const saveDriver = () =>
    run(() =>
      api.put(`/admin/delivery/deliveries/${delivery.id}/assign`, {
        driver_id: driverId ? Number(driverId) : null,
        vehicle_id: vehicleId ? Number(vehicleId) : null,
      })
    );
  const setStatus = (status) => run(() => api.put(`/admin/delivery/deliveries/${delivery.id}/status`, { status }));
  const complete = () => {
    if (!window.confirm("Mark this delivery as fully delivered?")) return;
    run(() =>
      api.post(`/admin/delivery/deliveries/${delivery.id}/complete`, {
        items: delivery.items.map((i) => ({ item_id: i.id, delivered_quantity: i.ordered_quantity })),
      })
    );
  };

  if (denied || delivery === undefined) return null;
  if (["Cancelled", "Voided"].includes(salesOrder.status)) return null;

  const finished = delivery && DONE.includes(delivery.status);
  const pickers = (
    <>
      <div className="form-group">
        <label htmlFor="so-driver">Driver</label>
        <select id="so-driver" className="form-control" value={driverId} disabled={finished} onChange={(e) => pickDriver(e.target.value)}>
          <option value="">No driver</option>
          {drivers.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
              {d.phone ? ` - ${d.phone}` : ""}
            </option>
          ))}
        </select>
      </div>
      <div className="form-group">
        <label htmlFor="so-vehicle">Vehicle</label>
        <select id="so-vehicle" className="form-control" value={vehicleId} disabled={finished || !driverId} onChange={(e) => setVehicleId(e.target.value)}>
          <option value="">No vehicle</option>
          {vehicles.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name_model ? `${v.name_model} (${v.registration_number})` : v.registration_number}
            </option>
          ))}
        </select>
      </div>
    </>
  );

  return (
    <div className="admin-form-card" style={{ maxWidth: "none", marginBottom: 20 }}>
      <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Delivery</h2>
      {error && <div className="alert alert-error" style={{ marginBottom: 12 }}>{error}</div>}

      {!delivery ? (
        <>
          <p style={{ color: "var(--color-text-muted)", marginTop: 0 }}>No delivery yet. Choose the driver and vehicle and create it.</p>
          {pickers}
          <button type="button" className="btn btn-primary btn-block" disabled={busy} onClick={create}>
            {busy ? "Creating..." : "Create delivery"}
          </button>
        </>
      ) : (
        <>
          <p style={{ margin: "0 0 12px" }}>
            <Link to={`/admin/delivery/deliveries/${delivery.id}`}>{delivery.delivery_number}</Link> &middot; <strong>{delivery.status}</strong>
          </p>
          {pickers}
          {!finished && (
            <>
              <button type="button" className="btn btn-outline dark btn-block" disabled={busy} onClick={saveDriver} style={{ marginBottom: 14 }}>
                Save driver
              </button>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
                {STEPS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={`btn btn-sm ${delivery.status === s ? "btn-primary" : "btn-outline dark"}`}
                    disabled={busy || delivery.status === s}
                    onClick={() => setStatus(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
              <button type="button" className="btn btn-primary btn-block" disabled={busy} onClick={complete}>
                Mark Delivered / Complete
              </button>
            </>
          )}
        </>
      )}
    </div>
  );
}
