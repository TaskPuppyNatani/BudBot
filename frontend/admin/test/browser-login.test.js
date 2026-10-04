import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";

// Optional browser suite: use an already available Playwright/Chromium runtime.
// Native fetch, Web Locks, form validation and HTTP are deliberately not mocked.
const { chromium } = createRequire(import.meta.url)("playwright");
const publicRoot = new URL("../public/", import.meta.url);
const widgetRoot = new URL("../../widget/", import.meta.url);
const account = token => ({ csrf_token: token, user: { email: "owner@example.test" }, businesses: [
  { business_id: "a", display_name: "Fixture business", role: "owner",
    permissions: ["business.read", "business.write", "location.write", "assistant.write", "branding.write"] },
] });

async function fixture(t) {
  const calls = []; const widgetNavigations = []; let token = 0;
  const server = createServer(async (request, response) => {
    const path = new URL(request.url, "http://localhost").pathname;
    if (path === "/favicon.ico") { response.writeHead(204).end(); return; }
    if (path === "/widget/" || path === "/widget/src/embed.js") {
      if (path === "/widget/") widgetNavigations.push({ url: request.url, referer: request.headers.referer || "" });
      response.writeHead(200, { "Content-Type": path.endsWith(".js") ? "text/javascript" : "text/html" });
      response.end(await readFile(new URL(path.endsWith(".js") ? "src/embed.js" : "index.html", widgetRoot))); return;
    }
    if (path.startsWith("/admin/")) {
      const files = { "/admin/": "index.html", "/admin/styles.css": "styles.css",
        "/admin/src/app.js": "src/app.js", "/admin/src/client.js": "src/client.js", "/admin/src/forms.js": "src/forms.js" };
      if (!files[path]) { response.writeHead(404).end(); return; }
      response.writeHead(200, { "Content-Type": path.endsWith(".js") ? "text/javascript" : path.endsWith(".css") ? "text/css" : "text/html",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'" });
      response.end(await readFile(new URL(files[path], publicRoot))); return;
    }
    const call = { path, method: request.method }; calls.push(call);
    const send = (status, body, headers = {}) => {
      call.status = status;
      response.writeHead(status, { "Content-Type": "application/json", ...headers });
      response.end(JSON.stringify(body));
    };
    if (path === "/api/v1/sessions" || path === "/api/v1/sessions/customer-fixture/widget") {
      call.hasAdminCookie = Boolean(request.headers.cookie?.includes("budbot_admin_session"));
      call.hasCsrfHeader = Boolean(request.headers["x-csrf-token"]);
      call.businessId = request.headers["x-budbot-business-id"];
      if (path === "/api/v1/sessions") {
        let text = ""; for await (const chunk of request) text += chunk;
        call.payload = JSON.parse(text);
        send(201, { id: "customer-fixture", age_gate_status: "NOT_REQUIRED" }); return;
      }
      send(200, { business: { display_name: "Fixture business" }, assistant: { display_name: "Fixture assistant" },
        compliance: { requires_age_gate: false }, locations: [{ id: "one", display_name: "Main" }, { id: "two", display_name: "Second" }] }); return;
    }
    if (path === "/api/v1/auth/login" && request.method === "POST") {
      let text = ""; for await (const chunk of request) text += chunk;
      const input = JSON.parse(text);
      if (input.email !== "owner@example.test" || input.password !== "synthetic owner passphrase") {
        send(401, { detail: "Invalid email or password." }); return;
      }
      send(200, account(String(++token)), { "Set-Cookie": "budbot_admin_session=fixture; Path=/; HttpOnly; SameSite=Lax" }); return;
    }
    if (!request.headers.cookie?.includes("budbot_admin_session=fixture")) {
      send(401, { detail: "Authentication is required." }); return;
    }
    if (path === "/api/v1/auth/me") { send(200, account(String(++token))); return; }
    if (path === "/api/v1/auth/logout" && request.method === "POST") {
      if (request.headers["x-csrf-token"] !== String(token)) {
        send(403, { detail: "A valid CSRF token is required for this request." }); return;
      }
      send(204, null, { "Set-Cookie": "budbot_admin_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax" }); return;
    }
    if (path === "/api/v1/businesses/a" && request.method === "PATCH") {
      // Make a concurrent /me rotation observable while a write is in flight.
      const submittedToken = request.headers["x-csrf-token"];
      await new Promise(resolve => setTimeout(resolve, 40));
      send(submittedToken === String(token) ? 200 : 403,
        submittedToken === String(token) ? {} : { detail: "A valid CSRF token is required for this request." }); return;
    }
    if (path === "/api/v1/businesses/a") {
      send(200, { id: "a", display_name: "Fixture business", industry: "general_retail", active: true, default_timezone: "UTC" }); return;
    }
    if (path.endsWith("/assistant")) { send(200, { display_name: "Fixture assistant", greeting: "Hello", fallback_message: "Ask staff", enabled: true }); return; }
    if (path.endsWith("/locations")) { send(200, []); return; }
    if (path.endsWith("/compliance-profile")) { send(200, { profile_id: "general_retail", requires_age_gate: false }); return; }
    send(404, { detail: "Unknown fixture route." });
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const browser = await chromium.launch({ headless: true,
    ...(process.env.BUDBOT_TEST_BROWSER_EXECUTABLE ? { executablePath: process.env.BUDBOT_TEST_BROWSER_EXECUTABLE } : {}),
  });
  t.after(() => browser.close());
  const context = await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  const pageErrors = []; page.on("pageerror", error => pageErrors.push(error.message));
  const origin = `http://127.0.0.1:${server.address().port}`;
  await page.goto(`${origin}/admin/`);
  await page.waitForFunction(() => document.querySelector('button[type="submit"]')?.disabled === false);
  assert.deepEqual(calls, [{ path: "/api/v1/auth/me", method: "GET", status: 401 }],
    `Anonymous startup must reach HTTP; UI: ${await page.locator('[role="status"]').textContent()}`);
  return { context, page, calls, pageErrors, origin, widgetNavigations };
}

async function signIn(page, password = "synthetic owner passphrase") {
  await page.getByLabel("Email", { exact: true }).fill("owner@example.test");
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}

test("anonymous restore leaves a usable form and native fetch issues login then dashboard reads", async t => {
  const { page, calls, pageErrors } = await fixture(t);
  assert.equal(await page.getByLabel("Email", { exact: true }).isEnabled(), true);
  assert.equal(await page.getByLabel("Password", { exact: true }).isEnabled(), true);
  await signIn(page);
  await page.getByRole("heading", { name: "Business settings", exact: true }).waitFor();
  assert.deepEqual(calls.slice(0, 2), [
    { path: "/api/v1/auth/me", method: "GET", status: 401 },
    { path: "/api/v1/auth/login", method: "POST", status: 200 },
  ]);
  assert.ok(calls.some(call => call.path === "/api/v1/businesses/a" && call.status === 200));
  assert.equal(await page.getByRole("button", { name: "Save changes", exact: true }).isEnabled(), true);
  assert.deepEqual(pageErrors, []);
});

test("invalid credentials issue a POST and remain retryable without page reload", async t => {
  const { page, calls, pageErrors } = await fixture(t);
  await signIn(page, "synthetic wrong passphrase");
  await page.getByText("Invalid email or password.", { exact: true }).waitFor();
  assert.equal(await page.getByLabel("Password", { exact: true }).inputValue(), "");
  assert.equal(await page.getByRole("button", { name: "Sign in", exact: true }).isEnabled(), true);
  await signIn(page);
  await page.getByRole("heading", { name: "Business settings", exact: true }).waitFor();
  assert.deepEqual(calls.filter(call => call.path.endsWith("/login")).map(call => call.status), [401, 200]);
  assert.deepEqual(pageErrors, []);
});

test("two real tabs preserve Web Lock coordination across CSRF refresh and writes", async t => {
  const { context, page, calls, origin } = await fixture(t);
  await signIn(page);
  await page.getByRole("heading", { name: "Business settings", exact: true }).waitFor();
  const second = await context.newPage(); second.setDefaultTimeout(5000);
  await second.goto(`${origin}/admin/`);
  await second.getByRole("heading", { name: "Business settings", exact: true }).waitFor();
  calls.length = 0;
  const write = tab => tab.evaluate(async () => {
    if (!navigator.locks) throw new Error("This test requires real Web Locks.");
    const { AdminClient } = await import("/admin/src/client.js");
    await new AdminClient().mutate("/api/v1/businesses/a", "PATCH", { display_name: "Fixture business" });
  });
  await Promise.all([write(page), write(second)]);
  assert.deepEqual(calls.map(call => [call.method, call.status]), [["GET", 200], ["PATCH", 200], ["GET", 200], ["PATCH", 200]]);
});

test("sign out refreshes CSRF and returns to an enabled login form", async t => {
  const { page, calls, pageErrors } = await fixture(t);
  await signIn(page);
  await page.getByRole("heading", { name: "Business settings", exact: true }).waitFor();
  calls.length = 0;
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.getByRole("heading", { name: "Sign in to BudBot", exact: true }).waitFor();
  assert.deepEqual(calls.map(call => [call.method, call.path, call.status]), [
    ["GET", "/api/v1/auth/me", 200], ["POST", "/api/v1/auth/logout", 204],
  ]);
  assert.equal(await page.getByRole("button", { name: "Sign in", exact: true }).isEnabled(), true);
  assert.deepEqual(pageErrors, []);
});

test("customer preview opens the selected widget with no opener/referrer or admin API credentials", async t => {
  const { context, page, calls, pageErrors, origin, widgetNavigations } = await fixture(t);
  await signIn(page);
  await page.getByRole("heading", { name: "Business settings", exact: true }).waitFor();
  calls.length = 0;
  const opened = context.waitForEvent("page", { timeout: 2000 }).catch(error => {
    throw new Error(`Preview did not open; browser errors: ${JSON.stringify(pageErrors)}`, { cause: error });
  });
  await page.getByRole("button", { name: "Customer preview", exact: true }).click();
  const preview = await opened;
  await preview.waitForURL(`${origin}/widget/?business_id=a`);
  await preview.getByText("Choose a location to start chatting.", { exact: true }).waitFor();
  assert.notEqual(preview, page);
  assert.equal(await preview.evaluate(() => window.opener), null);
  assert.equal(await preview.evaluate(() => document.referrer), "");
  assert.deepEqual(widgetNavigations, [{ url: "/widget/?business_id=a", referer: "" }]);
  assert.deepEqual(calls.map(call => call.path), ["/api/v1/sessions", "/api/v1/sessions/customer-fixture/widget"]);
  assert.ok(calls.every(call => call.hasAdminCookie === false && call.hasCsrfHeader === false && call.businessId === "a"));
  assert.deepEqual(calls[0].payload, {});
  assert.deepEqual(pageErrors, []);
});
