import { useEffect, useRef, useState } from "react";
import { Navigate, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Loading } from "../components/Loading";
import ErrorBoundary from "../components/ErrorBoundary";
import { OrderAlertProvider } from "./OrderAlertContext";
import OrderAlertBell from "./OrderAlertBell";
import logoImg from "../assets/logo.png";

// `module: null` means always visible to any logged-in admin (e.g. the
// dashboard landing page). Everything else is filtered through
// hasPermission(module) below -- for the legacy "admin"/"developer" roles
// and "super_access" this hides nothing (their seeded roles grant full
// business access), it only actually restricts a "custom" role.
const NAV = [
  { to: "/admin", label: "Dashboard", end: true, module: null },
  { to: "/admin/analytics", label: "Analytics", module: "analytics" },
  { to: "/admin/orders", label: "Orders", module: "orders" },
  { to: "/admin/categories", label: "Categories", module: "products" },
  { to: "/admin/plants", label: "Plants", module: "products" },
  { to: "/admin/purchases", label: "Purchases", module: "products" },
  { to: "/admin/services", label: "Services", module: "website" },
  { to: "/admin/pricing-plans", label: "Pricing Plans", module: "website" },
  { to: "/admin/faqs", label: "FAQs", module: "website" },
  { to: "/admin/testimonials", label: "Testimonials", module: "website" },
  { to: "/admin/gallery", label: "Gallery", module: "website" },
  { to: "/admin/blog", label: "Blog", module: "website" },
  { to: "/admin/inquiries", label: "Inquiries", module: "customers" },
  { to: "/admin/reviews", label: "Reviews", module: "products" },
  { to: "/admin/customers", label: "Customers", module: "customers" },
  { to: "/admin/customer-logs", label: "Customer Logs", module: "customers" },
  { to: "/admin/settings", label: "Site Settings", module: "website" },
];

const DEVELOPER_NAV = [
  { to: "/admin/admins", label: "Admins" },
  { to: "/admin/developer/activity-log", label: "Activity Log" },
  { to: "/admin/developer/roles-permissions", label: "Roles & Permissions" },
  { to: "/admin/developer/sessions", label: "Sessions" },
  { to: "/admin/developer/login-attempts", label: "Login Attempts" },
  { to: "/admin/developer/system-info", label: "System Info" },
  { to: "/admin/developer/system-health", label: "System Health", end: true },
  { to: "/admin/developer/system-health/errors", label: "Active Errors" },
  { to: "/admin/developer/system-health/history", label: "Error History" },
  { to: "/admin/developer/system-health/functions", label: "Function Monitoring" },
  { to: "/admin/developer/system-health/logs", label: "System Logs" },
  { to: "/admin/developer/live-logs", label: "Live Logs" },
  { to: "/admin/accounting/roles", label: "Accounting Roles" },
];

const ACCOUNTING_NAV = [
  { to: "/admin/accounting", label: "Overview", end: true, module: "accounting" },
  { to: "/admin/accounting/sales-orders", label: "Sales Orders", module: "accounting" },
  { to: "/admin/accounting/invoices", label: "Invoices", module: "accounting" },
  { to: "/admin/accounting/purchase-orders", label: "Purchase Orders", module: "accounting" },
  { to: "/admin/accounting/bills", label: "Bills", module: "accounting" },
  { to: "/admin/accounting/expenses", label: "Expenses", module: "accounting" },
  { to: "/admin/accounting/parties", label: "Parties", module: "accounting" },
  { to: "/admin/accounting/employees", label: "Employees", module: "accounting" },
  { to: "/admin/accounting/reports", label: "Reports", module: "accounting" },
  { to: "/admin/accounting/chart-of-accounts", label: "Chart of Accounts", module: "accounting" },
  { to: "/admin/accounting/tax-rates", label: "Tax Rates", module: "accounting" },
];

