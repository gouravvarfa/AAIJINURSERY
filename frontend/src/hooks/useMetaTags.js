import { useEffect } from "react";

function upsertMeta(attr, key, content) {
  let el = document.head.querySelector(`meta[${attr}="${key}"]`);
  const created = !el;
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  const previous = el.getAttribute("content");
  el.setAttribute("content", content);
  return { el, previous, created };
}

// Sets per-page meta description + Open Graph/Twitter tags (title, description,
// image, url), restoring whatever was there before on unmount/change -- same
// pattern as useDocumentTitle but for <head> metadata that search engines and
// link-preview crawlers (WhatsApp, Facebook) read instead of just the title.
export function useMetaTags({ title, description, image, url } = {}) {
  useEffect(() => {
    if (!description) return;
    const canonicalUrl = url || window.location.href;
    const entries = [
      upsertMeta("name", "description", description),
      upsertMeta("property", "og:title", title || document.title),
      upsertMeta("property", "og:description", description),
      upsertMeta("property", "og:url", canonicalUrl),
      upsertMeta("name", "twitter:description", description),
    ];
    if (image) {
      entries.push(upsertMeta("property", "og:image", image));
      entries.push(upsertMeta("name", "twitter:image", image));
    }

    let canonicalLink = document.head.querySelector('link[rel="canonical"]');
    const canonicalCreated = !canonicalLink;
    if (!canonicalLink) {
      canonicalLink = document.createElement("link");
      canonicalLink.setAttribute("rel", "canonical");
      document.head.appendChild(canonicalLink);
    }
    const previousHref = canonicalLink.getAttribute("href");
    canonicalLink.setAttribute("href", canonicalUrl);

    return () => {
      entries.forEach(({ el, previous, created }) => {
        if (created) el.remove();
        else if (previous !== null) el.setAttribute("content", previous);
      });
      if (canonicalCreated) canonicalLink.remove();
      else if (previousHref !== null) canonicalLink.setAttribute("href", previousHref);
    };
  }, [title, description, image, url]);
}
