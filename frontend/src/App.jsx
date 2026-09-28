import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import PublicLayout from "./components/PublicLayout";
import ErrorBoundary from "./components/ErrorBoundary";
import Home from "./pages/Home";
import About from "./pages/About";
import Plants from "./pages/Plants";
import PlantDetail from "./pages/PlantDetail";
import Cart from "./pages/Cart";
import Wishlist from "./pages/Wishlist";
import Checkout from "./pages/Checkout";
import Account from "./pages/Account";
import Addresses from "./pages/Addresses";
import Orders from "./pages/Orders";
import OrderDetail from "./pages/OrderDetail";
import Services from "./pages/Services";
import Pricing from "./pages/Pricing";
import FAQs from "./pages/FAQs";
import Contact from "./pages/Contact";
import Testimonials from "./pages/Testimonials";
import Gallery from "./pages/Gallery";
import Blog from "./pages/Blog";
import BlogPost from "./pages/BlogPost";
import LoginModal from "./components/LoginModal";
import Signup from "./pages/Signup";
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
import NotFound from "./pages/NotFound";
import AdminLayout from "./admin/AdminLayout";
import AdminDashboard from "./admin/pages/Dashboard";
import AdminAnalytics from "./admin/pages/Analytics";
import AdminPurchases from "./admin/pages/Purchases";
import AdminOrders from "./admin/pages/Orders";
import AdminOrderDetail from "./admin/pages/OrderDetail";
import AdminCategories from "./admin/pages/Categories";
import AdminPlants from "./admin/pages/Plants";
import AdminServices from "./admin/pages/Services";
import AdminPricingPlans from "./admin/pages/PricingPlans";
import AdminFAQs from "./admin/pages/FAQs";
import AdminTestimonials from "./admin/pages/Testimonials";
import AdminReviews from "./admin/pages/Reviews";
import AdminGallery from "./admin/pages/Gallery";
import AdminBlog from "./admin/pages/Blog";
import AdminInquiries from "./admin/pages/Inquiries";
import AdminCustomers from "./admin/pages/Customers";
import AdminCustomerDetail from "./admin/pages/CustomerDetail";
import AdminCustomerLogs from "./admin/pages/CustomerLogs";
import AdminSettings from "./admin/pages/Settings";
import AdminAdmins from "./admin/pages/Admins";
import AdminActivityLog from "./admin/pages/ActivityLog";
import AdminSystemInfo from "./admin/pages/SystemInfo";
import AdminSessions from "./admin/pages/Sessions";
import AdminLoginAttempts from "./admin/pages/LoginAttempts";
import AdminRolesPermissions from "./admin/pages/RolesPermissions";
import SystemHealthOverview from "./admin/pages/system-health/Overview";
import SystemHealthActiveErrors from "./admin/pages/system-health/ActiveErrors";
import SystemHealthErrorHistory from "./admin/pages/system-health/ErrorHistory";
import SystemHealthFunctionMonitoring from "./admin/pages/system-health/FunctionMonitoring";
import SystemHealthSystemLogs from "./admin/pages/system-health/SystemLogs";
import LiveLogs from "./admin/pages/developer/LiveLogs";
import AccountingOverview from "./admin/pages/accounting/Overview";
import AccountingSalesOrders from "./admin/pages/accounting/SalesOrders";
import AccountingSalesOrderDetail from "./admin/pages/accounting/SalesOrderDetail";
import AccountingInvoices from "./admin/pages/accounting/Invoices";
import AccountingInvoiceDetail from "./admin/pages/accounting/InvoiceDetail";
import AccountingParties from "./admin/pages/accounting/Parties";
import AccountingPartyProfile from "./admin/pages/accounting/PartyProfile";
import AccountingChartOfAccounts from "./admin/pages/accounting/ChartOfAccounts";
import AccountingTaxRates from "./admin/pages/accounting/TaxRates";
import AccountingPurchaseOrders from "./admin/pages/accounting/PurchaseOrders";
import AccountingPurchaseOrderDetail from "./admin/pages/accounting/PurchaseOrderDetail";
import AccountingBills from "./admin/pages/accounting/Bills";
import AccountingBillDetail from "./admin/pages/accounting/BillDetail";
import AccountingExpenses from "./admin/pages/accounting/Expenses";
import AccountingExpenseDetail from "./admin/pages/accounting/ExpenseDetail";
import AccountingEmployees from "./admin/pages/accounting/Employees";
import AccountingReports from "./admin/pages/accounting/Reports";
import AccountingRoles from "./admin/pages/accounting/Roles";
import CommunicationsDashboard from "./admin/pages/communications/Dashboard";
import CommunicationsSendMessage from "./admin/pages/communications/SendMessage";
import CommunicationsTemplates from "./admin/pages/communications/Templates";
import CommunicationsEventMap from "./admin/pages/communications/EventTemplateMap";
import CommunicationsHistory from "./admin/pages/communications/MessageHistory";
import CommunicationsSettings from "./admin/pages/communications/Settings";
import LabourDashboard from "./admin/pages/labour/Dashboard";
import LabourEmployees from "./admin/pages/labour/Employees";
import LabourEmployeeDetail from "./admin/pages/labour/EmployeeDetail";
import LabourLabour from "./admin/pages/labour/Labour";
import LabourLabourDetail from "./admin/pages/labour/LabourDetail";
import LabourTodaysWork from "./admin/pages/labour/TodaysWork";
import LabourAttendance from "./admin/pages/labour/Attendance";
import LabourPayroll from "./admin/pages/labour/Payroll";
import LabourPayments from "./admin/pages/labour/Payments";
import LabourAdvances from "./admin/pages/labour/Advances";
import DeliveryDashboard from "./admin/pages/delivery/Dashboard";
import DeliveryDeliveries from "./admin/pages/delivery/Deliveries";
import DeliveryCreate from "./admin/pages/delivery/DeliveryCreate";
import DeliveryDetail from "./admin/pages/delivery/DeliveryDetail";
import DeliveryDrivers from "./admin/pages/delivery/Drivers";
import DeliveryDriverDetail from "./admin/pages/delivery/DriverDetail";
import DeliveryVehicles from "./admin/pages/delivery/Vehicles";
import DeliveryVehicleDetail from "./admin/pages/delivery/VehicleDetail";
import DeliveryTrips from "./admin/pages/delivery/Trips";
import DeliveryFuel from "./admin/pages/delivery/Fuel";
export default function App() {
  const location = useLocation();
  // When navigation to /login carries a backgroundLocation (set by the Navbar's
  // Login button and by the auth-guard redirects), render the routes as if we're
  // still on that background page, then overlay LoginModal on top of it below —
  // this is what makes login feel like a modal instead of a page navigation.
  const backgroundLocation = location.state?.backgroundLocation;

  return (
    <>
      <Routes location={backgroundLocation || location}>
        <Route element={<PublicLayout />}>
          <Route path="/" element={<Home />} />
          <Route path="/about" element={<About />} />
          <Route path="/plants" element={<Plants />} />
          <Route path="/plants/:slug" element={<PlantDetail />} />
          <Route path="/cart" element={<Cart />} />
          <Route path="/wishlist" element={<Wishlist />} />
          <Route
            path="/checkout"
            element={
              <ErrorBoundary moduleName="Checkout">
                <Checkout />
              </ErrorBoundary>
            }
          />
          <Route path="/account" element={<Account />} />
          <Route path="/addresses" element={<Addresses />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/orders/:id" element={<OrderDetail />} />
          <Route path="/services" element={<Services />} />
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/faqs" element={<FAQs />} />
          <Route path="/contact" element={<Contact />} />
          <Route path="/testimonials" element={<Testimonials />} />
          <Route path="/gallery" element={<Gallery />} />
          <Route path="/blog" element={<Blog />} />
          <Route path="/blog/:slug" element={<BlogPost />} />
        </Route>
        {/* Fallback full-page auth screens for direct URL visits/refreshes, i.e. when
            there's no background page to overlay. Mirrored below as overlay routes. */}
        <Route path="/login" element={<LoginModal />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/admin/login" element={<Navigate to="/login" replace />} />
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<AdminDashboard />} />
          <Route path="analytics" element={<AdminAnalytics />} />
          <Route path="orders" element={<AdminOrders />} />
          <Route path="orders/:id" element={<AdminOrderDetail />} />
          <Route path="categories" element={<AdminCategories />} />
          <Route path="plants" element={<AdminPlants />} />
          <Route path="purchases" element={<AdminPurchases />} />
          <Route path="services" element={<AdminServices />} />
          <Route path="pricing-plans" element={<AdminPricingPlans />} />
          <Route path="faqs" element={<AdminFAQs />} />
          <Route path="testimonials" element={<AdminTestimonials />} />
          <Route path="reviews" element={<AdminReviews />} />
          <Route path="gallery" element={<AdminGallery />} />
          <Route path="blog" element={<AdminBlog />} />
          <Route path="inquiries" element={<AdminInquiries />} />
          <Route path="customers" element={<AdminCustomers />} />
          <Route path="customers/:id" element={<AdminCustomerDetail />} />
          <Route path="customer-logs" element={<AdminCustomerLogs />} />
          <Route path="settings" element={<AdminSettings />} />
          <Route path="admins" element={<AdminAdmins />} />
          <Route path="developer/activity-log" element={<AdminActivityLog />} />
          <Route path="developer/system-info" element={<AdminSystemInfo />} />
          <Route path="developer/sessions" element={<AdminSessions />} />
          <Route path="developer/login-attempts" element={<AdminLoginAttempts />} />
          <Route path="developer/roles-permissions" element={<AdminRolesPermissions />} />
          <Route path="developer/system-health" element={<SystemHealthOverview />} />
          <Route path="developer/system-health/errors" element={<SystemHealthActiveErrors />} />
          <Route path="developer/system-health/history" element={<SystemHealthErrorHistory />} />
          <Route path="developer/system-health/functions" element={<SystemHealthFunctionMonitoring />} />
          <Route path="developer/system-health/logs" element={<SystemHealthSystemLogs />} />
          <Route path="developer/live-logs" element={<LiveLogs />} />
          <Route path="accounting" element={<ErrorBoundary moduleName="Accounting"><AccountingOverview /></ErrorBoundary>} />
          <Route path="accounting/sales-orders" element={<ErrorBoundary moduleName="Accounting"><AccountingSalesOrders /></ErrorBoundary>} />
          <Route path="accounting/sales-orders/:id" element={<ErrorBoundary moduleName="Accounting"><AccountingSalesOrderDetail /></ErrorBoundary>} />
          <Route path="accounting/invoices" element={<ErrorBoundary moduleName="Accounting"><AccountingInvoices /></ErrorBoundary>} />
          <Route path="accounting/invoices/:id" element={<ErrorBoundary moduleName="Accounting"><AccountingInvoiceDetail /></ErrorBoundary>} />
          <Route path="accounting/parties" element={<ErrorBoundary moduleName="Accounting"><AccountingParties /></ErrorBoundary>} />
          <Route path="accounting/parties/:id" element={<ErrorBoundary moduleName="Accounting"><AccountingPartyProfile /></ErrorBoundary>} />
          <Route path="accounting/chart-of-accounts" element={<ErrorBoundary moduleName="Accounting"><AccountingChartOfAccounts /></ErrorBoundary>} />
          <Route path="accounting/tax-rates" element={<ErrorBoundary moduleName="Accounting"><AccountingTaxRates /></ErrorBoundary>} />
          <Route path="accounting/purchase-orders" element={<ErrorBoundary moduleName="Accounting"><AccountingPurchaseOrders /></ErrorBoundary>} />
          <Route path="accounting/purchase-orders/:id" element={<ErrorBoundary moduleName="Accounting"><AccountingPurchaseOrderDetail /></ErrorBoundary>} />
          <Route path="accounting/bills" element={<ErrorBoundary moduleName="Accounting"><AccountingBills /></ErrorBoundary>} />
          <Route path="accounting/bills/:id" element={<ErrorBoundary moduleName="Accounting"><AccountingBillDetail /></ErrorBoundary>} />
          <Route path="accounting/expenses" element={<ErrorBoundary moduleName="Accounting"><AccountingExpenses /></ErrorBoundary>} />
          <Route path="accounting/expenses/:id" element={<ErrorBoundary moduleName="Accounting"><AccountingExpenseDetail /></ErrorBoundary>} />
          <Route path="accounting/employees" element={<ErrorBoundary moduleName="Accounting"><AccountingEmployees /></ErrorBoundary>} />
          <Route path="accounting/reports" element={<ErrorBoundary moduleName="Accounting"><AccountingReports /></ErrorBoundary>} />
          <Route path="accounting/roles" element={<ErrorBoundary moduleName="Accounting"><AccountingRoles /></ErrorBoundary>} />
          <Route path="communications" element={<ErrorBoundary moduleName="Communications"><CommunicationsDashboard /></ErrorBoundary>} />
          <Route path="communications/send" element={<ErrorBoundary moduleName="Communications"><CommunicationsSendMessage /></ErrorBoundary>} />
          <Route path="communications/templates" element={<ErrorBoundary moduleName="Communications"><CommunicationsTemplates /></ErrorBoundary>} />
          <Route path="communications/event-map" element={<ErrorBoundary moduleName="Communications"><CommunicationsEventMap /></ErrorBoundary>} />
          <Route path="communications/history" element={<ErrorBoundary moduleName="Communications"><CommunicationsHistory /></ErrorBoundary>} />
          <Route path="communications/settings" element={<ErrorBoundary moduleName="Communications"><CommunicationsSettings /></ErrorBoundary>} />
          <Route path="labour" element={<ErrorBoundary moduleName="Labour"><LabourDashboard /></ErrorBoundary>} />
          <Route path="labour/employees" element={<ErrorBoundary moduleName="Labour"><LabourEmployees /></ErrorBoundary>} />
          <Route path="labour/employees/:id" element={<ErrorBoundary moduleName="Labour"><LabourEmployeeDetail /></ErrorBoundary>} />
          <Route path="labour/labour" element={<ErrorBoundary moduleName="Labour"><LabourLabour /></ErrorBoundary>} />
          <Route path="labour/labour/:id" element={<ErrorBoundary moduleName="Labour"><LabourLabourDetail /></ErrorBoundary>} />
          <Route path="labour/todays-work" element={<ErrorBoundary moduleName="Labour"><LabourTodaysWork /></ErrorBoundary>} />
          <Route path="labour/attendance" element={<ErrorBoundary moduleName="Labour"><LabourAttendance /></ErrorBoundary>} />
          <Route path="labour/payroll" element={<ErrorBoundary moduleName="Labour"><LabourPayroll /></ErrorBoundary>} />
          <Route path="labour/payments" element={<ErrorBoundary moduleName="Labour"><LabourPayments /></ErrorBoundary>} />
          <Route path="labour/advances" element={<ErrorBoundary moduleName="Labour"><LabourAdvances /></ErrorBoundary>} />
          <Route path="delivery" element={<ErrorBoundary moduleName="Delivery"><DeliveryDashboard /></ErrorBoundary>} />
          <Route path="delivery/deliveries" element={<ErrorBoundary moduleName="Delivery"><DeliveryDeliveries /></ErrorBoundary>} />
          <Route path="delivery/deliveries/new" element={<ErrorBoundary moduleName="Delivery"><DeliveryCreate /></ErrorBoundary>} />
          <Route path="delivery/deliveries/:id" element={<ErrorBoundary moduleName="Delivery"><DeliveryDetail /></ErrorBoundary>} />
          <Route path="delivery/drivers" element={<ErrorBoundary moduleName="Delivery"><DeliveryDrivers /></ErrorBoundary>} />
          <Route path="delivery/drivers/:id" element={<ErrorBoundary moduleName="Delivery"><DeliveryDriverDetail /></ErrorBoundary>} />
          <Route path="delivery/vehicles" element={<ErrorBoundary moduleName="Delivery"><DeliveryVehicles /></ErrorBoundary>} />
          <Route path="delivery/vehicles/:id" element={<ErrorBoundary moduleName="Delivery"><DeliveryVehicleDetail /></ErrorBoundary>} />
          <Route path="delivery/trips" element={<ErrorBoundary moduleName="Delivery"><DeliveryTrips /></ErrorBoundary>} />
          <Route path="delivery/fuel" element={<ErrorBoundary moduleName="Delivery"><DeliveryFuel /></ErrorBoundary>} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>

      {backgroundLocation && (
        <Routes>
          <Route path="/login" element={<LoginModal />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
        </Routes>
      )}
    </>
  );
}
