const CSRF_ERROR = "A valid CSRF token is required for this request.";

export class ApiError extends Error {
  constructor(status, message, options) { super(message, options); this.status = status; }
}

export function errorMessage(status, body) {
  if (status === 401) return "Your session expired or was revoked. Please sign in again.";
  if (status === 403) return "You do not have permission, or your session security token changed. Please retry.";
  if (status >= 500) return "BudBot could not complete the request. Check the backend and try again.";
  if (Array.isArray(body?.detail)) return body.detail.map(item =>
    `${(item.loc || []).filter(part => part !== "body").join(".")}: ${String(item.msg || "Invalid value")}`
  ).join("\n").slice(0, 1500);
  return typeof body?.detail === "string" ? body.detail.slice(0, 1500) : `Request failed (${status}).`;
}

export class AdminClient {
  constructor(fetcher = globalThis.fetch, locks = globalThis.navigator?.locks) {
    this.fetcher = fetcher;
    this.locks = locks;
    this.session = null;
    this.queue = Promise.resolve();
  }
  // Serialize same-origin tabs where Web Locks is available. Always renew CSRF
  // immediately before a foreground write. Never poll /me or store tokens.
  exclusive(operation) {
    const run = () => this.locks ? this.locks.request("budbot-admin-session", operation) : operation();
    const next = this.queue.then(run, run);
    this.queue = next.catch(() => {});
    return next;
  }
  async request(path, options = {}) {
    if (!path.startsWith("/api/v1/")) throw new Error("Invalid administrative API path.");
    let pending, response;
    try {
      // Browser-native fetch requires Window as its receiver, not AdminClient.
      // Keep synchronous setup errors separate from rejected network requests.
      pending = this.fetcher.call(globalThis, path, {
        ...options, credentials: "same-origin", cache: "no-store",
        signal: AbortSignal.timeout(30_000),
        headers: { "Content-Type": "application/json", ...options.headers },
      });
    } catch (cause) {
      throw new ApiError(0, "BudBot could not start the request. Reload the page or update your browser; if it persists, report a browser client error.", { cause });
    }
    try {
      response = await pending;
    } catch (cause) {
      throw new ApiError(0, "Connection failed or timed out. Check BudBot and reload settings before retrying; a saved change may already have completed.", { cause });
    }
    let body = null;
    if (response.status !== 204) {
      try { body = await response.json(); }
      catch { if (response.ok) throw new ApiError(502, "BudBot returned an unreadable response. Reload settings before retrying."); }
    }
    if (!response.ok) {
      if (response.status === 401) this.session = null;
      const error = new ApiError(response.status, errorMessage(response.status, body));
      error.csrfChanged = response.status === 403 && body?.detail === CSRF_ERROR;
      throw error;
    }
    return body;
  }
  async current() {
    this.session = await this.request("/api/v1/auth/me");
    return this.session;
  }
  restore() { return this.exclusive(() => this.current()); }
  login(email, password) {
    return this.exclusive(async () => {
      try {
        this.session = await this.request("/api/v1/auth/login", {
          method: "POST", body: JSON.stringify({ email, password }),
        });
        return this.session;
      } catch (error) {
        if (error.status === 401) error.message = "Invalid email or password.";
        throw error;
      }
    });
  }
  mutate(path, method, payload) {
    return this.exclusive(async () => {
      // Also refresh permissions/memberships; authorization is still server-side.
      await this.current();
      const options = () => ({ method,
        headers: { "X-CSRF-Token": this.session.csrf_token },
        ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
      });
      try { return await this.request(path, options()); }
      catch (error) {
        if (!error.csrfChanged) throw error;
        // Bounded recovery for other clients/older browsers. A CSRF rejection
        // occurs before mutation, so retrying it cannot duplicate a saved change.
        await this.current();
        return this.request(path, options());
      }
    });
  }
  async logout() {
    await this.mutate("/api/v1/auth/logout", "POST");
    this.session = null;
  }
  can(businessId, permission) {
    return this.session?.businesses.some(item => item.business_id === businessId &&
      item.permissions?.includes(permission)) || false;
  }
}
