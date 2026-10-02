import { Navigate, NavLink, Outlet } from "react-router-dom";
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
  { to: "/admin/admins", label: "Admins", module: "users_roles" },
];

const DEVELOPER_NAV = [
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

export default function AdminLayout() {
  const { username, role, hasPermission, logout } = useAuth();

  if (username === undefined) return <Loading />;
  if (username === null) return <Navigate to="/login" replace />;

  return (
    <OrderAlertProvider>
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <div className="brand">
          <span className="admin-logo-chip">
            <img src={logoImg} alt="Aaiji Nursery" />
          </span>
          Aaiji Nursery
        </div>
        <nav className="admin-nav">
          <NavGroup items={NAV} hasPermission={hasPermission} />
          <NavGroup heading="Accounting" items={ACCOUNTING_NAV} hasPermission={hasPermission} />
          <NavGroup heading="Employees & Labour" items={WORKFORCE_NAV} hasPermission={hasPermission} />
          <NavGroup heading="Delivery Management" items={DELIVERY_NAV} hasPermission={hasPermission} />
          <NavGroup heading="Communications" items={COMMUNICATIONS_NAV} hasPermission={hasPermission} />
          {role === "developer" && (
            <>
              <div className="admin-nav-heading">Developer</div>
              {DEVELOPER_NAV.map((item) => (
                <NavLink key={item.to} to={item.to} end={item.end}>
                  {item.label}
                </NavLink>
              ))}
            </>
          )}
          <div className="logout-btn">
            <a
              href="#"
              onClick={(e) => {
                e.preventDefault();
                if (confirm("Are you sure you want to log out?")) logout();
              }}
            >
              Log Out
            </a>
          </div>
        </nav>
      </aside>
      <div className="admin-main">
        <div className="admin-topbar">
          <strong>Admin Dashboard</strong>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <OrderAlertBell />
            <span style={{ color: "var(--color-text-muted)", fontSize: "0.88rem" }}>
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
    </div>
    </OrderAlertProvider>
  );
}
