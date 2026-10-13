import { useCart } from "../context/CartContext";

export default function BuyNowButton({ plant, variantId = null, quantity = 1, className = "", style }) {
  const { buyNow } = useCart();
  const hasVariants = plant.variants && plant.variants.length > 0;
  const selectedVariant = hasVariants ? plant.variants.find((v) => v.id === variantId) : null;
  const needsVariant = hasVariants && !selectedVariant;
  const invalidQuantity = !Number.isInteger(quantity) || quantity < 1;
  const disabled = needsVariant || invalidQuantity;

  function handleClick(e) {
    e.preventDefault();
    e.stopPropagation();
    if (disabled) return;
    buyNow(plant, quantity, variantId);
  }

  return (
    <button
      type="button"
      className={`btn btn-gold ${className}`}
      style={style}
      onClick={handleClick}
      disabled={disabled}
    >
      {needsVariant
        ? "Select a Tray Size"
        : "Buy Now"}
    </button>
  );
}
