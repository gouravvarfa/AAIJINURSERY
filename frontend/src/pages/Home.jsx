import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useSettings } from "../context/SettingsContext";
import PlantCard from "../components/PlantCard";
import PlantCarousel from "../components/PlantCarousel";
import PlantExplorer from "../components/PlantExplorer";
import HeroImageSlider, { parseHeroImages } from "../components/HeroImageSlider";
import Stars from "../components/Stars";
import Avatar from "../components/Avatar";
import { Loading } from "../components/Loading";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

const CAROUSEL_ITEM_LIMIT = 8;

export default function Home() {
  const settings = useSettings();
  const [categories, setCategories] = useState(null);
  const [featured, setFeatured] = useState(null);
  const [testimonials, setTestimonials] = useState(null);
  // Small per-category plant lists for the mobile-only carousels below —
  // keyed by category slug, filled in as each request resolves. Desktop
  // never reads this (it keeps the existing "Shop by Category" tiles +
  // "Featured Plants" grid instead), so there's no cost to fetching it
  // lazily like this.
  const [categoryPlants, setCategoryPlants] = useState({});

  useDocumentTitle(
    `${settings.business_name || "Aaiji Nursery"} - ${settings.tagline || "Plant Nursery & Landscaping"}`
  );

  useEffect(() => {
    api.get("/categories").then(setCategories);
    api.get("/plants?featured=true").then(setFeatured);
    api.get("/testimonials").then((data) => setTestimonials(data.slice(0, 3)));
  }, []);

  useEffect(() => {
    if (!categories) return;
    categories.forEach((cat) => {
      api.get(`/plants?category=${cat.slug}&limit=${CAROUSEL_ITEM_LIMIT}`).then((data) => {
        setCategoryPlants((prev) => ({ ...prev, [cat.slug]: data }));
      });
    });
  }, [categories]);

  return (
    <>
      <section className="hero">
        <div className="container">
          <div>
            <span className="tagline">{settings.tagline}</span>
            <h1>{settings.business_name || "Aaiji Nursery"}</h1>
            <p className="lead">{settings.intro}</p>
            <div className="hero-actions">
              <Link to="/plants" className="btn btn-primary">
                Browse Plants
              </Link>
              <Link to="/contact" className="btn btn-outline">
                <span className="hide-mobile">Get a Free Consultation</span>
                <span>Enquire Now</span>
              </Link>
            </div>
          </div>
          <div className="hero-image">
            <HeroImageSlider
              alt="Lush green plants"
              images={parseHeroImages(settings.hero_images)}
              intervalSeconds={settings.hero_slide_seconds}
            />
          </div>
        </div>
      </section>

      {/* Mobile-only horizontal browsing (see .landing-mobile-only in
          index.css) — desktop keeps the "Shop by Category" tiles and
          "Featured Plants" grid below instead, completely unchanged. */}
      <div className="landing-mobile-only">
        <div className="container">
          {featured && featured.length > 0 && (
            <PlantCarousel title="Popular Plants" viewAllHref="/plants" plants={featured.slice(0, CAROUSEL_ITEM_LIMIT)} />
          )}
          {categories &&
            categories.map((cat) => (
              <PlantCarousel
                key={cat.id}
                title={cat.name}
                viewAllHref={`/plants?category=${cat.slug}`}
                plants={categoryPlants[cat.slug]}
              />
            ))}
        </div>
      </div>

      <PlantExplorer />

      <section className="section landing-desktop-only">
        <div className="container">
          <div className="section-head">
            <span className="eyebrow">What we offer</span>
            <h2>Shop by Category</h2>
            <p>From indoor greens to full landscaping supplies - find exactly what your space needs.</p>
          </div>
          {!categories ? (
            <Loading />
          ) : (
            <div className="grid grid-4">
              {categories.map((cat) => (
                <Link key={cat.id} to={`/plants?category=${cat.slug}`} className="card">
                  <img src={cat.image_url} alt={cat.name} loading="lazy" />
                  <div className="card-body">
                    <h3 style={{ fontSize: "1.05rem", margin: 0 }}>{cat.name}</h3>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="section section-alt landing-desktop-only">
        <div className="container">
          <div className="section-head">
            <span className="eyebrow">Customer favourites</span>
            <h2>Featured Plants</h2>
          </div>
          {!featured ? (
            <Loading />
          ) : (
            <div className="grid grid-4 grid-plants">
              {featured.map((plant) => (
                <PlantCard key={plant.id} plant={plant} />
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="section">
        <div className="container">
          <div className="stat-row">
            <div>
              <div className="num">{settings.years_experience}+</div>
              <div className="label">Years of Experience</div>
            </div>
            <div>
              <div className="num">5000+</div>
              <div className="label">Happy Customers</div>
            </div>
            <div>
              <div className="num">150+</div>
              <div className="label">Plant Varieties</div>
            </div>
            <div>
              <div className="num">30+</div>
              <div className="label">Cities Served</div>
            </div>
          </div>
        </div>
      </section>

      <section className="section section-alt">
        <div className="container">
          <div className="section-head">
            <span className="eyebrow">Social proof</span>
            <h2>What Our Customers Say</h2>
          </div>
          {!testimonials ? (
            <Loading />
          ) : (
            <div className="grid grid-3">
              {testimonials.map((t) => (
                <div key={t.id} className="card">
                  <div className="card-body">
                    <Stars rating={t.rating} />
                    <p style={{ marginTop: 10, color: "var(--color-text-muted)" }}>
                      &ldquo;{t.message}&rdquo;
                    </p>
                    <div className="testimonial-author">
                      <Avatar name={t.customer_name} src={t.image_url} size={40} />
                      <strong>{t.customer_name}</strong>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
