import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import useOrderConfirmations from "../hooks/useOrderConfirmations";

// Global "Your Order Is Confirmed!" popup for logged-in customers. Shown only
// when the backend reports the order as confirmed by the team; closing it
// never changes the order.
export default function OrderConfirmedPopup() {
  const { session } = useAuth();
  const customerId = session && session.type === "customer" ? session.id : null;
  const { current, dismiss } = useOrderConfirmations(customerId);
  const navigate = useNavigate();
  const dialogRef = useRef(null);
  const primaryRef = useRef(null);
  const returnFocusRef = useRef(null);
  const orderId = current?.id;

  useEffect(() => {
    if (!orderId) return undefined;
    returnFocusRef.current = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    primaryRef.current?.focus();

    function onKeyDown(e) {
      if (e.key === "Escape") {
        e.preventDefault();
        dismiss(orderId);
        return;
      }
      if (e.key !== "Tab") return;
      const focusable = dialogRef.current?.querySelectorAll("button, a[href], [tabindex]:not([tabindex='-1'])");
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      if (returnFocusRef.current && document.contains(returnFocusRef.current)) returnFocusRef.current.focus();
    };
  }, [orderId, dismiss]);

  if (!current) return null;

  function viewDetails() {
    dismiss(current.id);
    navigate(`/orders/${current.id}`);
  }

  return createPortal(
    <div className="oc-overlay" onMouseDown={(e) => e.target === e.currentTarget && dismiss(current.id)}>
      <div ref={dialogRef} className="oc-modal" role="dialog" aria-modal="true" aria-labelledby="oc-title" aria-describedby="oc-desc">
        <button type="button" className="oc-close" onClick={() => dismiss(current.id)} aria-label="Close">
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" />
          </svg>
        </button>
        <div className="oc-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="38" height="38">
            <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.8" />
            <path d="M8 12.5l2.7 2.7L16 9.8" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <h2 id="oc-title" className="oc-title">Your Order Is Confirmed!</h2>
        <p id="oc-desc" className="oc-text">Great news! Your order has been confirmed by our team.</p>
        <dl className="oc-card">
          <div className="oc-row">
            <dt>Order number</dt>
            <dd className="oc-number">#ORD-{current.id}</dd>
          </div>
          <div className="oc-row">
            <dt>Order status</dt>
            <dd><span className="oc-badge">Confirmed</span></dd>
          </div>
        </dl>
        <button ref={primaryRef} type="button" className="oc-primary" onClick={viewDetails}>
          View Order Details <span aria-hidden="true">&rarr;</span>
        </button>
        <button type="button" className="oc-secondary" onClick={() => dismiss(current.id)}>
          Continue Shopping
        </button>
        <div className="oc-brand">Shree Aaiji High Tech Nursery</div>
      </div>
    </div>,
    document.body
  );
}
