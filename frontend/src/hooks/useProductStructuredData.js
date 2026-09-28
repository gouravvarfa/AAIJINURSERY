import { useEffect } from "react";

const SCRIPT_ID = "product-structured-data";

// Injects schema.org Product JSON-LD for the plant detail page, so Google
// can show star-rating rich snippets in search results. Deliberately only
// includes aggregateRating/review when real PUBLISHED reviews exist --
// never a fake/default rating -- so the markup always matches what a
// visitor actually sees on the page (Google's structured-data policy
// requires this; a mismatch risks a manual action, not just "no stars").
export function useProductStructuredData(plant, reviewsData) {
  useEffect(() => {
    if (!plant) return undefined;

    const data = {
      "@context": "https://schema.org/",
      "@type": "Product",
      name: plant.name,
      description: plant.description || undefined,
      image: plant.image_url ? [plant.image_url] : undefined,
      sku: plant.sku || undefined,
      offers: {
        "@type": "Offer",
        price: String(plant.effective_price),
        priceCurrency: "INR",
        availability:
          plant.stock_quantity > 0
            ? "https://schema.org/InStock"
            : "https://schema.org/OutOfStock",
        url: window.location.href,
      },
    };

    if (reviewsData && reviewsData.review_count > 0) {
      data.aggregateRating = {
        "@type": "AggregateRating",
        ratingValue: reviewsData.average_rating,
        reviewCount: reviewsData.review_count,
      };
      data.review = reviewsData.reviews.map((r) => ({
        "@type": "Review",
        author: { "@type": "Person", name: r.customer_name },
        reviewRating: { "@type": "Rating", ratingValue: r.rating, bestRating: 5, worstRating: 1 },
        reviewBody: r.comment || undefined,
        datePublished: r.created_at,
      }));
    }

    let script = document.getElementById(SCRIPT_ID);
    if (!script) {
      script = document.createElement("script");
      script.id = SCRIPT_ID;
      script.type = "application/ld+json";
      document.head.appendChild(script);
    }
    script.textContent = JSON.stringify(data);

    return () => {
      script?.remove();
    };
  }, [plant, reviewsData]);
}
