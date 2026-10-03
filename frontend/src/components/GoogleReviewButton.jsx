// Small branded CTA for the configured Google Review link. Deliberately NOT
// a generic outline button -- a recognizable Google "G" mark + neutral
// copy reads as a legitimate review prompt rather than a plain link.
export function GoogleG({ size = 18 }) {
  return (
    <svg viewBox="0 0 48 48" width={size} height={size} aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.1 8 3l5.7-5.7C34.6 6.1 29.6 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.7-.4-3.5z"/>
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 15.1 18.9 12 24 12c3.1 0 5.8 1.1 8 3l5.7-5.7C34.6 6.1 29.6 4 24 4c-7.4 0-13.8 4.2-17 10.3z"/>
      <path fill="#4CAF50" d="M24 44c5.5 0 10.4-1.9 14.2-5l-6.6-5.6c-2 1.4-4.6 2.3-7.6 2.3-5.2 0-9.6-3.4-11.2-8l-6.6 5.1C9.9 39.7 16.4 44 24 44z"/>
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.3 4.3-4.1 5.7l6.6 5.6c-.5.4 7.2-5.2 7.2-15.3 0-1.3-.1-2.7-.4-3.5z"/>
    </svg>
  );
}

// Small branded CTA for the configured Google Review link. Deliberately NOT
// a generic outline button -- a recognizable Google "G" mark + neutral
// copy reads as a legitimate review prompt rather than a plain link.
export default function GoogleReviewButton({ url, label = "Rate us on Google" }) {
  if (!url) return null;
  return (
    <button
      type="button"
      className="google-review-btn"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        window.open(url, "_blank", "noopener,noreferrer");
      }}
    >
      <GoogleG />
      <span>{label}</span>
      <svg className="google-review-btn-ext" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
        <path fill="currentColor" d="M14 3h7v7h-2V6.41l-9.29 9.3-1.42-1.42 9.3-9.29H14V3zM5 5h5v2H5v12h12v-5h2v7H5V5z"/>
      </svg>
    </button>
  );
}
