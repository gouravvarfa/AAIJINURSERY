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

const MAX_SLIDES = 10;

function HeroSliderEditor({ images, setImages, seconds, setSeconds }) {
  function setAt(i, value) {
    setImages(images.map((src, idx) => (idx === i ? value : src)));
  }
  function move(i, dir) {
    const j = i + dir;
    if (j < 0 || j >= images.length) return;
    const next = [...images];
    [next[i], next[j]] = [next[j], next[i]];
    setImages(next);
  }
  function remove(i) {
    setImages(images.filter((_, idx) => idx !== i));
  }

  return (
    <div className="form-group">
      <label>Home Page Slider Images</label>
      <small style={{ display: "block", color: "var(--color-text-muted)", marginBottom: 10 }}>
        Photos that rotate in the home page banner, in this order. Paste an image link (https://...) for each.
        Wide or square photos of at least 900px look best.
      </small>
      {images.map((src, i) => (
        <div key={i} style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
          <div
            style={{
              width: 88, height: 60, borderRadius: 8, flexShrink: 0, overflow: "hidden",
              background: "var(--color-bg)", border: "1px solid var(--color-border)",
            }}
          >
            {src.trim() && (
              <img src={src.trim()} alt={`Slide ${i + 1}`} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            )}
          </div>
          <input
            className="form-control"
            style={{ flex: "1 1 260px", minWidth: 0 }}
            placeholder="https://..."
            value={src}
            onChange={(e) => setAt(i, e.target.value)}
            aria-label={`Slide ${i + 1} image link`}
          />
          <div className="row-actions">
            <button type="button" className="btn btn-sm btn-outline dark" onClick={() => move(i, -1)} disabled={i === 0} aria-label="Move up">
              ↑
            </button>
            <button type="button" className="btn btn-sm btn-outline dark" onClick={() => move(i, 1)} disabled={i === images.length - 1} aria-label="Move down">
              ↓
            </button>
            <button type="button" className="btn btn-sm btn-danger" onClick={() => remove(i)} disabled={images.length === 1}>
              Remove
            </button>
          </div>
        </div>
      ))}
      <button
        type="button"
        className="btn btn-sm btn-outline dark"
        onClick={() => setImages([...images, ""])}
        disabled={images.length >= MAX_SLIDES}
      >
        + Add Image
      </button>
      <div style={{ marginTop: 14, maxWidth: 220 }}>
        <label htmlFor="hero_slide_seconds">Change photo every (seconds)</label>
        <input
          id="hero_slide_seconds"
          type="number"
          min={2}
          max={30}
          className="form-control"
          value={seconds}
          onChange={(e) => setSeconds(e.target.value)}
        />
      </div>
    </div>
  );
}

export default function Settings() {
  const [values, setValues] = useState(null);
  const [heroImages, setHeroImages] = useState([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/admin/settings").then((v) => {
      setValues(v);
      setHeroImages((v.hero_images || "").split("\n").map((s) => s.trim()).filter(Boolean));
    });
  }, []);

  function update(key, value) {
    setValues((v) => ({ ...v, [key]: value }));
    setSaved(false);
  }

  function updateHeroImages(list) {
    setHeroImages(list);
    setSaved(false);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const payload = { ...values, hero_images: heroImages.map((s) => s.trim()).filter(Boolean).join("\n") };
      const fresh = await api.put("/admin/settings", { values: payload });
      setValues(fresh);
      setHeroImages((fresh.hero_images || "").split("\n").filter(Boolean));
      setSaved(true);
    } catch (err) {
      setError(err.message || "Could not save settings.");
    } finally {
      setSaving(false);
    }
  }

  if (!values) return <Loading />;

  return (
    <div>
      <div className="admin-page-head">
        <h1>Site Settings</h1>
      </div>
      <div className="admin-form-card">
        {saved && <div className="alert alert-success">Settings saved.</div>}
        {error && <div className="alert alert-error">{error}</div>}
        <form onSubmit={handleSubmit}>
          <HeroSliderEditor
            images={heroImages}
            setImages={updateHeroImages}
            seconds={values.hero_slide_seconds || "4"}
            setSeconds={(s) => update("hero_slide_seconds", s)}
          />
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
