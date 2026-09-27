import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../api";
import AuthShell from "../components/AuthShell";

export default function ForgotPassword() {
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    try {
      await api.post("/customer/forgot-password", { email });
    } catch {
      // ignore - always show the same generic confirmation
    } finally {
      setLoading(false);
      setSent(true);
    }
  }

  return (
    <AuthShell title="Forgot Password" subtitle="We'll email you a link to reset it.">
      {sent ? (
        <>
          <div className="alert alert-success">
            If that email is registered, we've sent a password reset link to it.
            Don't see it in your inbox? Please check your Spam or Promotions folder too.
          </div>
          <p className="auth-modal-footer-text">
            <Link to="/login" state={location.state}>Back to login</Link>
          </p>
        </>
      ) : (
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              className="form-control"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <button className="btn btn-primary btn-block" disabled={loading}>
            {loading ? "Sending..." : "Send Reset Link"}
          </button>
          <p className="auth-modal-footer-text">
            <Link to="/login" state={location.state}>Back to login</Link>
          </p>
        </form>
      )}
    </AuthShell>
  );
}
