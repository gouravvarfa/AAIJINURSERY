import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import PlantCard from "../components/PlantCard";
import AddToCartButton from "../components/AddToCartButton";
import BuyNowButton from "../components/BuyNowButton";
import WishlistButton from "../components/WishlistButton";
import TraySelector from "../components/TraySelector";
import EnquireModal from "../components/EnquireModal";
import PlantReviews from "../components/PlantReviews";
import { Loading, Empty } from "../components/Loading";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useProductStructuredData } from "../hooks/useProductStructuredData";
import { useMetaTags } from "../hooks/useMetaTags";

export default function PlantDetail() {
  const { slug } = useParams();
  const [plant, setPlant] = useState(null);
  const [related, setRelated] = useState(null);
  const [notFound, setNotFound] = useState(false);
  const [selectedVariantId, setSelectedVariantId] = useState(null);
  const [quantity, setQuantity] = useState(1);
  const [showEnquireModal, setShowEnquireModal] = useState(false);
  const [reviewsData, setReviewsData] = useState(null);
  useDocumentTitle(plant ? `${plant.name} | Aaiji Nursery` : "Plant Details | Aaiji Nursery");

  function loadReviews() {
    api.get(`/plants/${slug}/reviews`).then(setReviewsData).catch(() => setReviewsData(null));
  }

  useEffect(() => {
    setPlant(null);
    setNotFound(false);
    setSelectedVariantId(null);
    setQuantity(1);
    setReviewsData(null);
    api
      .get(`/plants/${slug}`)
      .then(setPlant)
      .catch(() => setNotFound(true));
    api.get(`/plants/${slug}/recommendations`).then(setRelated).catch(() => setRelated([]));
    loadReviews();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  useProductStructuredData(plant, reviewsData);
  useMetaTags(
    plant
      ? {
          title: `${plant.name} | Aaiji Nursery`,
          description: (plant.description || `Buy ${plant.name} online from Aaiji Nursery. Quality plants with doorstep delivery.`).slice(0, 160),
          image: plant.image_url,
        }
      : undefined
  );

  if (notFound) {
    return (
      <div className="section container">
        <Empty>Plant not found.</Empty>
        <div style={{ textAlign: "center" }}>
          <Link to="/plants" className="btn btn-primary">
            Back to Catalog
          </Link>
        </div>
      </div>
    );
  }

  if (!plant) return <Loading />;

  const hasVariants = plant.variants && plant.variants.length > 0;

  function handleSelectVariant(variantId) {
    setSelectedVariantId(variantId);
    setQuantity(1);
  }

  return (
    <>
      <section className="section">
        <div className="container">
          <div className="grid grid-2">
            <img
              className="card"
              style={{ aspectRatio: "4/3", objectFit: "contain", background: "var(--color-bg, #f4f4f0)" }}
              src={plant.image_url}
              alt={plant.name}
            />
            <div>
              {plant.category && (
                <Link to={`/plants?category=${plant.category.slug}`} className="badge badge-accent">
                  {plant.category.name}
                </Link>
              )}
              <h1 style={{ marginTop: 14 }}>{plant.name}</h1>
              <div className="plant-meta">
                <span className="badge badge-muted">Care: {plant.care_level}</span>
                <span
                  className={`badge ${plant.stock_quantity > 0 ? "badge-accent" : "badge-gold"}`}
                >
                  {plant.availability_status === "ENQUIRY_AVAILABLE"
                    ? "Currently Out of Stock"
                    : plant.stock_quantity > 0
                    ? "In Stock"
                    : "Out of Stock"}
                </span>
                {plant.sku && <span className="badge badge-muted">SKU: {plant.sku}</span>}
              </div>
              {plant.availability_status === "ENQUIRY_AVAILABLE" && (
                <p style={{ color: "var(--color-text-muted)", marginTop: -6, marginBottom: 14 }}>
                  We may be able to prepare this plant on request.
                </p>
              )}
              {hasVariants ? (
                <div style={{ marginBottom: 16 }}>
                  <TraySelector
                    plant={plant}
                    selectedVariantId={selectedVariantId}
                    onSelect={handleSelectVariant}
                    quantity={quantity}
                    onQuantityChange={setQuantity}
                  />
                </div>
              ) : (
                <div style={{ marginBottom: 16 }}>
                  <div className="price" style={{ fontSize: "1.6rem", marginBottom: plant.stock_quantity > 0 ? 10 : 0 }}>
                    &#8377;{plant.effective_price}
                    {plant.discount_price ? <span className="strike">&#8377;{plant.price}</span> : null}
                  </div>
                  {plant.stock_quantity > 0 && (
                    <div className="cart-row-qty">
                      <button
                        type="button"
                        className="qty-btn"
                        onClick={() => setQuantity((q) => Math.max(1, q - 1))}
                        disabled={quantity <= 1}
                        aria-label="Decrease quantity"
                      >
                        &minus;
                      </button>
                      <span className="qty-value">{quantity}</span>
                      <button
                        type="button"
                        className="qty-btn"
                        onClick={() => setQuantity((q) => Math.min(plant.stock_quantity, q + 1))}
                        disabled={quantity >= plant.stock_quantity}
                        aria-label="Increase quantity"
                      >
                        +
                      </button>
                    </div>
                  )}
                </div>
              )}
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 24 }}>
                {plant.availability_status === "ENQUIRY_AVAILABLE" ? (
                  <button type="button" className="btn btn-primary" onClick={() => setShowEnquireModal(true)}>
                    Enquire Now
                  </button>
                ) : (
                  <>
                    <AddToCartButton plant={plant} variantId={selectedVariantId} quantity={quantity} />
                    <BuyNowButton plant={plant} variantId={selectedVariantId} quantity={quantity} />
                    <Link
                      to={`/contact?plant_id=${plant.id}&plant_name=${encodeURIComponent(plant.name)}`}
                      className="btn btn-outline dark"
                    >
                      Enquire About This Plant
                    </Link>
                  </>
                )}
                <WishlistButton plant={plant} />
              </div>
              <p>{plant.description}</p>
              {plant.feature_list?.length > 0 && (
                <ul className="feature-list" style={{ marginBottom: 24 }}>
                  {plant.feature_list.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="section section-alt">
        <div className="container">
          <PlantReviews plant={plant} data={reviewsData} onChanged={loadReviews} />
        </div>
      </section>

      {showEnquireModal && <EnquireModal plant={plant} onClose={() => setShowEnquireModal(false)} />}

      {related && related.length > 0 && (
        <section className="section section-alt">
          <div className="container">
            <div className="section-head">
              <h2>You Might Also Like</h2>
            </div>
            <div className="grid grid-4 grid-plants">
              {related.map((p) => (
                <PlantCard key={p.id} plant={p} />
              ))}
            </div>
          </div>
        </section>
      )}
    </>
  );
}
