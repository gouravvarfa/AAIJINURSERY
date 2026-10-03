import { Link } from "react-router-dom";
import { useSettings } from "../context/SettingsContext";

export default function Footer() {
  const settings = useSettings();

  return (
    <footer className="site-footer">
      <div className="container">
        <div className="footer-grid">
          <div>
            <h4>{settings.business_name || "Aaiji Nursery"}</h4>
            <p>{settings.tagline}</p>
            {(settings.facebook_url || settings.instagram_url || settings.whatsapp) && (
              <div className="footer-social">
                {settings.facebook_url && (
                  <a href={settings.facebook_url} target="_blank" rel="noopener noreferrer" aria-label="Facebook">
                    f
                  </a>
                )}
                {settings.instagram_url && (
                  <a href={settings.instagram_url} target="_blank" rel="noopener noreferrer" aria-label="Instagram">
                    &#128247;
                  </a>
                )}
                {settings.whatsapp && (
                  <a href={`https://wa.me/${settings.whatsapp}`} target="_blank" rel="noopener noreferrer" aria-label="WhatsApp">
                    &#128172;
                  </a>
                )}
              </div>
            )}
          </div>
          <div>
            <h4>Explore</h4>
            <ul>
              <li><Link to="/plants">Plants</Link></li>
              <li><Link to="/services">Services</Link></li>
              <li><Link to="/pricing">Pricing</Link></li>
              <li><Link to="/gallery">Gallery</Link></li>
              <li><Link to="/blog">Blog</Link></li>
            </ul>
          </div>
          <div>
            <h4>Support</h4>
            <ul>
              <li><Link to="/faqs">FAQs</Link></li>
              <li><Link to="/testimonials">Testimonials</Link></li>
              <li><Link to="/contact">Contact Us</Link></li>
              <li><Link to="/about">About Us</Link></li>
            </ul>
          </div>
          <div>
            <h4>Contact</h4>
            <ul>
              <li>{settings.phone}</li>
              <li>{settings.email}</li>
              <li>{settings.address}</li>
            </ul>
          </div>
        </div>
        <div className="footer-bottom">
          &copy; {new Date().getFullYear()} {settings.business_name || "Aaiji Nursery"}. All
          rights reserved. &middot; <Link to="/privacy-policy">Privacy Policy</Link> &middot;{" "}
          <Link to="/terms-of-service">Terms of Service</Link>
        </div>
      </div>
    </footer>
  );
}
