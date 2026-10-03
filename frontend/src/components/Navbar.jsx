import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useCart } from "../context/CartContext";
import { useSettings } from "../context/SettingsContext";
import NavSearch from "./NavSearch";
import logoImg from "../assets/logo.png";

// Icons are only ever shown in the mobile drawer (desktop's .nav-links
// ignores .nav-link-icon entirely) — plain emoji to match the rest of the
// app's icon approach (cart, login, account avatar) rather than pulling in
// an icon library.
const LINKS = [
  { to: "/", label: "Home", icon: "\u{1F3E0}" },
  { to: "/about", label: "About Us", icon: "ℹ️" },
  { to: "/plants", label: "Shop", icon: "\u{1F33F}" },
  { to: "/services", label: "Services", icon: "⚙️" },
  { to: "/pricing", label: "Pricing", icon: "\u{1F3F7}️" },
  { to: "/gallery", label: "Gallery", icon: "\u{1F5BC}️" },
  { to: "/blog", label: "Blog", icon: "\u{1F4C4}" },
  { to: "/faqs", label: "FAQs", icon: "❓" },
  { to: "/contact", label: "Contact", icon: "\u{1F4DE}" },
];

// Matches the existing "collapse to hamburger" breakpoint in index.css
// (.nav-links goes fixed/off-canvas at this width) — the account dropdown
// should only intercept clicks in that same regime, never on desktop.
const MOBILE_BREAKPOINT = "(max-width: 767px)";

export default function Navbar() {
  const [open, setOpen] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const settings = useSettings();
  const { session, logout } = useAuth();
  const { cartCount } = useCart();
  const navigate = useNavigate();
  const location = useLocation();
  const accountRef = useRef(null);

  useEffect(() => {
    if (!dropdownOpen) return;
    function handleClickOutside(e) {
      if (accountRef.current && !accountRef.current.contains(e.target)) {
        setDropdownOpen(false);
      }
    }
    function handleEscape(e) {
      if (e.key === "Escape") setDropdownOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [dropdownOpen]);

  async function handleLogout() {
    setDropdownOpen(false);
    await logout();
    navigate("/");
  }

  // Desktop: unchanged — the avatar link navigates straight to /account (or
  // /admin), exactly as before. Mobile only: intercept the tap to open the
  // dropdown instead of navigating immediately.
  function handleAccountClick(e) {
    if (window.matchMedia(MOBILE_BREAKPOINT).matches) {
      e.preventDefault();
      setDropdownOpen((v) => !v);
    } else {
      setOpen(false);
    }
  }

  return (
    <header className="navbar">
      <div className="container">
        <NavLink to="/" className="brand" onClick={() => setOpen(false)}>
          <img className="brand-logo" src={logoImg} alt={settings.business_name || "Shri Aaiji Hightech Nursery"} />
        </NavLink>

        {open && (
          <div className="nav-links-backdrop" onClick={() => setOpen(false)} aria-hidden="true" />
        )}

        <nav className={`nav-links ${open ? "open" : ""}`}>
          <button
            type="button"
            className="nav-links-close"
            aria-label="Close menu"
            onClick={() => setOpen(false)}
          >
            &times;
          </button>
          {LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === "/"}
              onClick={() => setOpen(false)}
            >
              <span className="nav-link-icon" aria-hidden="true">
                {link.icon}
              </span>
              {link.label}
            </NavLink>
          ))}
          <NavLink to="/contact" className="btn btn-primary" onClick={() => setOpen(false)}>
            Get in Touch
          </NavLink>
        </nav>

        <div className="nav-right">
        <div className="nav-actions">
          <NavSearch />

          {session?.type === "customer" && (
            <NavLink to="/cart" className="nav-cart-link" onClick={() => setOpen(false)} aria-label="My Cart">
              <span aria-hidden="true">&#128722;</span>
              {cartCount > 0 && <span className="nav-cart-count">{cartCount}</span>}
            </NavLink>
          )}

          {session === undefined ? null : session === null ? (
            <NavLink
              to="/login"
              state={{ backgroundLocation: location }}
              className="nav-login-btn"
              onClick={() => setOpen(false)}
            >
              <span className="nav-login-icon" aria-hidden="true">
                &#128100;
              </span>
              <span className="nav-login-text">Login</span>
            </NavLink>
          ) : session.type === "customer" ? (
            <div className="nav-account" ref={accountRef}>
              <NavLink to="/account" className="nav-account-link" onClick={handleAccountClick}>
                <span className="nav-account-avatar" aria-hidden="true">
                  {(session.name || "U").charAt(0).toUpperCase()}
                </span>
                <span className="nav-account-name">{session.name}</span>
              </NavLink>
              <button type="button" className="nav-account-logout" onClick={handleLogout}>
                Logout
              </button>
              {dropdownOpen && (
                <div className="nav-account-dropdown">
                  <NavLink to="/account" onClick={() => setDropdownOpen(false)}>
                    <span aria-hidden="true">&#128100;</span> My Account
                  </NavLink>
                  <NavLink to="/orders" onClick={() => setDropdownOpen(false)}>
                    <span aria-hidden="true">&#128230;</span> My Orders
                  </NavLink>
                  <button type="button" className="nav-account-dropdown-logout" onClick={handleLogout}>
                    <span aria-hidden="true">&#128682;</span> Logout
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="nav-account" ref={accountRef}>
              <NavLink to="/admin" className="nav-account-link" onClick={handleAccountClick}>
                <span className="nav-account-avatar" aria-hidden="true">
                  &#128100;
                </span>
                <span className="nav-account-name">Dashboard</span>
              </NavLink>
              <button type="button" className="nav-account-logout" onClick={handleLogout}>
                Logout
              </button>
              {dropdownOpen && (
                <div className="nav-account-dropdown">
                  <NavLink to="/admin" onClick={() => setDropdownOpen(false)}>
                    <span aria-hidden="true">&#128100;</span> Dashboard
                  </NavLink>
                  <button type="button" className="nav-account-dropdown-logout" onClick={handleLogout}>
                    <span aria-hidden="true">&#128682;</span> Logout
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        <button
          className="nav-toggle"
          aria-label="Toggle navigation menu"
          onClick={() => setOpen((v) => !v)}
        >
          <span style={open ? { transform: "translateY(7px) rotate(45deg)" } : undefined} />
          <span style={open ? { opacity: 0 } : undefined} />
          <span style={open ? { transform: "translateY(-7px) rotate(-45deg)" } : undefined} />
        </button>
        </div>
      </div>
    </header>
  );
}
