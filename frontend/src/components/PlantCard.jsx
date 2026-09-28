import { Link } from "react-router-dom";
import AddToCartButton from "./AddToCartButton";
import BuyNowButton from "./BuyNowButton";
import WishlistButton from "./WishlistButton";

export default function PlantCard({ plant }) {
  const hasVariants = plant.variants && plant.variants.length > 0;
  const trayPrices = hasVariants ? plant.variants.map((v) => v.price) : [];
  const fromPrice = trayPrices.length > 0 ? Math.min(...trayPrices) : null;

  return (
    <div className="card plant-card">
      <WishlistButton plant={plant} iconOnly className="card-wishlist-btn" />
      <Link to={`/plants/${plant.slug}`} className="card-link">
        <img src={plant.image_url} alt={plant.name} loading="lazy" />
        <div className="card-body">
          {plant.category && <span className="badge badge-accent">{plant.category.name}</span>}
          <h3 className="plant-card-title">{plant.name}</h3>
          <p className="plant-card-desc">
            {plant.description?.slice(0, 80)}
            {plant.description?.length > 80 ? "..." : ""}
          </p>
          <div className="price">
            {hasVariants ? (
              <>From &#8377;{fromPrice}</>
            ) : (
              <>
                &#8377;{plant.effective_price}
                {plant.discount_price ? <span className="strike">&#8377;{plant.price}</span> : null}
              </>
            )}
          </div>
        </div>
      </Link>
      <div className="card-actions card-actions-row">
        {hasVariants ? (
          <Link to={`/plants/${plant.slug}`} className="btn btn-primary btn-sm" style={{ flex: 1 }}>
            View Tray Options
          </Link>
        ) : (
          <>
            <AddToCartButton plant={plant} className="btn-sm" style={{ flex: 1 }} />
            <BuyNowButton plant={plant} className="btn-sm" style={{ flex: 1 }} />
          </>
        )}
      </div>
    </div>
  );
}
