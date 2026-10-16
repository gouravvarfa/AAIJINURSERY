import { useEffect, useState } from "react";
import { api } from "../../../api";
import { Loading } from "../../../components/Loading";

const MULTILINE = new Set(["invoice_terms", "invoice_extra_phones", "invoice_payment_note"]);

// Shrinks the picked picture so the signature stays small, and keeps it as a PNG data URL.
function readSignature(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read the picture."));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("This file is not a picture."));
      img.onload = () => {
        const scale = Math.min(1, 560 / img.width);
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(img.width * scale));
        canvas.height = Math.max(1, Math.round(img.height * scale));
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/png"));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

// What is printed on the invoice PDF besides the business details from Site Settings.
// Everything here is optional: a field left empty simply does not appear on the invoice.
export default function InvoiceSettings() {
  const [data, setData] = useState(null);
  const [values, setValues] = useState({});
  const [signature, setSignature] = useState("");
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/admin/accounting/invoice-settings").then((d) => {
      setData(d);
      setValues(Object.fromEntries(d.fields.map((f) => [f.key, f.value])));
      setSignature(d.signature || "");
    }).catch((e) => setError(e.message || "Could not load the invoice settings."));
  }, []);

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const d = await api.put("/admin/accounting/invoice-settings", { values: { ...values, invoice_signature: signature } });
      setData(d);
      setMsg("Saved. New invoice PDFs will use these details.");
    } catch (err) {
      setError(err.message || "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  async function pick(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setSignature(await readSignature(file));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  if (!data) return error ? <div className="alert alert-error">{error}</div> : <Loading />;
  return (
    <div>
      <div className="admin-page-head"><h1>Invoice Settings</h1></div>
      <p className="stock-hint" style={{ marginTop: 0 }}>
        These details are printed on the invoice PDF. The business name, phone, email and address come from Site Settings. A field left empty is simply not printed. These details are private and are never shown on the public website.
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      {msg && <div className="alert alert-success" role="status">{msg}</div>}
      <form className="admin-form-card" onSubmit={save} style={{ maxWidth: 760 }}>
        {data.fields.map((f) => (
          <div className="form-group" key={f.key}>
            <label htmlFor={f.key}>{f.label}</label>
            {MULTILINE.has(f.key) ? (
              <textarea id={f.key} className="form-control" rows={f.key === "invoice_payment_note" ? 2 : 4} value={values[f.key] || ""} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
            ) : (
              <input id={f.key} className="form-control" value={values[f.key] || ""} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
            )}
            {f.hint && <small className="stock-hint">{f.hint}</small>}
          </div>
        ))}
        <div className="form-group">
          <label htmlFor="sig">Authorized signature (picture)</label>
          <input id="sig" type="file" accept="image/png,image/jpeg" onChange={pick} />
          {signature ? (
            <div style={{ marginTop: 8 }}>
              <img src={signature} alt="Signature preview" style={{ maxWidth: 220, maxHeight: 80, background: "#fff", border: "1px solid var(--color-border)", borderRadius: 8, padding: 6 }} />
              <div><button type="button" className="btn btn-sm btn-outline dark" onClick={() => setSignature("")}>Remove signature</button></div>
            </div>
          ) : <small className="stock-hint">No signature picture. The invoice will leave a blank space to sign.</small>}
        </div>
        <button className="btn btn-primary" disabled={busy}>{busy ? "Saving..." : "Save"}</button>
      </form>
    </div>
  );
}
