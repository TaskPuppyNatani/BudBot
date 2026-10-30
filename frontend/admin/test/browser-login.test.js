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
const account = token => ({ csrf_token: token, user: { id: "owner-id", email: "owner@example.test" }, businesses: [
  { business_id: "a", display_name: "Fixture business", role: "owner",
    permissions: ["business.read", "business.write", "location.write", "assistant.write", "branding.write", "faq.read", "faq.write", "audit.read", "provider.read", "provider.write", "membership.manage"] },
] });

async function fixture(t, { commandOutput = () => "<script>safe command output</script>", locations = [] } = {}) {
  const calls = []; const widgetNavigations = []; let token = 0;
  const faqs = []; const audit = []; let faqSequence = 0;
  const members = [{ membership_id: "member-one", user_id: "owner-id", display_name: "Store Owner", email: "owner@example.test", role: "owner", active: true }];
  const invitations = [];
  const provider = { configured: true, provider: "openai_compatible", model: "operator-model",
    base_url: "http://compatible.example/v1", enabled: true, tool_calling: true,
    credential_configured: false, runtime_status: "ready", runtime_code: null };
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
        "/admin/activate.html": "activate.html", "/admin/src/activate.js": "src/activate.js",
        "/admin/src/app.js": "src/app.js", "/admin/src/client.js": "src/client.js", "/admin/src/forms.js": "src/forms.js", "/admin/src/provider.js": "src/provider.js" };
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
    if (path === "/api/v1/invitations/inspect") {
      let text = ""; for await (const chunk of request) text += chunk;
      call.payload = JSON.parse(text);
      if (request.headers.origin !== `http://${request.headers.host}`) { send(403, { detail: "This invitation request must come from BudBot." }); return; }
      send(call.payload.token === "native-invite-token" ? 200 : 404,
        call.payload.token === "native-invite-token" ? { email: "owner@example.test", business_name: "Fixture business", role: "viewer", expires_at: "2026-10-30T00:00:00Z" } : { detail: "This invitation can’t be used. Ask the business owner for a new link." }); return;
    }
    if (path === "/api/v1/invitations/accept/new") {
      let text = ""; for await (const chunk of request) text += chunk; call.payload = JSON.parse(text);
      if (request.headers.origin !== `http://${request.headers.host}`) { send(403, { detail: "This invitation request must come from BudBot." }); return; }
      send(call.payload.token === "native-invite-token" ? 200 : 404, { message: "Your account is ready." }); return;
    }
    if (path === "/api/v1/auth/login" && request.method === "POST") {
      let text = ""; for await (const chunk of request) text += chunk;
      const input = JSON.parse(text);
      if (input.email !== "owner@example.test" || input.password !== "synthetic owner passphrase") {
        send(401, { detail: "Invalid email or password." }); return;
      }
      send(200, account(String(++token)), { "Set-Cookie": "budbot_admin_session=fixture; Path=/; HttpOnly; SameSite=Lax" }); return;
    }
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
    if (!request.headers.cookie?.includes("budbot_admin_session=fixture")) {
      send(401, { detail: "Authentication is required." }); return;
    }
    if (path === "/api/v1/auth/me") { send(200, account(String(++token))); return; }
    if (path === "/api/v1/businesses/a/members" && request.method === "GET") {
      send(200, { members, invitations }); return;
    }
    if (path === "/api/v1/businesses/a/invitations" && request.method === "POST") {
      if (request.headers["x-csrf-token"] !== String(token)) { send(403, { detail: "A valid CSRF token is required for this request." }); return; }
      let text = ""; for await (const chunk of request) text += chunk; call.payload = JSON.parse(text);
      const created = { invitation_id: "invite-one", email: call.payload.email, role: call.payload.role, expires_at: "2026-10-30T00:00:00Z" };
      invitations.push(created); send(201, { ...created, token: "native-invite-token" }); return;
    }
    if (path.startsWith("/api/v1/businesses/a/invitations/") && request.method === "DELETE") {
      call.hasCsrfHeader = request.headers["x-csrf-token"] === String(token);
      if (!call.hasCsrfHeader) { send(403, { detail: "A valid CSRF token is required for this request." }); return; }
      const invitationId = path.split("/").at(-1);
      const index = invitations.findIndex(invite => invite.invitation_id === invitationId);
      if (index < 0) { send(404, { detail: "This invite is no longer available." }); return; }
      invitations.splice(index, 1); call.status = 204; response.writeHead(204).end(); return;
    }
    if (path === "/api/v1/invitations/accept" && request.method === "POST") {
      call.hasAdminCookie = Boolean(request.headers.cookie?.includes("budbot_admin_session=fixture"));
      call.hasCsrfHeader = Boolean(request.headers["x-csrf-token"]);
      if (!request.headers.cookie?.includes("budbot_admin_session=fixture") || request.headers["x-csrf-token"] !== String(token)) { send(403, { detail: "A valid CSRF token is required for this request." }); return; }
      let text = ""; for await (const chunk of request) text += chunk; call.payload = JSON.parse(text);
      if (request.headers.origin !== `http://${request.headers.host}`) { send(403, { detail: "This invitation request must come from BudBot." }); return; }
      send(call.payload.token === "native-invite-token" ? 204 : 404, null); return;
    }
    if (path === "/api/v1/businesses/a/commands") {
      send(200, [{ name: "help", description: "Help", argument_hint: "" }, { name: "preview", description: "Customer preview", argument_hint: "" }]); return;
    }
    if (path === "/api/v1/businesses/a/commands/execute") {
      if (request.headers["x-csrf-token"] !== String(token)) {
        send(403, { detail: "A valid CSRF token is required for this request." }); return;
      }
      let text = ""; for await (const chunk of request) text += chunk;
      call.payload = JSON.parse(text);
      send(200, { canonical_name: "preview", requested_name: "preview", location_id: null,
        output: commandOutput(call.payload.input), preview_url: "/widget/?business_id=a" }); return;
    }
    if (path === "/api/v1/businesses/a/provider" || path.startsWith("/api/v1/businesses/a/provider/")) {
      if (request.method === "GET") { send(200, provider); return; }
      if (request.headers["x-csrf-token"] !== String(token)) {
        send(403, { detail: "A valid CSRF token is required for this request." }); return;
      }
      let text = ""; for await (const chunk of request) text += chunk;
      call.payload = text ? JSON.parse(text) : null;
      if (path.endsWith("/test")) {
        send(200, { code: provider.model === "unknown-model" ? "AI_MODEL_UNAVAILABLE" : "AI_CONNECTION_OK", message: "private upstream marker" }); return;
      }
      if (request.method === "DELETE") Object.assign(provider, { credential_configured: false, enabled: false, runtime_status: "disabled", runtime_code: "AI_DISABLED" });
      else Object.assign(provider, call.payload);
      send(200, provider); return;
    }
    if (path === "/api/v1/businesses/a/audit") { send(200, { items: audit, next_offset: null }); return; }
    const faqPath = "/api/v1/businesses/a/faqs";
    if (path === faqPath || path.startsWith(`${faqPath}/`)) {
      if (request.method === "GET") { send(200, faqs); return; }
      call.hasCsrfHeader = request.headers["x-csrf-token"] === String(token);
      if (!call.hasCsrfHeader) {
        send(403, { detail: "A valid CSRF token is required for this request." }); return;
      }
      if (request.method === "DELETE") {
        const index = faqs.findIndex(item => item.id === path.split("/").at(-1));
        if (index < 0) { send(404, { detail: "FAQ not found" }); return; }
        const [removed] = faqs.splice(index, 1);
        audit.unshift({ id: `audit-${audit.length}`, created_at: "2026-01-01T00:00:00Z",
          actor_user_id: "owner-id", resource_type: "faq", resource_id: removed.id,
          event_type: "admin.faq.deleted", details: { enabled: removed.enabled, is_public: removed.is_public } });
        call.status = 204; response.writeHead(204).end(); return;
      }
      let text = ""; for await (const chunk of request) text += chunk;
      const payload = call.payload = JSON.parse(text);
      const created = request.method === "POST";
      let entry;
      if (created) {
        const id = ++faqSequence === 1 ? "faq-one" : `faq-${faqSequence}`;
        entry = { id, ...payload }; faqs.push(entry);
      } else {
        entry = faqs.find(item => item.id === path.split("/").at(-1));
        if (!entry) { send(404, { detail: "FAQ not found" }); return; }
        Object.assign(entry, payload);
      }
      audit.unshift({ id: `audit-${audit.length}`, created_at: "2026-01-01T00:00:00Z",
        actor_user_id: "owner-id", resource_type: "faq", resource_id: entry.id,
        event_type: created ? "admin.faq.created" : "admin.faq.updated",
        details: { enabled: payload.enabled, is_public: payload.is_public } });
      send(created ? 201 : 200, entry); return;
    }
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
    if (path.endsWith("/assistant-override")) { send(200, null); return; }
    if (path.endsWith("/effective-assistant")) { send(200, { display_name: "Fixture assistant", greeting: "Hello", fallback_message: "Ask staff", enabled: true }); return; }
    if (path.includes("/compliance-profile/locations/")) { send(200, { status: "resolved", location_active: true, profile: { profile_id: "general_retail" } }); return; }
    if (path.endsWith("/assistant")) { send(200, { display_name: "Fixture assistant", greeting: "Hello", fallback_message: "Ask staff", enabled: true }); return; }
    if (path.endsWith("/locations")) { send(200, locations); return; }
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

