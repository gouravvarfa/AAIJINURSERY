import { useRef, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useCart } from "../context/CartContext";
import { useWishlist } from "../context/WishlistContext";
import AuthShell from "../components/AuthShell";
import GoogleSignInButton from "../components/GoogleSignInButton";

export default function Signup() {
  const { session, register, loginWithGoogle } = useAuth();
  const { resumePendingAction } = useCart();
  const { resumePendingAction: resumeWishlistPendingAction } = useWishlist();
  const navigate = useNavigate();
  const location = useLocation();
  const [form, setForm] = useState({ name: "", email: "", mobile: "", password: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  // Once handleSubmit decides where to navigate, this permanently suppresses the
  // "already logged in" redirect below — otherwise unrelated re-renders triggered
  // by CartContext (e.g. its cart refresh effect firing after session changes)
  // can re-run that redirect and overwrite our own in-flight navigate() call.
  const navigatedRef = useRef(false);
  const submittingRef = useRef(false);

  if (session === null) {
    // not logged in, show the form below
  } else if (session && !navigatedRef.current) {
    const isAdminType = session.type === "admin" || session.type === "developer";
    return <Navigate to={isAdminType ? "/admin" : "/"} replace />;
  }

  async function afterAuth() {
    navigatedRef.current = true;
    const resumed = await resumePendingAction();
    await resumeWishlistPendingAction();
    if (resumed?.navigateTo) {
      navigate(resumed.navigateTo, { state: resumed.state, replace: true });
    } else {
      navigate(location.state?.from || "/", { replace: true });
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (submittingRef.current) return;
    submittingRef.current = true;
    setLoading(true);
    setError("");
    try {
      await register(form);
      await afterAuth();
    } catch (err) {
      setError(err.message || "Unable to create account. Please try again.");
    } finally {
      submittingRef.current = false;
      setLoading(false);
    }
  }

  async function handleGoogleCredential(credential) {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setLoading(true);
    setError("");
    try {
      await loginWithGoogle(credential);
      await afterAuth();
    } catch (err) {
      setError(err.message || "Google sign-in failed. Please try again.");
    } finally {
      submittingRef.current = false;
      setLoading(false);
    }
  }

  return (
    <AuthShell title="Create Account" subtitle="Join Aaiji Nursery to start shopping.">
      {error && <div className="alert alert-error">{error}</div>}
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="name">Name</label>
          <input
            id="name"
            className="form-control"
            required
            autoFocus
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          />
        </div>
        <div className="form-group">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            className="form-control"
            required
            value={form.email}
            onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
          />
        </div>
        <div className="form-group">
          <label htmlFor="mobile">Mobile</label>
          <input
            id="mobile"
            className="form-control"
            value={form.mobile}
            onChange={(e) => setForm((f) => ({ ...f, mobile: e.target.value }))}
          />
        </div>
        <div className="form-group">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            className="form-control"
            required
            value={form.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
          />
        </div>
        <button className="btn btn-primary btn-block" disabled={loading}>
          {loading ? "Creating account..." : "Sign Up"}
        </button>
      </form>

      <div className="auth-divider">
        <span>or</span>
      </div>
      <GoogleSignInButton onCredential={handleGoogleCredential} onError={(err) => setError(err.message)} />

      <p className="auth-modal-footer-text">
        Already have an account? <Link to="/login" state={location.state}>Login</Link>
      </p>
    </AuthShell>
  );
}
