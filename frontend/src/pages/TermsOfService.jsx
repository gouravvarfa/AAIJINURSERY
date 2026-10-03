import { useDocumentTitle } from "../hooks/useDocumentTitle";

export default function TermsOfService() {
  useDocumentTitle("Terms of Service | Aaiji Nursery");

  return (
    <>
      <section className="page-hero">
        <div className="container">
          <h1>Terms of Service</h1>
          <p>The terms that apply when you use Shree Aaiji High Tech Nursery's website.</p>
        </div>
      </section>

      <section className="section">
        <div className="container" style={{ maxWidth: 820 }}>
          <p>
            Last updated: October 2026. By using{" "}
            <a href="https://shreeaaijihightechnursery.in">shreeaaijihightechnursery.in</a>, placing
            an order, or creating an account, you agree to these terms.
          </p>

          <h2>1. Orders and Payment</h2>
          <p>
            Prices shown are in Indian Rupees (INR) and may change without notice. Orders are
            confirmed only after our team reviews delivery feasibility. Payments are processed
            securely via Razorpay or Cash on Delivery, where available.
          </p>

          <h2>2. Delivery</h2>
          <p>
            Delivery timelines and charges depend on your location and are shown before you confirm
            payment. We'll keep you updated on your order status via WhatsApp/email.
          </p>

          <h2>3. Plant Health and Returns</h2>
          <p>
            We inspect every plant before dispatch. If a plant arrives damaged, contact us within 48
            hours of delivery with photos so we can resolve it -- replacement, refund, or credit, at
            our discretion.
          </p>

          <h2>4. Accounts</h2>
          <p>
            You're responsible for keeping your account credentials (or your linked Google account)
            secure. You may sign in using an email/password you create, or using "Sign in with
            Google" -- both create the same type of customer account.
          </p>

          <h2>5. Acceptable Use</h2>
          <p>
            Please don't misuse the website -- no attempts to disrupt the site, scrape data at scale,
            or submit fraudulent orders.
          </p>

          <h2>6. Changes to These Terms</h2>
          <p>
            We may update these terms from time to time; continued use of the site after a change
            means you accept the updated terms.
          </p>

          <h2>7. Contact Us</h2>
          <p>
            Questions about these terms? Reach us at{" "}
            <a href="mailto:hightechaaijinursery@gmail.com">hightechaaijinursery@gmail.com</a> or
            via the <a href="/contact">Contact page</a>.
          </p>
        </div>
      </section>
    </>
  );
}