const WORKFORCE_NAV = [
  { to: "/admin/labour", label: "Dashboard", end: true, module: "labour" },
  { to: "/admin/labour/employees", label: "Employees", module: "labour" },
  { to: "/admin/labour/labour", label: "Labour", module: "labour" },
  { to: "/admin/labour/todays-work", label: "Today's Work", module: "labour" },
  { to: "/admin/labour/attendance", label: "Attendance", module: "labour" },
  { to: "/admin/labour/payroll", label: "Payroll", module: "labour" },
  { to: "/admin/labour/payments", label: "Payments", module: "labour" },
  { to: "/admin/labour/advances", label: "Advances", module: "labour" },
];

const DELIVERY_NAV = [
  { to: "/admin/delivery", label: "Dashboard", end: true, module: "delivery" },
  { to: "/admin/delivery/deliveries", label: "Delivery History", module: "delivery" },
  { to: "/admin/delivery/drivers", label: "Drivers", module: "delivery" },
  { to: "/admin/delivery/vehicles", label: "Vehicles", module: "delivery" },
  { to: "/admin/delivery/trips", label: "Trips", module: "delivery" },
  { to: "/admin/delivery/fuel", label: "Fuel / Petrol", module: "delivery" },
];

const COMMUNICATIONS_NAV = [
  { to: "/admin/communications", label: "Dashboard", end: true, module: "communications" },
  { to: "/admin/communications/send", label: "Send Message", module: "communications" },
  { to: "/admin/communications/templates", label: "Templates", module: "communications" },
  { to: "/admin/communications/event-map", label: "Event Mapping", module: "communications" },
  { to: "/admin/communications/history", label: "Message History", module: "communications" },
  { to: "/admin/communications/settings", label: "Settings", module: "communications" },
];

function NavGroup({ heading, items, hasPermission }) {
  const visible = items.filter((item) => item.module == null || hasPermission(item.module));
  if (visible.length === 0) return null;
  return (
    <>
      {heading && <div className="admin-nav-heading">{heading}</div>}
      {visible.map((item) => (
        <NavLink key={item.to} to={item.to} end={item.end}>
          {item.label}
        </NavLink>
      ))}
    </>
  );
}

function HamburgerIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M3 6h18M3 12h18M3 18h18" />
    </svg>
  );
}
function ChevronIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}
function HomeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 10.5 12 3l9 7.5" />
      <path d="M5 9.5V21h14V9.5" />
    </svg>
  );
}
function OrdersIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3h2l2.4 12.2a2 2 0 0 0 2 1.8h8.6a2 2 0 0 0 2-1.6L21 7H6" />
      <circle cx="9" cy="21" r="1" /><circle cx="19" cy="21" r="1" />
    </svg>
  );
}
function ProductsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 7h12l1 13H5L6 7z" /><path d="M9 7a3 3 0 0 1 6 0" />
    </svg>
  );
}
function MoreIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <circle cx="5" cy="12" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="19" cy="12" r="1.5" />
    </svg>
  );
}

function AdminBottomNav({ onMore }) {
  return (
    <nav className="admin-bottom-nav" aria-label="Admin quick navigation">
      <NavLink to="/admin" end>
        <HomeIcon />
        Home
      </NavLink>
      <NavLink to="/admin/orders">
        <OrdersIcon />
        Orders
      </NavLink>
      <NavLink to="/admin/plants">
        <ProductsIcon />
        Products
      </NavLink>
      <button type="button" onClick={onMore}>
        <MoreIcon />
        More
      </button>
    </nav>
  );
}

