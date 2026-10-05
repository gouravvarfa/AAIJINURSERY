const BASE = "/api";

// FastAPI's own request-validation errors (422) send `detail` as an array of
// { loc, msg } objects rather than a plain string like the app's custom
// HTTPException responses do -- without this, new Error(detail) would
// stringify that array into the unreadable "[object Object]".
function formatDetail(detail, fallback) {
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const messages = detail.map((err) => {
      const field = Array.isArray(err.loc) ? err.loc[err.loc.length - 1] : null;
      const msg = err.msg || "Invalid value";
      return typeof field === "string" ? `${field}: ${msg}` : msg;
    });
    return messages.join("; ");
  }
  return fallback;
}

// Attaches `.code`/`.requestId` (from the backend's structured error
// envelope, when present) to a thrown fetch error, without touching the
// existing `.message`/`.status` behavior every current caller relies on.
function annotateError(error, data, res) {
  error.status = res.status;
  error.code = data?.error?.code;
  error.requestId = data?.request_id || res.headers.get("X-Request-ID") || undefined;
  // A 401 while already inside /admin (e.g. the automatic midnight logout,
  // or a session revoked from another tab) means the SPA's in-memory auth
  // state is now stale -- send straight to the login screen instead of
  // leaving the admin stuck on a page that silently stops working.
  if (res.status === 401 && window.location.pathname.startsWith("/admin") && window.location.pathname !== "/admin/login") {
    window.location.href = "/admin/login";
  }
  return error;
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    ...options,
  });

  if (!res.ok) {
    let detail = res.statusText;
    let data = null;
    try {
      data = await res.json();
      detail = formatDetail(data.detail, detail);
    } catch {
      // ignore non-JSON error bodies
    }
    throw annotateError(new Error(detail), data, res);
  }

  if (res.status === 204) return null;
  return res.json();
}

async function requestPaged(path) {
  const res = await fetch(`${BASE}${path}`, { credentials: "include" });

  if (!res.ok) {
    let detail = res.statusText;
    let data = null;
    try {
      data = await res.json();
      detail = formatDetail(data.detail, detail);
    } catch {
      // ignore non-JSON error bodies
    }
    throw annotateError(new Error(detail), data, res);
  }

  const items = await res.json();
  return {
    items,
    total: Number(res.headers.get("X-Total-Count") ?? items.length),
    page: Number(res.headers.get("X-Page") ?? 1),
    pages: Number(res.headers.get("X-Total-Pages") ?? 1),
  };
}

export const api = {
  get: (path) => request(path),
  getPaged: (path) => requestPaged(path),
  post: (path, body) => request(path, { method: "POST", body: JSON.stringify(body) }),
  put: (path, body) => request(path, { method: "PUT", body: JSON.stringify(body) }),
  patch: (path, body) => request(path, { method: "PATCH", body: JSON.stringify(body) }),
  del: (path) => request(path, { method: "DELETE" }),
};
