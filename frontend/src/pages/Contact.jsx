import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useSettings } from "../context/SettingsContext";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

const MOBILE_PATTERN = /^[6-9]\d{9}$/;

export default function Contact() {
  const settings = useSettings();
  useDocumentTitle("Contact Us | Aaiji Nursery");
  const [searchParams] = useSearchParams();
  const plantId = searchParams.get("plant_id");
  const plantName = searchParams.get("plant_name");
  const [form, setForm] = useState({
    name: "",
    mobile: "",
    requirement: plantName ? `Interested in: ${plantName}` : "",
  });
  const [status, setStatus] = useState("idle"); // idle | saving | done | error
  const [error, setError] = useState("");

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const mobile = form.mobile.trim();
    if (!MOBILE_PATTERN.test(mobile)) {
      setError("Please enter a valid 10-digit mobile number.");
      setStatus("error");
      return;
    }
    setStatus("saving");
    setError("");
    try {
      await api.post("/inquiries", {
        ...form,
        mobile,
        plant_id: plantId ? Number(plantId) : null,
      });
      setStatus("done");
      setForm({ name: "", mobile: "", requirement: "" });
    } catch (err) {
      setError(err.message || "Something went wrong. Please try again.");
      setStatus("error");
    }
  }

  return (
    <>
      <section className="page-hero">
        <div className="container">
          <h1>Contact Us</h1>
          <p>We're here to help. Reach out anytime.</p>
        </div>
      </section>

      <section className="section">
        <div className="container contact-grid">
          <div>
            <h2>Get In Touch</h2>
            <div className="contact-info-item">
              <span className="icon">📞</span>
              <div>
                <strong>Phone</strong>
                <p style={{ margin: 0 }}>{settings.phone}</p>
              </div>
            </div>
            <div className="contact-info-item">
              <span className="icon">✉️</span>
              <div>
                <strong>Email</strong>
                <p style={{ margin: 0 }}>{settings.email}</p>
              </div>
            </div>
            <div className="contact-info-item">
              <span className="icon">📍</span>
              <div>
                <strong>Address</strong>
                <p style={{ margin: 0 }}>{settings.address}</p>
              </div>
            </div>
            <div className="contact-info-item">
              <span className="icon">🕒</span>
              <div>
                <strong>Working Hours</strong>
                <p style={{ margin: 0 }}>{settings.working_hours}</p>
              </div>
            </div>
            {settings.whatsapp && (
              <a
                href={`https://wa.me/${settings.whatsapp}`}
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn-primary"
              >
                Chat on WhatsApp
              </a>
            )}
            {settings.map_embed_url && (
              <iframe
                className="map-embed"
                src={settings.map_embed_url}
                title="Location map"
                loading="lazy"
              />
            )}
          </div>

          <div className="card">
            <div className="card-body">
              <h2 style={{ marginTop: 0 }}>Send an Inquiry</h2>
              {plantName && status !== "done" && (
                <div className="badge badge-accent" style={{ marginBottom: 16 }}>
                  Enquiring about: {plantName}
                </div>
              )}
              {status === "done" ? (
                <div className="alert alert-success">
                  Thanks! We've received your inquiry and will get back to you shortly.
                </div>
              ) : (
                <form onSubmit={handleSubmit}>
                  {status === "error" && <div className="alert alert-error">{error}</div>}
                  <div className="form-group">
                    <label htmlFor="name">Name</label>
                    <input
                      id="name"
                      className="form-control"
                      required
                      value={form.name}
                      onChange={(e) => update("name", e.target.value)}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="mobile">Mobile Number</label>
                    <input
                      id="mobile"
                      className="form-control"
                      type="tel"
                      inputMode="numeric"
                      maxLength={10}
                      placeholder="10-digit mobile number"
                      required
                      value={form.mobile}
                      onChange={(e) => update("mobile", e.target.value.replace(/\D/g, ""))}
                    />
                  </div>
                  <div className="form-group">
                    <label htmlFor="requirement">Requirement</label>
                    <textarea
                      id="requirement"
                      className="form-control"
                      placeholder="Tell us what you're looking for..."
                      value={form.requirement}
                      onChange={(e) => update("requirement", e.target.value)}
                    />
                  </div>
                  <button className="btn btn-primary btn-block" disabled={status === "saving"}>
                    {status === "saving" ? "Submitting..." : "Submit Inquiry"}
                  </button>
                </form>
              )}
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
