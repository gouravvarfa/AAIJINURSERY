import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useWishlist } from "../context/WishlistContext";
import { useCart } from "../context/CartContext";
import { Loading, Empty } from "../components/Loading";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

function WishlistRow({ item, onRemove }) {
  const { addToCart } = useCart();
  const [busy, setBusy] = useState(false);
  const plant = item.plant;
  const outOfStock = !plant || plant.stock_quantity <= 0;

  async function handleAddToCart() {
    if (!plant || busy) return;
    setBusy(true);
    try {
      await addToCart(plant);
    } finally {
      setBusy(false);
    }
  }

  async function handleRemove() {
    if (busy) return;
    setBusy(true);
    try {
      await onRemove(item.plant_id);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="wishlist-row">
      <Link to={plant ? `/plants/${plant.slug}` : "#"} className="cart-row-image">
        <img src={plant?.image_url} alt={plant?.name || "Plant"} />
      </Link>

      <div className="cart-row-info">
        <Link to={plant ? `/plants/${plant.slug}` : "#"} className="cart-row-name">
          {plant?.name || "Unavailable product"}
        </Link>
        {plant && <div className="cart-row-price">&#8377;{plant.effective_price}</div>}
        <span className={`badge ${outOfStock ? "badge-gold" : "badge-accent"}`} style={{ marginTop: 6 }}>
          {outOfStock ? "Made to Order" : "In Stock"}
        </span>
      </div>

      <div className="wishlist-row-actions">
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={handleAddToCart}
          disabled={busy}
        >
          Add to Cart
        </button>
        <button type="button" className="btn btn-outline dark btn-sm" onClick={handleRemove} disabled={busy}>
          Remove
        </button>
      </div>
    </div>
  );
}

export default function Wishlist() {
  useDocumentTitle("My Wishlist | Aaiji Nursery");
  const { session } = useAuth();
  const { items, loading, removeFromWishlist } = useWishlist();

  if (session === undefined) return <Loading />;
  if (session === null)
    return (
      <Navigate
        to="/login"
        state={{ from: "/wishlist", backgroundLocation: { pathname: "/" } }}
        replace
      />
    );
  if (session.type !== "customer") return <Navigate to="/" replace />;

  return (
    <>
      <section className="page-hero">
        <div className="container">
          <h1>My Wishlist</h1>
          <p>Plants you've saved for later.</p>
        </div>
      </section>

      <section className="section">
        <div className="container">
          {loading ? (
            <Loading />
          ) : items.length === 0 ? (
            <Empty>
              <p style={{ fontSize: "1.1rem", fontWeight: 600, color: "var(--color-text)" }}>
                Your wishlist is empty
              </p>
              <Link to="/plants" className="btn btn-primary" style={{ marginTop: 16 }}>
                Browse Plants
              </Link>
            </Empty>
          ) : (
            <div className="wishlist-list">
              {items.map((item) => (
                <WishlistRow key={item.id} item={item} onRemove={removeFromWishlist} />
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
