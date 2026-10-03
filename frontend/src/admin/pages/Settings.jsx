import { useEffect, useState } from "react";
import { api } from "../../api";
import { Loading } from "../../components/Loading";

const FIELDS = [
  { key: "business_name", label: "Business Name" },
  { key: "tagline", label: "Tagline" },
  { key: "intro", label: "Homepage Introduction", type: "textarea" },
  { key: "about_text", label: "About Us Text", type: "textarea" },
  { key: "years_experience", label: "Years of Experience" },
  { key: "team_details", label: "Team Details", type: "textarea" },
  { key: "phone", label: "Phone Number" },
  { key: "whatsapp", label: "WhatsApp Number", help: "Digits only with country code, e.g. 919876543210" },
  { key: "email", label: "Email Address" },
  { key: "address", label: "Business Address", type: "textarea" },
  { key: "map_embed_url", label: "Google Maps Embed URL" },
  { key: "facebook_url", label: "Facebook Page URL" },
  { key: "instagram_url", label: "Instagram Profile URL" },
  { key: "google_review_url", label: "Google Review URL", help: "Your Google Business Profile review link -- shown to customers after delivery" },
  { key: "working_hours", label: "Working Hours" },
  { key: "delivery_days", label: "Delivery Timeline" },
  { key: "payment_methods", label: "Payment Methods Accepted" },
  { key: "refund_policy", label: "Refund Policy", type: "textarea" },
];

export default function Settings() {
  const [values, setValues] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.get("/admin/settings").then(setValues);
  }, []);

  function update(key, value) {
    setValues((v) => ({ ...v, [key]: value }));
    setSaved(false);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    await api.put("/admin/settings", { values });
    setSaving(false);
    setSaved(true);
  }

  if (!values) return <Loading />;

  return (
    <div>
      <div className="admin-page-head">
        <h1>Site Settings</h1>
      </div>
      <div className="admin-form-card">
        {saved && <div className="alert alert-success">Settings saved.</div>}
        <form onSubmit={handleSubmit}>
          {FIELDS.map((field) => (
            <div className="form-group" key={field.key}>
              <label htmlFor={field.key}>{field.label}</label>
              {field.type === "textarea" ? (
                <textarea
                  id={field.key}
                  className="form-control"
                  value={values[field.key] || ""}
                  onChange={(e) => update(field.key, e.target.value)}
                />
              ) : (
                <input
                  id={field.key}
                  className="form-control"
                  value={values[field.key] || ""}
                  onChange={(e) => update(field.key, e.target.value)}
                />
              )}
              {field.help && <small style={{ color: "var(--color-text-muted)" }}>{field.help}</small>}
            </div>
          ))}
          <button className="btn btn-primary" disabled={saving}>
            {saving ? "Saving..." : "Save Settings"}
          </button>
        </form>
      </div>
    </div>
  );
}
