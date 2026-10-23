import test from "node:test";
import assert from "node:assert/strict";
import { AdminApp } from "../public/src/app.js";
import { ApiError } from "../public/src/client.js";

// A dependency-free DOM harness executes the actual form/event handlers. Setting
// innerHTML is forbidden so business-controlled content must use text nodes.
class Element {
  constructor(tag, document) { this.tagName = tag; this.ownerDocument = document; this.children = []; this.listeners = {}; this.attributes = {}; this.value = ""; this.checked = false; this.files = []; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return (this.text || "") + this.children.map(child => child.textContent).join(""); }
  set innerHTML(value) { throw new Error("HTML injection in admin UI"); }
  append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  remove() { this.parent.children.splice(this.parent.children.indexOf(this), 1); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  dispatch(type) { for (const callback of this.listeners[type] || []) callback({ target: this, preventDefault() {} }); }
}
const all = node => [node, ...node.children.flatMap(all)];
const button = (root, text) => all(root).find(node => node.tagName === "button" && node.textContent === text);
const field = (root, text) => all(root).find(node => node.tagName === "label" && node.children[0]?.textContent === text)?.children[1];
const form = (root, title) => all(root).find(node => node.tagName === "form" && node.children[0]?.textContent === title);
function setup(permissions = ["business.read", "business.write", "location.write", "assistant.write", "branding.write", "faq.read", "faq.write", "audit.read"]) {
  const document = { createElement: tag => new Element(tag, document) };
  const root = document.createElement("main"); const writes = []; const opened = [];
  const account = { user: { email: "owner@example.test" }, businesses: [{ business_id: "a", display_name: "<script>business</script>", role: "owner", permissions }, { business_id: "b", display_name: "Second business", role: "viewer", permissions: ["business.read", "faq.read"] }] };
  const business = { id: "a", display_name: "<script>business</script>", industry: "general_retail", active: true, default_timezone: "UTC", products_enabled: true, promotions_enabled: true };
  const assistant = { display_name: "Assistant", greeting: "Hello", fallback_message: "Ask staff", enabled: true };
  const location = { id: "loc", display_name: "Main", active: true, hours: [], timezone: "UTC" };
  const faqs = { a: [], b: [{ id: "faq-b", question: "Second tenant question", answer: "Second tenant answer", location_id: null, enabled: true, is_public: true }] };
  const api = {
    session: null, restore: async function () { this.session = structuredClone(account); return this.session; },
    login: async function () { this.session = structuredClone(account); return this.session; }, logout: async function () { this.session = null; },
    can: function (id, permission) { return this.session?.businesses.find(item => item.business_id === id)?.permissions.includes(permission) || false; },
    request: async path => {
      const id = path.split("/")[4];
      if (path.endsWith("/faqs")) return structuredClone(faqs[id]);
      if (path.includes("/audit?")) return { items: [], next_offset: null };
      if (path.endsWith("assistant-override")) return null;
      if (path.endsWith("effective-assistant")) return structuredClone(assistant);
      if (path.includes("compliance-profile/locations")) return { status: "resolved", location_active: true, profile: { profile_id: "general_retail" } };
      if (path.endsWith("compliance-profile")) return { profile_id: "general_retail", requires_age_gate: false };
      if (path.endsWith("/assistant")) return structuredClone(assistant);
      if (path.includes("/locations?")) return [structuredClone(location)];
      return { ...structuredClone(business), id: path.split("/").at(-1) };
    },
    mutate: async (path, method, payload) => {
      writes.push({ path, method, payload });
      if (path.includes("/faqs")) {
        const entries = faqs[path.split("/")[4]];
        if (method === "POST") entries.push({ id: `faq-${entries.length}`, ...payload });
        else Object.assign(entries.find(item => item.id === path.split("/").at(-1)), payload);
        return {};
      }
      Object.assign(business, payload); return { id: "loc" };
    },
  };
  const app = new AdminApp(root, api, { confirm: () => true, open: (...args) => opened.push(args) });
  return { root, app, api, writes, opened };
}

test("dashboard loads authorized businesses, renders hostile strings as text and saves flags", async () => {
  const { root, app, writes } = setup(); await app.start();
  assert.equal(field(root, "Business").children.length, 2);
  assert.ok(root.textContent.includes("<script>business</script>"));
  field(root, "products enabled").checked = false;
  field(root, "promotions enabled").checked = false;
  form(root, "Business settings").dispatch("submit"); await app.task;
  assert.equal(writes[0].payload.products_enabled, false);
  assert.equal(writes[0].payload.promotions_enabled, false);
  assert.equal(app.busy, false);
  assert.equal(button(root, "Save changes").disabled, false);
});

test("permission controls use server permissions for each area", async () => {
  for (const permissions of [["business.read"], ["business.read", "location.write"], ["business.read", "business.write", "location.write", "assistant.write", "branding.write"]]) {
    const { root, app, writes } = setup(permissions); await app.start();
    assert.equal(button(root, "Save changes").disabled, !permissions.includes("business.write"));
    form(root, "Business settings").dispatch("submit"); if (app.task) await app.task;
    assert.equal(writes.length, permissions.includes("business.write") ? 1 : 0);
    button(root, "Locations").dispatch("click");
    assert.equal(button(root, "Save location and hours").disabled, !permissions.includes("location.write"));
    button(root, "Assistant").dispatch("click");
    assert.equal(button(root, "Save explicit override changes").disabled, !permissions.includes("assistant.write"));
    button(root, "Branding").dispatch("click");
    assert.equal(button(root, "Save branding").disabled, !permissions.includes("branding.write"));
  }
});

test("opening an override form does not create overrides and no-op submission does not write", async () => {
  const { root, app, writes } = setup(); await app.start();
  button(root, "Assistant").dispatch("click");
  form(root, "Location assistant overrides").dispatch("submit"); await app.task;
  assert.equal(writes.length, 0); assert.match(app.message, /No override changes/);
  assert.equal(app.busy, false);
  const override = form(root, "Location assistant overrides");
  field(override, "greeting").value = "override";
  const values = all(override).filter(node => node.tagName === "label" && node.children[0]?.textContent === "Override value");
  values[1].children[1].value = "Local greeting";
  override.dispatch("submit"); await app.task;
  assert.deepEqual(writes[0].payload, { greeting: "Local greeting" });
});

test("location hours submit structured states and deactivation requires confirmation", async () => {
  const { root, app, writes } = setup(); await app.start();
  button(root, "Locations").dispatch("click");
  const locationForm = form(root, "Location settings");
  const states = all(locationForm).filter(node => node.tagName === "label" && node.children[0]?.textContent === "State");
  states[0].children[1].value = "closed";
  locationForm.dispatch("submit"); await app.task;
  assert.deepEqual(writes[0].payload.hours, [{ day_of_week: 0, is_closed: true }]);
  app.confirm = () => false;
  button(root, "Deactivate location").dispatch("click"); await app.task;
  assert.equal(writes.length, 1);
  app.confirm = () => true;
  button(root, "Deactivate location").dispatch("click"); await app.task;
  assert.equal(writes[1].path, "/api/v1/businesses/a/locations/loc/deactivate");
});

test("401 clears authenticated view; 403 retains edits and releases busy controls", async () => {
  const { root, app, api } = setup(); await app.start();
  api.mutate = async () => { throw new ApiError(403, "Permission denied."); };
  field(root, "Business name").value = "Keep my edit";
  form(root, "Business settings").dispatch("submit"); await app.task;
  assert.equal(field(root, "Business name").value, "Keep my edit");
  assert.equal(button(root, "Save changes").disabled, false);
  api.mutate = async () => { api.session = null; throw new ApiError(401, "Your session expired. Please sign in again."); };
  form(root, "Business settings").dispatch("submit"); await app.task;
  assert.ok(button(root, "Sign in")); assert.equal(button(root, "Sign in").disabled, false);
  assert.match(app.message, /sign in again/);
});

test("customer preview passes only business selection and business switching clears old scope", async () => {
  const { root, app, opened } = setup(); await app.start();
  button(root, "Customer preview").dispatch("click");
  assert.deepEqual(opened[0], ["/widget/?business_id=a", "_blank", "noopener,noreferrer"]);
  field(root, "Business").value = "b"; field(root, "Business").dispatch("change"); await app.task;
  assert.equal(app.businessId, "b"); assert.equal(button(root, "Save changes").disabled, true);
  button(root, "Customer preview").dispatch("click");
  assert.deepEqual(opened[1], ["/widget/?business_id=b", "_blank", "noopener,noreferrer"]);
});

test("customer preview uses the browser-global receiver and offers guidance without a window handle", async () => {
  const { root, app } = setup(); await app.start();
  app.open = function (url, target, features) {
    assert.equal(this, globalThis);
    assert.deepEqual([url, target, features], ["/widget/?business_id=a", "_blank", "noopener,noreferrer"]);
    return null;
  };
  button(root, "Customer preview").dispatch("click");
  assert.match(app.message, /If no tab opened, allow popups/);
  assert.equal(app.failed, false);
  assert.equal(app.busy, false);
  assert.ok(root.textContent.includes(app.message));
  app.open = () => ({});
  button(root, "Customer preview").dispatch("click");
  assert.equal(app.message, "Customer preview opened in a separate tab.");
});

test("customer preview opening exceptions show safe retryable errors", async () => {
  const { root, app } = setup(); await app.start();
  app.open = () => { throw new Error("synthetic private browser detail"); };
  button(root, "Customer preview").dispatch("click");
  assert.match(app.message, /Could not open customer preview.*allow popups/i);
  assert.ok(!app.message.includes("private browser detail"));
  assert.equal(app.status.attributes["data-error"], "true");
  assert.equal(button(root, "Customer preview").disabled, false);
});

test("login clears passwords and logout returns to a usable sign-in form", async () => {
  const { root, app, api } = setup();
  api.restore = async () => { throw new ApiError(401, "Please sign in."); };
  await app.start(); const password = field(root, "Password"); password.value = "temporary passphrase";
  field(root, "Email").value = "owner@example.test";
  form(root, "Sign in to BudBot").dispatch("submit"); await app.task;
  assert.equal(password.value, ""); assert.ok(button(root, "Sign out"));
  button(root, "Sign out").dispatch("click"); await app.task;
  assert.equal(api.session, null); assert.ok(button(root, "Sign in")); assert.equal(app.busy, false);
});

test("initial network failure shows a usable sign-in form and visible recovery error", async () => {
  const { root, app, api } = setup();
  api.restore = async () => { throw new ApiError(0, "Connection failed. Check BudBot and try again."); };
  await app.start();
  assert.ok(field(root, "Email"));
  assert.equal(button(root, "Sign in").disabled, false);
  assert.equal(app.busy, false);
  assert.match(root.textContent, /Connection failed/);
});

test("successful reload clears a prior mutation security error and red status", async () => {
  const { root, app, api } = setup(); await app.start();
  api.mutate = async () => { throw new ApiError(403, "Security token changed. Please retry."); };
  form(root, "Business settings").dispatch("submit"); await app.task;
  assert.equal(app.failed, true);
  assert.equal(app.status.attributes["data-error"], "true");
  button(root, "Reload settings").dispatch("click"); await app.task;
  assert.equal(app.failed, false);
  assert.equal(app.status.attributes["data-error"], "false");
  assert.equal(app.message, "Reloaded current settings.");
  assert.equal(button(root, "Save changes").disabled, false);
});

test("failed initial settings load retains authorized selection for retry", async () => {
  const { root, app, api } = setup(); const request = api.request;
  api.request = async () => { throw new ApiError(500, "Settings unavailable. Please retry."); };
  await app.start();
  assert.equal(app.busy, false);
  assert.ok(button(root, "Sign out"));
  assert.equal(field(root, "Business").disabled, false);
  assert.match(root.textContent, /Settings unavailable/);
  api.request = request;
  field(root, "Business").value = "a";
  field(root, "Business").dispatch("change"); await app.task;
  assert.equal(app.businessId, "a");
  assert.ok(button(root, "Save changes"));
});

test("FAQ forms create, edit, scope and disable public customer entries as text", async () => {
  const { root, app, writes } = setup(); await app.start();
  button(root, "FAQs").dispatch("click"); await app.task;
  assert.ok(root.textContent.includes("No FAQs yet."));
  field(root, "Question").value = "<img onerror=alert(1)> parking?";
  field(root, "Answer").value = "First answer";
  form(root, "New FAQ").dispatch("submit"); await app.task;
  assert.equal(writes[0].path, "/api/v1/businesses/a/faqs");
  assert.equal(writes[0].method, "POST");
  assert.equal(writes[0].payload.location_id, null);
  assert.ok(root.textContent.includes("<img onerror=alert(1)> parking?"));
  assert.equal(all(root).filter(node => node.tagName === "img").length, 0);
  button(root, "Edit FAQ").dispatch("click");
  assert.equal(field(root, "Answer").value, "First answer");
  field(root, "Answer").value = "Local answer";
  field(root, "FAQ scope").value = "loc";
  field(root, "FAQ enabled").checked = false;
  field(root, "Public to customers").checked = false;
  form(root, "Edit FAQ").dispatch("submit"); await app.task;
  assert.equal(writes[1].method, "PATCH");
  assert.equal(writes[1].payload.location_id, "loc");
  assert.equal(writes[1].payload.enabled, false);
  assert.equal(writes[1].payload.is_public, false);
  assert.match(root.textContent, /Main · Disabled · Non-public/);
  assert.equal(app.busy, false);
});

test("FAQ validation errors retain edits and release controls; reload and relogin preserve saved data", async () => {
  const { root, app, api } = setup(); await app.start();
  button(root, "FAQs").dispatch("click"); await app.task;
  field(root, "Question").value = "Parking?"; field(root, "Answer").value = "Original";
  form(root, "New FAQ").dispatch("submit"); await app.task;
  button(root, "Edit FAQ").dispatch("click");
  const mutate = api.mutate;
  api.mutate = async () => { throw new ApiError(409, "An enabled public FAQ with this question already exists in this scope."); };
  field(root, "Answer").value = "Keep this edit";
  form(root, "Edit FAQ").dispatch("submit"); await app.task;
  assert.equal(field(root, "Answer").value, "Keep this edit");
  assert.match(app.message, /already exists/);
  assert.equal(button(root, "Save FAQ").disabled, false);
  api.mutate = mutate;
  button(root, "Reload settings").dispatch("click"); await app.task;
  assert.ok(root.textContent.includes("Original"));
  button(root, "Sign out").dispatch("click"); await app.task;
  assert.deepEqual(app.faqs, []); assert.equal(app.auditPage, null);
  form(root, "Sign in to BudBot").dispatch("submit"); await app.task;
  assert.ok(root.textContent.includes("Original"));
});

test("business switching clears FAQ state immediately, including during a failed load", async () => {
  const { root, app, api } = setup(); await app.start();
  button(root, "FAQs").dispatch("click"); await app.task;
  field(root, "Question").value = "First tenant only"; field(root, "Answer").value = "Private first tenant answer";
  form(root, "New FAQ").dispatch("submit"); await app.task;
  const request = api.request; let release;
  api.request = async path => path === "/api/v1/businesses/b" ? new Promise(resolve => { release = () => resolve({ id: "b", display_name: "Second" }); }) : request(path);
  field(root, "Business").value = "b"; field(root, "Business").dispatch("change");
  assert.ok(!root.textContent.includes("Private first tenant answer"));
  assert.deepEqual(app.faqs, []);
  release(); await app.task;
  assert.ok(root.textContent.includes("Second tenant question"));
  assert.ok(!root.textContent.includes("First tenant only"));
  assert.equal(button(root, "Create FAQ").disabled, true);
  api.request = async path => path.endsWith("/faqs") ? Promise.reject(new ApiError(403, "FAQ access denied.")) : request(path);
  field(root, "Business").value = "a"; field(root, "Business").dispatch("change"); await app.task;
  assert.ok(root.textContent.includes("FAQ access denied."));
  assert.ok(!root.textContent.includes("Second tenant answer"));
});

test("FAQ and audit permissions gate reads and writes independently", async () => {
  for (const permissions of [["business.read"], ["business.read", "faq.read"]]) {
    const { root, app, api, writes } = setup(permissions); await app.start();
    const calls = []; const request = api.request;
    api.request = async path => { calls.push(path); return request(path); };
    button(root, "FAQs").dispatch("click"); await app.task;
    if (permissions.includes("faq.read")) {
      assert.equal(button(root, "Create FAQ").disabled, true);
      form(root, "New FAQ").dispatch("submit");
    } else assert.match(root.textContent, /do not have permission/);
    assert.equal(writes.length, 0);
    button(root, "Audit History").dispatch("click"); await app.task;
    assert.match(root.textContent, /do not have permission/);
    assert.ok(!calls.some(path => path.includes("/audit")));
    assert.equal(calls.length, permissions.includes("faq.read") ? 1 : 0);
  }
});

test("audit history is read-only text, handles empty history and paginates within one business", async () => {
  const { root, app, api, writes } = setup(); await app.start();
  button(root, "Audit History").dispatch("click"); await app.task;
  assert.match(root.textContent, /No audit events/);
  const request = api.request;
  const calls = [];
  api.request = async path => {
    if (!path.includes("/audit?")) return request(path);
    calls.push(path);
    return { items: [{ event_type: "admin.faq.updated", created_at: "2026-01-01T00:00:00Z", actor_user_id: "actor-id", resource_type: "faq", resource_id: "faq-id",
      details: { changed_fields: "<script>untrusted</script>" } }], next_offset: path.endsWith("offset=0") ? 25 : null };
  };
  button(root, "Reload settings").dispatch("click"); await app.task;
  assert.ok(root.textContent.includes("<script>untrusted</script>"));
  assert.ok(root.textContent.includes("actor-id"));
  assert.equal(all(root).filter(node => node.tagName === "form").length, 0);
  button(root, "Older events").dispatch("click"); await app.task;
  assert.ok(calls[1].endsWith("offset=25"));
  button(root, "Newest events").dispatch("click"); await app.task;
  assert.ok(calls[2].endsWith("offset=0"));
  field(root, "Business").value = "b"; field(root, "Business").dispatch("change"); await app.task;
  assert.ok(!root.textContent.includes("actor-id"));
  assert.equal(app.auditPage, null);
  assert.match(root.textContent, /do not have permission/);
  assert.equal(writes.length, 0);
});

test("audit load authorization errors are actionable and expired sessions clear both panels", async () => {
  const { root, app, api } = setup(); await app.start();
  const request = api.request;
  api.request = async path => {
    if (path.includes("/audit?")) throw new ApiError(403, "Audit access denied.");
    return request(path);
  };
  button(root, "Audit History").dispatch("click"); await app.task;
  assert.match(root.textContent, /Audit access denied/);
  assert.equal(app.busy, false);
  api.request = async () => { api.session = null; throw new ApiError(401, "Please sign in again."); };
  button(root, "Reload settings").dispatch("click"); await app.task;
  assert.ok(button(root, "Sign in"));
  assert.deepEqual(app.faqs, []); assert.equal(app.auditPage, null);
});

test("provider configuration keeps credentials write-only and preserves them on ordinary saves", async () => {
  const { root, app, api, writes } = setup(["business.read", "provider.read", "provider.write"]);
  const profile = { configured: true, provider: "openrouter", model: "sample/model", enabled: false, tool_calling: false, base_url: null, credential_configured: true };
  const request = api.request;
  api.request = async path => path.endsWith("/provider") ? structuredClone(profile) : request(path);
  api.mutate = async (path, method, payload) => {
    writes.push({ path, method, payload });
    if (path.endsWith("/credential")) profile.credential_configured = method !== "DELETE";
    else Object.assign(profile, payload);
    return structuredClone(profile);
  };
  await app.start(); button(root, "AI Provider").dispatch("click"); await app.task;
  assert.match(root.textContent, /Credential configured: Yes/);
  assert.equal(field(root, "New API key").value, "");
  field(root, "Model identifier").value = "another/model";
  form(root, "Provider configuration").dispatch("submit"); await app.task;
  assert.ok(!("credential" in writes[0].payload));
  assert.equal(profile.credential_configured, true);
  field(root, "Provider").value = "openai_compatible"; field(root, "Provider").dispatch("change");
  assert.equal(field(root, "Backend-reachable base URL").disabled, false);
  assert.equal(field(root, "Backend-reachable base URL").required, true);
  assert.match(root.textContent, /backend container/);
  field(root, "Provider").value = "anthropic"; field(root, "Provider").dispatch("change");
  assert.equal(field(root, "Backend-reachable base URL").disabled, true);
  const input = field(root, "New API key"); input.value = "synthetic-provider-test";
  form(root, "Replace provider credential").dispatch("submit"); await app.task;
  assert.equal(input.value, ""); assert.equal(field(root, "New API key").value, "");
  assert.ok(!root.textContent.includes("synthetic-provider-test"));
  assert.ok(!root.textContent.includes("Test Connection"));
  button(root, "Remove credential and disable AI").dispatch("click"); await app.task;
  assert.equal(writes.at(-1).method, "DELETE");
  assert.match(root.textContent, /Credential configured: No/);
});

test("browser confirmation receiver is preserved and credential removal honors cancellation", async () => {
  const { root, api, writes } = setup(["business.read", "provider.read", "provider.write"]);
  const profile = { configured: true, provider: "openrouter", model: "test/model", enabled: true, credential_configured: true };
  const request = api.request; const prompts = []; let confirmed = false;
  api.request = async path => path.endsWith("/provider") ? structuredClone(profile) : request(path);
  api.mutate = async (path, method) => { writes.push({ path, method }); profile.enabled = false; profile.credential_configured = false; };
  const app = new AdminApp(root, api, { confirm: function (message) {
    assert.equal(this, globalThis, "Native Window.confirm requires the browser-global receiver");
    prompts.push(message); return confirmed;
  } });
  await app.start();
  app.dirty = true;
  assert.equal(app.discard(), false);
  app.dirty = false;
  button(root, "AI Provider").dispatch("click"); await app.task;
  button(root, "Remove credential and disable AI").dispatch("click"); await app.task;
  assert.equal(writes.length, 0, "Cancellation must not send DELETE");
  assert.equal(profile.credential_configured, true);
  confirmed = true;
  button(root, "Remove credential and disable AI").dispatch("click"); await app.task;
  assert.deepEqual(writes, [{ path: "/api/v1/businesses/a/provider/credential", method: "DELETE" }]);
  assert.equal(prompts.filter(message => message.includes("provider credential")).length, 2);
  assert.match(root.textContent, /Credential configured: No/);
});
