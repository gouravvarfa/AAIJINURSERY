import { useDocumentTitle } from "../hooks/useDocumentTitle";

export default function PrivacyPolicy() {
  useDocumentTitle("Privacy Policy | Aaiji Nursery");

  return (
    <>
      <section className="page-hero">
        <div className="container">
          <h1>Privacy Policy</h1>
          <p>How Shree Aaiji High Tech Nursery collects, uses, and protects your information.</p>
        </div>
      </section>

      <section className="section">
        <div className="container" style={{ maxWidth: 820 }}>
          <p>
            Last updated: October 2026. This Privacy Policy explains what information Shree Aaiji
            High Tech Nursery ("we", "us", "our") collects from visitors and customers of{" "}
            <a href="https://shreeaaijihightechnursery.in">shreeaaijihightechnursery.in</a>, how we
            use it, and the choices you have.
          </p>

          <h2>1. Information We Collect</h2>
          <ul className="feature-list">
            <li>
              <strong>Account information:</strong> name, email address, and mobile number when you
              register, sign in, or sign in with Google.
            </li>
            <li>
              <strong>Order and delivery information:</strong> delivery address, mobile number, and
              order history, used to process and deliver your orders.
            </li>
            <li>
              <strong>Payment information:</strong> payments are processed by Razorpay; we do not
              store your card, UPI, or bank details on our own servers.
            </li>
            <li>
              <strong>Communications:</strong> messages you send us via Contact, Enquiry forms, or
              WhatsApp, and order-related notifications we send you via WhatsApp or email.
            </li>
            <li>
              <strong>Google Sign-In:</strong> if you choose "Sign in with Google", we receive your
              name and email address from Google to create or match your account. We never receive
              or see your Google password.
            </li>
          </ul>

          <h2>2. How We Use Your Information</h2>
          <ul className="feature-list">
            <li>To create and manage your customer account</li>
            <li>To process, deliver, and provide support for your orders</li>
            <li>To send order updates, delivery notifications, and invoices via WhatsApp or email</li>
            <li>To respond to enquiries and customer support requests</li>
            <li>To improve our website, products, and services</li>
          </ul>

          <h2>3. Sharing of Information</h2>
          <p>
            We do not sell your personal information to third parties. We share information only
            with service providers who help us run the business -- payment processing (Razorpay),
            WhatsApp Business messaging providers, and delivery logistics -- strictly to the extent
            needed to provide our services to you.
          </p>

          <h2>4. Cookies and Sessions</h2>
          <p>
            We use a session cookie to keep you signed in while you browse and shop. We do not use
            third-party advertising or tracking cookies.
          </p>

          <h2>5. Data Security</h2>
          <p>
            We take reasonable technical and organisational measures to protect your information,
            including encrypted connections (HTTPS) and access-controlled admin systems.
          </p>

          <h2>6. Your Choices</h2>
          <p>
            You can update your account details from your profile at any time, or request deletion
            of your account and associated data by contacting us using the details below.
          </p>

          <h2>7. Contact Us</h2>
          <p>
            For any privacy-related questions or requests, contact us at{" "}
            <a href="mailto:hightechaaijinursery@gmail.com">hightechaaijinursery@gmail.com</a> or
            via the <a href="/contact">Contact page</a>.
          </p>
        </div>
      </section>
    </>
  );
}
