import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useCart } from "../context/CartContext";

// Fixed mobile-only bottom tab bar -- reuses the exact same auth/cart state
// and routes as the desktop Navbar, never a parallel system. Hidden on
// admin/developer routes (session.type !== "customer") and on desktop via
// CSS (.bottom-nav is display:none above 767px, see index.css).
const ICONS = {
  home: (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 10.5 12 3l9 7.5" />
      <path d="M5 9.5V21h14V9.5" />
    </svg>
  ),
  shop: (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 7h12l1 13H5L6 7z" />
      <path d="M9 7a3 3 0 0 1 6 0" />
    </svg>
  ),
  search: (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  ),
  cart: (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="9" cy="21" r="1" />
      <circle cx="19" cy="21" r="1" />
      <path d="M2 3h2l2.4 12.2a2 2 0 0 0 2 1.8h8.6a2 2 0 0 0 2-1.6L21 7H6" />
    </svg>
  ),
  account: (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c1.5-4 5-6 8-6s6.5 2 8 6" />
    </svg>
  ),
};

export default function BottomNav() {
  const location = useLocation();
  const navigate = useNavigate();
  const { session } = useAuth();
  const { cartCount } = useCart();

  // Never shown for an admin/developer session -- customer tab bar only.
  if (session && session.type !== "customer") return null;

  function goAccount(e) {
    e.preventDefault();
    if (session === null) {
      navigate("/login", { state: { backgroundLocation: location, from: "/account" } });
    } else {
      navigate("/account");
    }
  }

  // No dedicated /search route exists -- the real search (autosuggest,
  // debounce, "view all results") already lives in NavSearch, which is
  // already rendered on every page as the mobile search bar under the
  // navbar. Reuse it instead of building a second search system: scroll up
  // and focus that same input.
  function focusSearch(e) {
    e.preventDefault();
    window.scrollTo({ top: 0, behavior: "smooth" });
    document.getElementById("nav-search-input")?.focus();
  }

  return (
    <nav className="bottom-nav" aria-label="Primary">
      <NavLink to="/" end className="bottom-nav-item">
        <span className="bottom-nav-icon">{ICONS.home}</span>
        <span className="bottom-nav-label">Home</span>
      </NavLink>
      <NavLink to="/plants" className="bottom-nav-item">
        <span className="bottom-nav-icon">{ICONS.shop}</span>
        <span className="bottom-nav-label">Shop</span>
      </NavLink>
      <a href="#" className="bottom-nav-item" onClick={focusSearch}>
        <span className="bottom-nav-icon">{ICONS.search}</span>
        <span className="bottom-nav-label">Search</span>
      </a>
      <NavLink to="/cart" className="bottom-nav-item">
        <span className="bottom-nav-icon bottom-nav-icon-cart">
          {ICONS.cart}
          {cartCount > 0 && <span className="bottom-nav-badge">{cartCount}</span>}
        </span>
        <span className="bottom-nav-label">Cart</span>
      </NavLink>
      <a
        href={session === null ? "/login" : "/account"}
        className={`bottom-nav-item${location.pathname.startsWith("/account") || location.pathname.startsWith("/orders") ? " active" : ""}`}
        onClick={goAccount}
      >
        <span className="bottom-nav-icon">{ICONS.account}</span>
        <span className="bottom-nav-label">{session === null ? "Login" : "Account"}</span>
      </a>
    </nav>
  );
}
