import { useEffect, useState } from "react";

// Fallback only -- the real list comes from Site Settings ("hero_images"),
// editable by admins, and the backend already supplies these same defaults.
const DEFAULT_IMAGES = [
  "https://images.unsplash.com/photo-1466692476868-aef1dfb1e735?w=900",
  "https://images.unsplash.com/photo-1416879595882-3373a0480b5b?w=900",
  "https://images.unsplash.com/photo-1512428813834-c702c7702b78?w=900",
  "https://images.unsplash.com/photo-1466781783364-36c955e42a7f?w=900",
];

export function parseHeroImages(value) {
  const list = (value || "").split("\n").map((s) => s.trim()).filter(Boolean);
  return list.length ? list : DEFAULT_IMAGES;
}

export default function HeroImageSlider({ alt, images, intervalSeconds }) {
  const list = images && images.length ? images : DEFAULT_IMAGES;
  const seconds = Number(intervalSeconds) >= 2 ? Number(intervalSeconds) : 4;
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    setActiveIndex(0);
    if (list.length < 2) return undefined;
    const timer = setInterval(() => {
      setActiveIndex((prev) => (prev + 1) % list.length);
    }, seconds * 1000);
    return () => clearInterval(timer);
  }, [list.join("\n"), seconds]);

  return (
    <>
      {list.map((src, index) => (
        <img
          key={`${index}-${src}`}
          src={src}
          alt={alt}
          className={index === activeIndex ? "is-active" : undefined}
        />
      ))}
    </>
  );
}
