import { useSettings } from "../context/SettingsContext";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

const VALUE_PROPS = [
  {
    icon: "🌿",
    title: "Quality Assured",
    text: "Every plant is inspected for health and vigour before it leaves our nursery.",
  },
  {
    icon: "🚚",
    title: "Careful Delivery",
    text: "Plants are packed to survive the journey, not just look good in a photo.",
  },
  {
    icon: "🌱",
    title: "Expert Guidance",
    text: "Our horticulturists help you pick the right plant for your light, space, and care level.",
  },
  {
    icon: "💚",
    title: "Ongoing Support",
    text: "Questions after you buy? We're a call or WhatsApp message away.",
  },
];

export default function About() {
  const settings = useSettings();
  useDocumentTitle("About Us | Aaiji Nursery");

  return (
    <>
      <section className="page-hero">
        <div className="container">
          <h1>About Us</h1>
          <p>Growing quality plants and lasting trust, one season at a time.</p>
        </div>
      </section>

      <section className="section">
        <div className="container">
          <div className="grid grid-2" style={{ alignItems: "center" }}>
            <div>
              <span className="eyebrow" style={{ color: "var(--color-accent)", fontWeight: 700 }}>
                Our Story
              </span>
              <h2>What We Do</h2>
              <p>{settings.about_text}</p>
              <div className="stat-row" style={{ gridTemplateColumns: "1fr 1fr", marginTop: 28 }}>
                <div>
                  <div className="num">{settings.years_experience}+</div>
                  <div className="label">Years of Experience</div>
                </div>
                <div>
                  <div className="num">5000+</div>
                  <div className="label">Happy Customers</div>
                </div>
              </div>
            </div>
            <img
              className="card"
              style={{ aspectRatio: "4/3", objectFit: "cover" }}
              src="https://images.unsplash.com/photo-1416879595882-3373a0480b5b?w=900"
              alt="Our nursery"
            />
          </div>
        </div>
      </section>

      <section className="section section-alt">
        <div className="container">
          <div className="section-head">
            <span className="eyebrow">Why choose us</span>
            <h2>What Sets Us Apart</h2>
          </div>
          <div className="grid grid-4">
            {VALUE_PROPS.map((item) => (
              <div key={item.title} className="value-prop">
                <span className="value-prop-icon">{item.icon}</span>
                <h3>{item.title}</h3>
                <p>{item.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section">
        <div className="container">
          <div className="section-head">
            <span className="eyebrow">Meet the people</span>
            <h2>Our Team</h2>
          </div>
          <p style={{ textAlign: "center", maxWidth: 700, margin: "0 auto" }}>
            {settings.team_details}
          </p>
        </div>
      </section>
    </>
  );
}