export default function AdminLayout() {
  const { username, role, hasPermission, logout } = useAuth();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [devOpen, setDevOpen] = useState(false);
  const location = useLocation();
  const navRef = useRef(null);

  // Close the drawer automatically on route change (covers link clicks,
  // including ones not caught by the delegated click handler below).
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    document.body.style.overflow = drawerOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [drawerOpen]);

  if (username === undefined) return <Loading />;
  if (username === null) return <Navigate to="/login" replace />;

  function closeDrawerOnLinkClick(e) {
    if (e.target.closest("a")) setDrawerOpen(false);
  }

  return (
    <OrderAlertProvider>
    <div className="admin-shell">
      {drawerOpen && <div className="admin-drawer-overlay" onClick={() => setDrawerOpen(false)} aria-hidden="true" />}
      <aside className={`admin-sidebar${drawerOpen ? " open" : ""}`}>
        <div className="brand">
          <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="admin-logo-chip">
              <img src={logoImg} alt="Aaiji Nursery" />
            </span>
            Aaiji Nursery
          </span>
          <button type="button" className="admin-drawer-close" aria-label="Close menu" onClick={() => setDrawerOpen(false)}>
            &times;
          </button>
        </div>
        <nav className="admin-nav" ref={navRef} onClick={closeDrawerOnLinkClick}>
          <NavGroup items={NAV} hasPermission={hasPermission} />
          <NavGroup heading="Accounting" items={ACCOUNTING_NAV} hasPermission={hasPermission} />
          <NavGroup heading="Employees & Labour" items={WORKFORCE_NAV} hasPermission={hasPermission} />
          <NavGroup heading="Delivery Management" items={DELIVERY_NAV} hasPermission={hasPermission} />
          <NavGroup heading="Communications" items={COMMUNICATIONS_NAV} hasPermission={hasPermission} />
          {role === "developer" && (
            <>
              {/* Desktop: plain heading, always-expanded list (unchanged).
                  Mobile (<=768px, see admin.css): becomes a collapsible
                  toggle -- .admin-dev-toggle/.admin-dev-group are display:none
                  above that breakpoint, so desktop renders exactly as before. */}
              <div className="admin-nav-heading admin-dev-toggle-label-desktop">Developer</div>
              <button
                type="button"
                className="admin-dev-toggle"
                aria-expanded={devOpen}
                onClick={() => setDevOpen((v) => !v)}
              >
                Developer
                <ChevronIcon />
              </button>
              <div className={`admin-dev-group${devOpen ? " open" : ""}`}>
                {DEVELOPER_NAV.map((item) => (
                  <NavLink key={item.to} to={item.to} end={item.end}>
                    {item.label}
                  </NavLink>
                ))}
              </div>
            </>
          )}
        </nav>
        <div className="admin-drawer-footer">
          <span style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
            <span className="admin-logo-chip" style={{ borderRadius: "50%", background: "rgba(255,255,255,0.15)", color: "#fff", fontWeight: 700 }}>
              {(username || "A").charAt(0).toUpperCase()}
            </span>
            <span style={{ color: "#fff", fontSize: "0.85rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {username}
            </span>
          </span>
          <a
            href="#"
            style={{ color: "#f3a6a0", fontSize: "0.85rem", fontWeight: 600, flexShrink: 0 }}
            onClick={(e) => {
              e.preventDefault();
              if (confirm("Are you sure you want to log out?")) logout();
            }}
          >
            Log out
          </a>
        </div>
      </aside>
      <div className="admin-main">
        <div className="admin-topbar">
          <button type="button" className="admin-hamburger" aria-label="Open menu" onClick={() => setDrawerOpen(true)}>
            <HamburgerIcon />
          </button>
          <strong>Admin Dashboard</strong>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <OrderAlertBell />
            <span className="admin-topbar-username" style={{ color: "var(--color-text-muted)", fontSize: "0.88rem" }}>
              Signed in as {username}
            </span>
          </div>
        </div>
        <div className="admin-content">
          <ErrorBoundary moduleName="Admin">
            <Outlet />
          </ErrorBoundary>
        </div>
      </div>
      <AdminBottomNav onMore={() => setDrawerOpen(true)} />
    </div>
    </OrderAlertProvider>
  );
}
