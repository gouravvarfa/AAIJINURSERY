import { createContext, useContext, useEffect, useState } from "react";
import { api } from "../api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [session, setSession] = useState(undefined); // undefined = loading, null = logged out

  useEffect(() => {
    api
      .get("/auth/me")
      .then((data) => setSession(data))
      .catch(() => setSession(null));
  }, []);

  async function login(identifier, password) {
    const data = await api.post("/auth/login", { identifier, password });
    setSession(data);
    return data;
  }

  async function loginWithGoogle(credential) {
    const data = await api.post("/auth/google", { credential });
    setSession(data);
    return data;
  }

  async function register(payload) {
    const customer = await api.post("/customer/register", payload);
    const data = { type: "customer", id: customer.id, name: customer.name, email: customer.email };
    setSession(data);
    return data;
  }

  async function logout() {
    await api.post("/auth/logout");
    setSession(null);
  }

  const ADMIN_TYPES = new Set(["admin", "developer", "super_access", "custom"]);
  const isAdminType = Boolean(session) && ADMIN_TYPES.has(session.type);
  const username = session === undefined ? undefined : isAdminType ? session.username : null;
  const role = isAdminType ? session.type : null;
  // { [module]: { VIEW: bool, CREATE: bool, ... } } from /auth/me and /auth/login,
  // computed server-side by app/permissions.py -- the frontend never decides
  // access on its own, only reflects what the backend already enforces.
  const permissions = isAdminType ? session.permissions || {} : {};

  function hasPermission(module, action = "VIEW") {
    if (role === "developer") return true; // Developer's own tools are never matrix-governed
    return Boolean(permissions[module]?.[action]);
  }

  return (
    <AuthContext.Provider value={{ session, username, role, permissions, hasPermission, login, loginWithGoogle, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