test("native FAQ editing and audit navigation preserve CSRF, text rendering and reload", async t => {
  const { page, pageErrors, calls } = await fixture(t);
  await signIn(page);
  await page.getByRole("heading", { name: "Business settings", exact: true }).waitFor();
  await page.getByRole("button", { name: "FAQs", exact: true }).click();
  await page.getByText("No FAQs yet.", { exact: true }).waitFor();
  const question = '<img src=x onerror="window.faqInjection=true">';
  await page.getByLabel("Question", { exact: true }).fill(question);
  await page.getByLabel("Answer", { exact: true }).fill("Use the main lot.");
  await page.getByRole("button", { name: "Create FAQ", exact: true }).click();
  await page.getByRole("heading", { name: question, exact: true }).waitFor();
  assert.equal(await page.locator("article img").count(), 0);
  assert.equal(await page.evaluate(() => window.faqInjection), undefined);
  await page.getByRole("button", { name: "Remove from customer answers", exact: true }).waitFor();
  let listConfirmation = "";
  page.once("dialog", async dialog => { listConfirmation = dialog.message(); await dialog.accept(); });
  await page.getByRole("button", { name: "Remove from customer answers", exact: true }).click();
  assert.equal(listConfirmation, "Remove this answer from customer answers? Customers will stop seeing it. The FAQ is kept and can be restored later.");
  await page.getByText("Business-wide · Disabled · Public", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Restore to customer answers", exact: true }).click();
  await page.getByText("Business-wide · Enabled · Public", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Edit FAQ", exact: true }).click();
  const editForm = page.locator("form").filter({ has: page.getByRole("heading", { name: "Edit FAQ", exact: true }) });
  await editForm.getByRole("button", { name: "Remove from customer answers", exact: true }).waitFor();
  await page.getByLabel("Answer", { exact: true }).fill("Use the updated lot.");
  let confirmation = "";
  page.once("dialog", async dialog => { confirmation = dialog.message(); await dialog.accept(); });
  await editForm.getByRole("button", { name: "Remove from customer answers", exact: true }).click();
  assert.equal(confirmation, "Remove this answer from customer answers? Customers will stop seeing it. The FAQ is kept and can be restored later.");
  await page.getByText("Business-wide · Disabled · Public", { exact: true }).waitFor();
  assert.equal(await page.getByLabel("FAQ enabled", { exact: true }).isChecked(), false);
  await editForm.getByRole("button", { name: "Restore to customer answers", exact: true }).click();
  await page.getByText("Business-wide · Enabled · Public", { exact: true }).waitFor();
  assert.equal(await page.getByLabel("FAQ enabled", { exact: true }).isChecked(), true);
  await editForm.getByRole("button", { name: "Remove from customer answers", exact: true }).waitFor();
  await page.getByRole("button", { name: "Save FAQ", exact: true }).click();
  await page.getByText("Business-wide · Enabled · Public", { exact: true }).waitFor();
  assert.ok(calls.some(call => call.path.endsWith("/faqs/faq-one") && call.method === "PATCH" && call.payload.enabled === false));
  assert.ok(calls.some(call => call.path.endsWith("/faqs/faq-one") && call.method === "PATCH" && call.payload.enabled === true));
  await page.getByRole("button", { name: "Reload settings", exact: true }).click();
  await page.getByText("Use the updated lot.", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Audit History", exact: true }).click();
  await page.getByRole("heading", { name: "admin.faq.updated", exact: true }).first().waitFor();
  assert.equal(await page.locator("form").count(), 0);
  assert.equal(await page.getByRole("heading", { name: "admin.faq.updated", exact: true }).count(), 5);
  assert.equal(await page.getByRole("heading", { name: "admin.faq.created", exact: true }).count(), 1);
  assert.ok(calls.some(call => call.path.endsWith("/faqs") && call.method === "POST" && call.status === 201));
  assert.ok(calls.some(call => call.path.endsWith("/faqs/faq-one") && call.method === "PATCH" && call.status === 200));
  assert.deepEqual(pageErrors, []);
});

test("native FAQ deletion refreshes the exact FAQ scope immediately and after reload", async t => {
  const locations = [{ id: "loc", display_name: "Main", active: true }];
  const { page, calls, pageErrors } = await fixture(t, { locations });
  await signIn(page);
  await page.getByRole("heading", { name: "Business settings", exact: true }).waitFor();
  await page.getByRole("button", { name: "FAQs", exact: true }).click();
  await page.getByText("No FAQs yet.", { exact: true }).waitFor();

  const fillNewFaq = async (question, answer, locationId = "") => {
    await page.getByLabel("Question", { exact: true }).fill(question);
    await page.getByLabel("Answer", { exact: true }).fill(answer);
    await page.getByLabel("FAQ scope").selectOption(locationId);
    await page.getByRole("button", { name: "Create FAQ", exact: true }).click();
    await page.getByRole("heading", { name: question, exact: true }).waitFor();
  };
  const confirmDelete = async buttonToClick => {
    let message = "";
    page.once("dialog", async dialog => { message = dialog.message(); await dialog.accept(); });
    await buttonToClick.click();
    assert.equal(message, "Delete this FAQ permanently?\nThis cannot be undone.");
  };

  const question = "Do you have parking?";
  await fillNewFaq(question, "Parking across the business.");
  await fillNewFaq(question, "Parking at Main.", "loc");
  await page.getByRole("heading", { name: question, exact: true }).nth(1).waitFor();
  const faqCards = () => page.locator("article").filter({ has: page.getByRole("heading", { name: question, exact: true }) });
  const businessCard = () => faqCards().filter({ hasText: "Business-wide · Enabled · Public" });
  const locationCard = () => faqCards().filter({ hasText: "Main · Enabled · Public" });
  assert.equal(await faqCards().count(), 2);

  await businessCard().getByRole("button", { name: "Edit FAQ", exact: true }).click();
  const faqReadsBeforeDelete = calls.filter(call => call.path === "/api/v1/businesses/a/faqs" && call.method === "GET").length;
  await confirmDelete(locationCard().getByRole("button", { name: "Delete FAQ", exact: true }));
  await page.getByText("FAQ deleted. The answer for Main was removed.", { exact: true }).waitFor();
  assert.equal(await faqCards().count(), 1, "the same-question business answer remains while the location FAQ disappears");
  assert.equal(await businessCard().count(), 1);
  assert.equal(await locationCard().count(), 0);
  await page.getByText("Parking across the business.", { exact: true }).waitFor();
  assert.equal(await page.getByText("Parking at Main.", { exact: true }).count(), 0);
  assert.equal(await page.getByRole("heading", { name: "Edit FAQ", exact: true }).count(), 1,
    "deleting another scope does not reset the open editor");
  assert.equal(calls.filter(call => call.path === "/api/v1/businesses/a/faqs" && call.method === "GET").length, faqReadsBeforeDelete,
    "the visible list updates without a manual or background reload");

  await page.reload();
  await page.getByRole("heading", { name: "Business settings", exact: true }).waitFor();
  await page.getByRole("button", { name: "FAQs", exact: true }).click();
  await page.getByText("Business-wide · Enabled · Public", { exact: true }).waitFor();
  assert.equal(await faqCards().count(), 1);
  assert.equal(await businessCard().count(), 1);
  assert.equal(await locationCard().count(), 0);
  await page.getByRole("button", { name: "Edit FAQ", exact: true }).click();
  const editForm = page.locator("form").filter({ has: page.getByRole("heading", { name: "Edit FAQ", exact: true }) });
  const faqReadsBeforeEditorDelete = calls.filter(call => call.path === "/api/v1/businesses/a/faqs" && call.method === "GET").length;
  await confirmDelete(editForm.getByRole("button", { name: "Delete FAQ", exact: true }));
  await page.getByText("FAQ deleted. The business-wide answer was removed.", { exact: true }).waitFor();
  await page.getByText("No FAQs yet.", { exact: true }).waitFor();
  assert.equal(await page.getByRole("heading", { name: "Edit FAQ", exact: true }).count(), 0);
  assert.equal(await faqCards().count(), 0);
  assert.equal(calls.filter(call => call.path === "/api/v1/businesses/a/faqs" && call.method === "GET").length, faqReadsBeforeEditorDelete);
  const deletes = calls.filter(call => call.path.startsWith("/api/v1/businesses/a/faqs/") && call.method === "DELETE");
  assert.equal(deletes.length, 2);
  assert.deepEqual(deletes.map(call => call.path), [
    "/api/v1/businesses/a/faqs/faq-2", "/api/v1/businesses/a/faqs/faq-one",
  ]);
  assert.ok(deletes.every(call => call.hasCsrfHeader && call.status === 204));

  await page.reload();
  await page.getByRole("heading", { name: "Business settings", exact: true }).waitFor();
  await page.getByRole("button", { name: "FAQs", exact: true }).click();
  await page.getByText("No FAQs yet.", { exact: true }).waitFor();
  assert.equal(await faqCards().count(), 0, "reload confirms both deleted records remain gone");
  assert.deepEqual(pageErrors, []);
});

test("native provider controls hide irrelevant endpoints and test saved settings with safe results", async t => {
  const { page, calls, pageErrors } = await fixture(t);
  await signIn(page);
  await page.getByRole("heading", { name: "Business settings", exact: true }).waitFor();
  await page.getByRole("button", { name: "AI Provider", exact: true }).click();
  const endpoint = page.getByLabel("Backend-reachable base URL", { exact: true });
  await endpoint.waitFor();
  await page.getByLabel(/^Provider/).selectOption("anthropic");
  assert.equal(await endpoint.isVisible(), false);
  assert.equal(await page.getByRole("button", { name: "Test Connection", exact: true }).isEnabled(), false);
  await page.getByLabel(/^Provider/).selectOption("openai_compatible");
  assert.equal(await endpoint.isVisible(), true);
  await page.getByRole("button", { name: "Save provider configuration", exact: true }).click();
  await page.getByRole("button", { name: "Test Connection", exact: true }).click();
  await page.getByText(/^Connected successfully\./).waitFor();
  assert.ok(calls.some(call => call.path.endsWith("/provider/test") && call.method === "POST" && call.status === 200));
  assert.deepEqual(calls.find(call => call.path.endsWith("/provider/test")).payload, {});
  await page.getByLabel("Model identifier", { exact: true }).fill("unknown-model");
  await page.getByRole("button", { name: "Save provider configuration", exact: true }).click();
  await page.getByRole("button", { name: "Test Connection", exact: true }).click();
  await page.getByText(/^The configured model or API endpoint was not found\./).waitFor();
  assert.ok(!(await page.locator("body").textContent()).includes("private upstream marker"));
  await page.getByRole("button", { name: "Reload settings", exact: true }).click();
  await page.getByText("Not tested", { exact: true }).waitFor();
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByRole("button", { name: "Remove credential and disable AI", exact: true }).click();
  assert.equal(calls.filter(call => call.method === "DELETE").length, 0);
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Remove credential and disable AI", exact: true }).click();
  await page.getByText(/^AI runtime: Disabled\./).waitFor();
  assert.equal(calls.filter(call => call.method === "DELETE").length, 1);
  assert.deepEqual(pageErrors, []);
});

test("native admin command form sends authenticated CSRF input and provides a safe separate preview", async t => {
  const { page, calls, pageErrors } = await fixture(t);
  await signIn(page);
  await page.getByRole("button", { name: "Commands", exact: true }).click();
  await page.getByLabel("Command", { exact: true }).fill("/preview");
  await page.getByRole("button", { name: "Run command", exact: true }).click();
  await page.getByText("<script>safe command output</script>", { exact: true }).waitFor();
  const call = calls.find(call => call.path.endsWith("/commands/execute"));
  assert.equal(call.status, 200); assert.deepEqual(call.payload, { input: "/preview", location_id: null });
  const preview = page.getByRole("link", { name: "Open customer preview", exact: true });
  assert.equal(await preview.getAttribute("href"), "/widget/?business_id=a");
  assert.equal(await preview.getAttribute("target"), "_blank");
  assert.equal(await preview.getAttribute("rel"), "noopener noreferrer");
  assert.equal(await page.getByLabel("Command", { exact: true }).inputValue(), "");
  assert.deepEqual(pageErrors, []);
});

test("command output contains long audit results with working scrollbars at desktop and mobile widths", async t => {
  const id = "01234567-89ab-cdef-0123-456789abcdef";
  const longLine = `${id.repeat(40)} https://example.test/${"path".repeat(200)}`;
  const audit = Array.from({ length: 20 }, (_, index) =>
    `2026-01-01T00:00:00Z | admin.assistant.updated | {"changed_fields":"greeting","location_id":"${id}"}${index === 0 ? longLine : ""}`
  ).join("\n");
  const short = "Assistant enabled: true";
  const { page, pageErrors } = await fixture(t, { commandOutput: input => input === "/audit 20" ? audit : short });
  await signIn(page);
  await page.getByRole("button", { name: "Commands", exact: true }).click();
  for (const viewport of [{ width: 1280, height: 800 }, { width: 360, height: 740 }, { width: 320, height: 640 }]) {
    await page.setViewportSize(viewport);
    await page.getByLabel("Command", { exact: true }).fill("/audit 20");
    await page.getByRole("button", { name: "Run command", exact: true }).click();
    await page.waitForFunction(expected => document.querySelector("pre")?.textContent === expected, audit);
    const output = page.locator("pre");
    const metrics = await output.evaluate(node => {
      const style = getComputedStyle(node);
      const rect = node.getBoundingClientRect();
      const panel = node.closest("section").getBoundingClientRect();
      return { pageWidth: document.documentElement.scrollWidth, viewportWidth: document.documentElement.clientWidth,
        clientWidth: node.clientWidth, scrollWidth: node.scrollWidth, clientHeight: node.clientHeight, scrollHeight: node.scrollHeight,
        maxHeight: style.maxHeight, overflowX: style.overflowX, overflowY: style.overflowY, whiteSpace: style.whiteSpace,
        left: rect.left, right: rect.right, panelLeft: panel.left, panelRight: panel.right };
    });
    assert.ok(metrics.pageWidth <= metrics.viewportWidth + 1, JSON.stringify({ viewport, metrics }));
    assert.ok(metrics.left >= metrics.panelLeft && metrics.right <= metrics.panelRight + 1);
    assert.equal(metrics.whiteSpace, "pre");
    assert.equal(metrics.overflowX, "auto"); assert.equal(metrics.overflowY, "auto");
    assert.ok(Number.isFinite(parseFloat(metrics.maxHeight)) && parseFloat(metrics.maxHeight) <= 480);
    assert.ok(metrics.clientHeight <= parseFloat(metrics.maxHeight) + 1);
    assert.ok(metrics.scrollWidth > metrics.clientWidth && metrics.scrollHeight > metrics.clientHeight);
    assert.equal(await output.textContent(), audit); // Complete output, including all 20 events.
    const scroll = await output.evaluate(node => {
      node.scrollLeft = node.scrollWidth; node.scrollTop = node.scrollHeight;
      return { x: node.scrollLeft, y: node.scrollTop, pageX: window.scrollX };
    });
    assert.ok(scroll.x > 0 && scroll.y > 0); assert.equal(scroll.pageX, 0);
    await page.getByRole("button", { name: "Run command", exact: true }).scrollIntoViewIfNeeded();
    assert.equal(await page.getByRole("button", { name: "Run command", exact: true }).isEnabled(), true);
    assert.equal(await page.getByLabel("Command", { exact: true }).isEnabled(), true);
    assert.ok((await page.getByRole("button", { name: "Run command", exact: true }).boundingBox()).y < (await output.boundingBox()).y);
    await page.getByLabel("Command", { exact: true }).fill("/status");
    await page.getByRole("button", { name: "Run command", exact: true }).click();
    await page.waitForFunction(expected => document.querySelector("pre")?.textContent === expected, short);
    const shortSize = await output.evaluate(node => ({ height: node.clientHeight, scrollHeight: node.scrollHeight, width: node.clientWidth, scrollWidth: node.scrollWidth }));
    assert.ok(shortSize.height < 128 && shortSize.scrollHeight <= shortSize.height + 1);
    assert.ok(shortSize.scrollWidth <= shortSize.width + 1);
  }
  await page.getByRole("button", { name: "Business", exact: true }).click();
  await page.getByRole("heading", { name: "Business settings", exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Save changes", exact: true }).isEnabled(), true);
  assert.deepEqual(pageErrors, []);
});

test("native Team flow creates a one-time link and warns about localhost reachability", async t => {
  const { context, page, calls, origin, pageErrors } = await fixture(t);
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin });
  await signIn(page);
  await page.getByRole("heading", { name: "Business settings", exact: true }).waitFor();
  await page.getByRole("button", { name: "Team", exact: true }).click();
  await page.getByRole("heading", { name: "Add a person", exact: true }).waitFor();
  await page.getByLabel("Email", { exact: true }).fill("new.person@example.test");
  await page.locator("form").filter({ has: page.getByRole("heading", { name: "Add a person", exact: true }) })
    .getByRole("combobox").selectOption("manager");
  await page.getByRole("button", { name: "Create invite", exact: true }).click();
  const link = page.getByLabel("One-time invite link", { exact: true });
  await link.waitFor();
  assert.equal(await link.inputValue(), `${origin}/admin/activate.html#native-invite-token`);
  await page.getByRole("alert").getByText("This address is only available on this computer.").waitFor();
  assert.ok(calls.some(call => call.path === "/api/v1/businesses/a/invitations" && call.method === "POST" && call.payload.email === "new.person@example.test"));
  await page.getByRole("heading", { name: "Pending invitations", exact: true }).waitFor();
  await page.getByText("new.person@example.test", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Copy link", exact: true }).click();
  await page.getByText("Link copied.", { exact: true }).last().waitFor();
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), `${origin}/admin/activate.html#native-invite-token`);
  let confirmation = "";
  page.once("dialog", async dialog => { confirmation = dialog.message(); await dialog.accept(); });
  await page.getByRole("button", { name: "Revoke invite", exact: true }).click();
  assert.equal(confirmation, "Revoke the invitation for new.person@example.test?");
  await page.getByText("No pending invitations.", { exact: true }).waitFor();
  const revokeCall = calls.find(call => call.path === "/api/v1/businesses/a/invitations/invite-one" && call.method === "DELETE");
  assert.ok(revokeCall); assert.equal(revokeCall.hasCsrfHeader, true); assert.equal(revokeCall.status, 204);
  assert.equal(calls.filter(call => call.path === "/api/v1/businesses/a/members" && call.method === "GET").length, 2,
    "Team data is not reloaded after revocation; the pending list updates from the successful delete");
  await page.getByText("Invitation revoked.", { exact: true }).waitFor();
  assert.deepEqual(pageErrors, []);
});

test("activation consumes the fragment locally and accepts a new account", async t => {
  const { page, calls, origin, pageErrors } = await fixture(t);
  await page.goto(`${origin}/admin/activate.html#native-invite-token`);
  await page.getByRole("heading", { name: "Join a BudBot business", exact: true }).waitFor();
  assert.equal(new URL(page.url()).hash, "");
  await page.getByLabel("Your name", { exact: true }).fill("New Teammate");
  await page.getByLabel("Choose a password (at least 12 characters)", { exact: true }).fill("a-safe-new-passphrase");
  await page.getByLabel("Confirm password", { exact: true }).fill("a-safe-new-passphrase");
  await page.getByRole("button", { name: "Create account and join", exact: true }).click();
  await page.getByText("Your account is ready. Go to the BudBot sign-in page to continue.", { exact: true }).waitFor();
  const inspect = calls.find(call => call.path === "/api/v1/invitations/inspect");
  const accepted = calls.find(call => call.path === "/api/v1/invitations/accept/new");
  assert.equal(inspect.payload.token, "native-invite-token");
  assert.equal(accepted.payload.token, "native-invite-token");
  assert.ok(calls.every(call => !call.path.includes("native-invite-token")));
  assert.deepEqual(pageErrors, []);
});

test("activation requires the invited existing account to sign in and explicitly accept", async t => {
  const { page, calls, origin, pageErrors } = await fixture(t);
  await page.goto(`${origin}/admin/activate.html#native-invite-token`);
  await page.getByRole("heading", { name: "Join a BudBot business", exact: true }).waitFor();
  await page.getByLabel("Email", { exact: true }).fill("owner@example.test");
  await page.getByLabel("Password", { exact: true }).fill("synthetic owner passphrase");
  await page.getByRole("button", { name: "Sign in and accept invitation", exact: true }).click();
  await page.getByText("You’ve joined the business. Open the BudBot dashboard to continue.", { exact: true }).waitFor();
  const accepted = calls.find(call => call.path === "/api/v1/invitations/accept");
  assert.equal(accepted.payload.token, "native-invite-token");
  assert.ok(accepted.hasCsrfHeader);
  assert.ok(calls.every(call => !call.path.includes("native-invite-token")));
  assert.deepEqual(pageErrors, []);
});
