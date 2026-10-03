import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useCart } from "../context/CartContext";
import { useWishlist } from "../context/WishlistContext";
import AuthShell from "./AuthShell";
import GoogleSignInButton from "./GoogleSignInButton";

const REMEMBER_KEY = "rememberedIdentifier";

export default function LoginModal() {
  const { session, login, loginWithGoogle } = useAuth();
  const { resumePendingAction } = useCart();
  const { resumePendingAction: resumeWishlistPendingAction } = useWishlist();
  const navigate = useNavigate();
  const location = useLocation();
  const fromPath = location.state?.from || location.state?.backgroundLocation?.pathname;

  const [form, setForm] = useState(() => ({
    identifier: localStorage.getItem(REMEMBER_KEY) || "",
    password: "",
  }));
  const [remember, setRemember] = useState(() => Boolean(localStorage.getItem(REMEMBER_KEY)));
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  // Once handleSubmit decides where to navigate, this permanently suppresses the
  // "already logged in" redirect below — otherwise unrelated re-renders triggered
  // by CartContext (e.g. its cart refresh effect firing after session changes)
  // can re-run that redirect and overwrite our own in-flight navigate() call.
  const navigatedRef = useRef(false);
  // setLoading(true) doesn't disable the submit button until React commits the
  // re-render, which happens a tick later — a fast double-click (or a synthetic
  // double-fire) can slip two submits through before that. This ref blocks
  // re-entry synchronously, independent of render timing.
  const submittingRef = useRef(false);
  const firstFieldRef = useRef(null);

  useEffect(() => {
    firstFieldRef.current?.focus();
  }, []);

  if (session === null) {
    // not logged in, show the form below
  } else if (session && !navigatedRef.current) {
    const isAdminType = session.type === "admin" || session.type === "developer";
    return <Navigate to={isAdminType ? "/admin" : fromPath || "/"} replace />;
  }

  async function afterLogin(data) {
    navigatedRef.current = true;
    const isAdminType = data.type === "admin" || data.type === "developer";
    if (isAdminType) {
      navigate("/admin", { replace: true });
      return;
    }
    const resumed = await resumePendingAction();
    await resumeWishlistPendingAction();
    if (resumed?.navigateTo) {
      navigate(resumed.navigateTo, { state: resumed.state, replace: true });
    } else {
      navigate(fromPath || "/", { replace: true });
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (submittingRef.current) return;
    submittingRef.current = true;
    setLoading(true);
    setError("");
    try {
      const data = await login(form.identifier, form.password);
      if (remember) localStorage.setItem(REMEMBER_KEY, form.identifier);
      else localStorage.removeItem(REMEMBER_KEY);
      await afterLogin(data);
    } catch (err) {
      setError(err.message || "Invalid email or password.");
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
      const data = await loginWithGoogle(credential);
      await afterLogin(data);
    } catch (err) {
      setError(err.message || "Google sign-in failed. Please try again.");
    } finally {
      submittingRef.current = false;
      setLoading(false);
    }
  }

  return (
    <AuthShell title="Welcome back" subtitle="Sign in to continue to your account.">
      {error && <div className="alert alert-error">{error}</div>}

      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="login-identifier">Email or Username</label>
          <input
            id="login-identifier"
            ref={firstFieldRef}
            className="form-control"
            placeholder="Email or Username"
            required
            value={form.identifier}
            onChange={(e) => setForm((f) => ({ ...f, identifier: e.target.value }))}
          />
        </div>
        <div className="form-group">
          <label htmlFor="login-password">Password</label>
          <input
            id="login-password"
            type="password"
            className="form-control"
            placeholder="Enter your password"
            required
            value={form.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
          />
        </div>

        <div className="auth-modal-row">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
            />
            Remember me
          </label>
          <Link to="/forgot-password" className="auth-modal-link" state={location.state}>
            Forgot password?
          </Link>
        </div>

        <button className="btn btn-primary btn-block" disabled={loading}>
          {loading ? "Signing in..." : "Sign In"}
        </button>
      </form>

      <div className="auth-divider">
        <span>or</span>
      </div>
      <GoogleSignInButton onCredential={handleGoogleCredential} onError={(err) => setError(err.message)} />

      <p className="auth-modal-footer-text">
        New here? <Link to="/signup" state={location.state}>Create an account</Link>
      </p>
    </AuthShell>
  );
}
