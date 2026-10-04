import test from "node:test";
import assert from "node:assert/strict";
import { AdminClient, ApiError } from "../public/src/client.js";

const account = token => ({ csrf_token: token, user: { email: "owner@example.test" }, businesses: [
  { business_id: "a", role: "owner", permissions: ["business.read", "business.write"] },
  { business_id: "b", role: "viewer", permissions: ["business.read"] },
] });
const response = (status, body) => ({ status, ok: status < 400, json: async () => body });

test("login/logout and writes use same-origin cookies, fresh CSRF and no persisted credentials", async () => {
  const calls = []; let token = 0;
  const api = new AdminClient(async (path, options) => {
    calls.push({ path, ...options });
    if (path.endsWith("/me") || path.endsWith("/login")) return response(200, account(`token-${++token}`));
    return response(204, null);
  }, null);
  await api.login("owner@example.test", "hidden passphrase");
  assert.equal(api.can("a", "business.write"), true);
  assert.equal(api.can("b", "business.write"), false);
  assert.equal(api.can("arbitrary-uuid", "business.read"), false);
  await api.mutate("/api/v1/businesses/a", "PATCH", { products_enabled: false });
  assert.deepEqual(calls.slice(1).map(item => item.path), ["/api/v1/auth/me", "/api/v1/businesses/a"]);
  assert.equal(calls.at(-1).headers["X-CSRF-Token"], "token-2");
  await api.logout();
  assert.equal(api.session, null);
  assert.ok(calls.every(item => item.credentials === "same-origin" && item.cache === "no-store"));
  assert.ok(calls.every(item => !("X-BudBot-Business-ID" in item.headers)));
  assert.ok(!("password" in api));
});

test("shared Web Lock prevents /me rotation during another tab's write", async () => {
  let chain = Promise.resolve(); let token = 0; const events = [];
  const locks = { request(name, operation) {
    assert.equal(name, "budbot-admin-session");
    const next = chain.then(operation); chain = next.catch(() => {}); return next;
  } };
  const fetcher = async (path, options) => {
    if (path.endsWith("/me")) { events.push("me"); return response(200, account(String(++token))); }
    await Promise.resolve();
    assert.equal(options.headers["X-CSRF-Token"], String(token));
    events.push("write"); return response(200, {});
  };
  const a = new AdminClient(fetcher, locks); const b = new AdminClient(fetcher, locks);
  await Promise.all([a.mutate("/api/v1/businesses/a", "PATCH", {}), b.mutate("/api/v1/businesses/a", "PATCH", {})]);
  assert.deepEqual(events, ["me", "write", "me", "write"]);
});

test("CSRF recovery is bounded and does not retry permission errors", async () => {
  let gets = 0; let writes = 0;
  const api = new AdminClient(async path => {
    if (path.endsWith("/me")) return response(200, account(String(++gets)));
    writes++;
    return response(403, { detail: "A valid CSRF token is required for this request." });
  }, null);
  await assert.rejects(api.mutate("/api/v1/businesses/a", "PATCH", {}), ApiError);
  assert.equal(writes, 2); assert.equal(gets, 2);
  writes = 0;
  api.fetcher = async path => path.endsWith("/me") ? response(200, account("t")) : (writes++, response(403, { detail: "You do not have permission to perform this action." }));
  await assert.rejects(api.mutate("/api/v1/businesses/a", "PATCH", {}), error => error.status === 403);
  assert.equal(writes, 1);
});

test("a genuine stale-CSRF rejection refreshes once and completes the mutation", async () => {
  let gets = 0; let writes = 0;
  const api = new AdminClient(async (path, options) => {
    if (path.endsWith("/me")) return response(200, account(String(++gets)));
    writes++;
    assert.equal(options.headers["X-CSRF-Token"], String(gets));
    return writes === 1
      ? response(403, { detail: "A valid CSRF token is required for this request." })
      : response(200, { display_name: "Saved after refresh" });
  }, null);
  assert.deepEqual(await api.mutate("/api/v1/businesses/a", "PATCH", {}), { display_name: "Saved after refresh" });
  assert.equal(gets, 2); assert.equal(writes, 2);
});

test("expiry/revocation stops writes and returns an actionable sign-in error", async () => {
  const calls = [];
  const api = new AdminClient(async path => { calls.push(path); return response(401, { detail: "Authentication is required." }); }, null);
  api.session = account("old");
  await assert.rejects(api.mutate("/api/v1/businesses/a", "PATCH", {}), error => error.status === 401 && /sign in again/.test(error.message));
  assert.equal(api.session, null);
  assert.deepEqual(calls, ["/api/v1/auth/me"]);
});

test("raw internal failures are not displayed and the request queue recovers", async () => {
  const api = new AdminClient(async path => path.endsWith("/me") ? response(200, account("t")) : response(500, { detail: "private filesystem path and credential" }), null);
  await assert.rejects(api.mutate("/api/v1/businesses/a", "PATCH", {}), error => !error.message.includes("private"));
  api.fetcher = async () => response(200, account("new"));
  assert.equal((await api.restore()).csrf_token, "new");
  await assert.rejects(api.request("https://other.test/api/v1/auth/login"));
});

test("network failures use a bounded signal and do not strand subsequent requests", async () => {
  let options;
  const api = new AdminClient(async (path, provided) => { options = provided; throw new Error("raw private transport error"); }, null);
  await assert.rejects(api.restore(), error => error.status === 0 && /reload settings/.test(error.message) && !error.message.includes("raw private"));
  assert.ok(options.signal instanceof AbortSignal);
  api.fetcher = async () => response(200, account("recovered"));
  assert.equal((await api.restore()).csrf_token, "recovered");
});

test("anonymous restore and login use the browser-global fetch receiver and recover the queue", async () => {
  const calls = [];
  const api = new AdminClient(function (path, options) {
    assert.equal(this, globalThis);
    calls.push({ path, method: options.method || "GET" });
    return Promise.resolve(path.endsWith("/me")
      ? response(401, { detail: "Authentication is required." })
      : response(200, account("logged-in")));
  }, null);
  await assert.rejects(api.restore(), error => error.status === 401);
  assert.equal((await api.login("owner@example.test", "synthetic passphrase")).csrf_token, "logged-in");
  assert.deepEqual(calls, [{ path: "/api/v1/auth/me", method: "GET" }, { path: "/api/v1/auth/login", method: "POST" }]);
});

test("synchronous browser/setup errors stay safe but retain their diagnostic cause", async () => {
  const cause = new TypeError("synthetic internal browser detail");
  const api = new AdminClient(() => { throw cause; }, null);
  await assert.rejects(api.restore(), error => error instanceof ApiError && error.cause === cause &&
    /browser client error/.test(error.message) && !/Connection failed|internal browser detail/.test(error.message));
  api.fetcher = async () => response(200, account("recovered"));
  assert.equal((await api.restore()).csrf_token, "recovered");
});
