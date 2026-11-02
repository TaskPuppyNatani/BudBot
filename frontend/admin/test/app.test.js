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
function setup(permissions = ["business.read", "business.write", "location.write", "assistant.write", "branding.write", "faq.read", "faq.write", "audit.read", "membership.manage"]) {
  const copied = [];
  const document = { createElement: tag => new Element(tag, document) };
  document.defaultView = { location: { origin: "https://budbot.test" }, navigator: { clipboard: { writeText: async value => copied.push(value) } } };
  const root = document.createElement("main"); const writes = []; const opened = [];
  const account = { user: { id: "owner-id", email: "owner@example.test" }, businesses: [{ business_id: "a", display_name: "<script>business</script>", role: "owner", permissions }, { business_id: "b", display_name: "Second business", role: "viewer", permissions: ["business.read", "faq.read"] }] };
  const business = { id: "a", display_name: "<script>business</script>", industry: "general_retail", active: true, default_timezone: "UTC", products_enabled: true, promotions_enabled: true };
  const assistant = { display_name: "Assistant", greeting: "Hello", fallback_message: "Ask staff", enabled: true };
  const location = { id: "loc", display_name: "Main", active: true, hours: [], timezone: "UTC" };
  const faqs = { a: [], b: [{ id: "faq-b", question: "Second tenant question", answer: "Second tenant answer", location_id: null, enabled: true, is_public: true }] };
  const catalog = { a: { products: [], deals: [], currencies: ["USD", "JPY"] }, b: { products: [], deals: [], currencies: ["USD"] } };
  const team = { a: { members: [{ membership_id: "membership-one", user_id: "owner-id", display_name: "Store Owner", email: "owner@example.test", role: "owner", active: true }], invitations: [] }, b: { members: [], invitations: [] } };
  const api = {
    session: null, restore: async function () { this.session = structuredClone(account); return this.session; },
    login: async function () { this.session = structuredClone(account); return this.session; }, logout: async function () { this.session = null; },
    current: async function () { return this.session; },
    can: function (id, permission) { return this.session?.businesses.find(item => item.business_id === id)?.permissions.includes(permission) || false; },
    request: async path => {
      const id = path.split("/")[4];
      if (path.endsWith("/faqs")) return structuredClone(faqs[id]);
      if (path.endsWith("/catalog")) return structuredClone(catalog[id]);
      if (path.endsWith("/members")) return structuredClone(team[id]);
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
      if (path.includes("/catalog/")) {
        const kind = path.split("/")[6]; const rows = catalog[path.split("/")[4]][kind];
        if (method === "POST") { const entry = { id: `${kind}-${rows.length}`, ...structuredClone(payload) }; rows.push(entry); return structuredClone(entry); }
        const entry = rows.find(item => item.id === path.split("/").at(-1));
        Object.assign(entry, structuredClone(payload)); return structuredClone(entry);
      }
      if (path.includes("/faqs")) {
        const entries = faqs[path.split("/")[4]];
        if (method === "POST") entries.push({ id: `faq-${entries.length}`, ...payload });
        else if (method === "DELETE") {
          const index = entries.findIndex(item => item.id === path.split("/").at(-1));
          if (index >= 0) entries.splice(index, 1);
        }
        else Object.assign(entries.find(item => item.id === path.split("/").at(-1)), payload);
        return {};
      }
      if (path.endsWith("/invitations") && method === "POST") {
        return { invitation_id: "invite-one", email: payload.email.toLowerCase(), role: payload.role,
          expires_at: "2026-10-30T00:00:00Z", token: "secret-one-time-token" };
      }
      if (path.includes("/invitations/") && method === "DELETE") {
        const invitations = team[path.split("/")[4]].invitations;
        const index = invitations.findIndex(invite => invite.invitation_id === path.split("/").at(-1));
        if (index >= 0) invitations.splice(index, 1);
        return {};
      }
      if (path.includes("/members/")) {
        const members = team[path.split("/")[4]].members;
        const member = members.find(item => item.membership_id === path.split("/").at(-1));
        if (method === "PATCH") member.role = payload.role;
        if (method === "DELETE") team[path.split("/")[4]].members = [];
      }
      Object.assign(business, payload); return { id: "loc" };
    },
  };
  const app = new AdminApp(root, api, { confirm: () => true, open: (...args) => opened.push(args) });
  return { root, app, api, writes, opened, faqs, team, copied, catalog };
}

test("catalog creates, edits, hides and restores exactly one product immediately using location names", async () => {
  const { root, app, catalog, writes } = setup(); app.tab = "Catalog"; await app.start();
  assert.ok(button(root, "Catalog")); assert.ok(root.textContent.includes("No products yet."));
  field(root, "Product name").value = "<script>tea</script>"; field(root, "Category").value = "Drinks";
  field(root, "Offer at this location").checked = true; field(root, "Price (optional)").value = "12.50";
  form(root, "Add product").dispatch("submit"); await app.task;
  assert.equal(writes[0].path, "/api/v1/businesses/a/catalog/products");
  assert.deepEqual(writes[0].payload.offerings, [{ location_id: "loc", offered: true, price: "12.50", currency: "USD", availability: "unknown" }]);
  assert.ok(root.textContent.includes("<script>tea</script>")); assert.ok(root.textContent.includes("Offered at: Main"));
  button(root, "Edit product").dispatch("click");
  assert.equal(field(root, "Product name").value, "<script>tea</script>");
  field(root, "Product name").value = "Changed tea";
  form(root, "Edit product").dispatch("submit"); await app.task;
  assert.ok(root.textContent.includes("Changed tea")); assert.equal(writes.at(-1).method, "PUT");
  app.confirm = () => false; button(root, "Remove product from customers").dispatch("click"); await app.task;
  assert.equal(catalog.a.products[0].enabled, true);
  app.confirm = function () { assert.equal(this, globalThis); return true; };
  button(root, "Remove product from customers").dispatch("click"); await app.task;
  assert.ok(root.textContent.includes("Hidden from customers")); assert.equal(app.editProductId, null);
  assert.ok(root.textContent.includes("Product removed from customers"));
  assert.equal(catalog.a.products.length, 1);
  button(root, "Restore product to customers").dispatch("click"); await app.task;
  assert.equal(catalog.a.products[0].enabled, true); assert.equal(app.businessId, "a");
});

test("catalog failed save and hide retain product/editor and show errors; successful mutation leaves sibling unchanged", async () => {
  const { root, app, api, catalog } = setup();
  const first = { id: "one", name: "Tea", category: "Drinks", enabled: true, offerings: [] };
  const sibling = { ...first, id: "two" }; catalog.a.products.push(first, sibling);
  app.tab = "Catalog"; await app.start(); button(root, "Edit product").dispatch("click");
  api.mutate = async () => { throw new ApiError(422, "Enter a valid price."); };
  form(root, "Edit product").dispatch("submit"); await app.task;
  assert.equal(app.editProductId, "one"); assert.equal(field(root, "Product name").value, "Tea");
  assert.ok(root.textContent.includes("Check the product name, category and prices"));
  button(root, "Remove product from customers").dispatch("click"); await app.task;
  assert.equal(app.editProductId, "one"); assert.equal(app.catalog.products[0].enabled, true);
  assert.equal(app.catalog.products.length, 2); assert.deepEqual(catalog.a.products[1], sibling);
});

test("catalog deals save, edit and hide separately; read-only roles cannot mutate", async () => {
  const { root, app, catalog, writes } = setup(); app.tab = "Catalog"; await app.start();
  field(root, "Deal name").value = "Tea special"; field(root, "Deal details").value = "Only configured terms";
  field(root, "Where this deal applies").value = "loc";
  form(root, "Add deal").dispatch("submit"); await app.task;
  assert.equal(writes[0].payload.location_id, "loc"); assert.ok(root.textContent.includes("Tea special"));
  button(root, "Edit deal").dispatch("click"); field(root, "Deal details").value = "Updated terms";
  form(root, "Edit deal").dispatch("submit"); await app.task;
  assert.ok(root.textContent.includes("Updated terms"));
  button(root, "Remove deal from customers").dispatch("click"); await app.task;
  assert.equal(catalog.a.deals[0].enabled, false);
  const viewer = setup(["business.read"]); viewer.app.tab = "Catalog"; await viewer.app.start();
  assert.ok(button(viewer.root, "Catalog")); assert.equal(button(viewer.root, "Save product").disabled, true);
  form(viewer.root, "Add product").dispatch("submit"); await viewer.app.task;
  assert.equal(viewer.writes.length, 0);
});

test("catalog hides only the selected same-name product and preserves another editor; tenant switching clears catalog", async () => {
  const { root, app, catalog } = setup();
  const row = { name: "Same tea", category: "Drinks", enabled: true, offerings: [] };
  catalog.a.products.push({ id: "one", ...row }, { id: "two", ...row });
  app.tab = "Catalog"; await app.start(); app.editProductId = "two"; app.render();
  button(root, "Remove product from customers").dispatch("click"); await app.task;
  assert.equal(app.catalog.products[0].enabled, false);
  assert.equal(app.catalog.products[1].enabled, true); assert.equal(app.editProductId, "two");
  assert.equal(field(root, "Product name").value, "Same tea");
  const select = field(root, "Business"); select.value = "b"; select.dispatch("change"); await app.task;
  assert.equal(app.editProductId, null); assert.deepEqual(app.catalog.products, []);
  assert.ok(!root.textContent.includes("Same tea"));
});

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

test("admin commands use the selected tenant and CSRF mutation client, render text and clear scope on switching", async () => {
  const { root, app, api, writes } = setup();
  const output = "<script>command result</script>\n" + Array.from({ length: 40 }, () => "01234567-89ab-cdef-0123-456789abcdef".repeat(16)).join("\n");
  const original = api.request;
  api.request = async path => path.endsWith("/commands") ? [
    { name: "help", description: "Available commands", argument_hint: "" }, { name: "location", argument_hint: "/location Main" },
    { name: "set-hours", argument_hint: "/set-hours mon-fri 9am-9pm; sat 10am-8pm; sun closed" },
    { name: "add-faq", argument_hint: "/add-faq Do you have parking? | Street parking only." },
  ] : original(path);
  api.mutate = async (path, method, payload) => {
    writes.push({ path, method, payload });
    return { output, location_id: "loc", preview_url: "/widget/?business_id=a" };
  };
  app.tab = "Commands"; await app.start();
  const suggestions = all(root).find(node => node.tagName === "datalist");
  assert.deepEqual(suggestions.children.map(node => node.value), ["/help", "/location", "/set-hours", "/add-faq"]);
  assert.ok(suggestions.textContent.includes("/set-hours mon-fri 9am-9pm; sat 10am-8pm; sun closed"));
  assert.ok(suggestions.textContent.includes("/add-faq Do you have parking? | Street parking only."));
  assert.ok(!/JSON|day_of_week|UUID|location_id/.test(suggestions.textContent));
  const input = field(root, "Command"); input.value = "/location Main"; input.dispatch("input");
  input.parent.parent.dispatch("submit"); await app.task;
  assert.deepEqual(writes, [{ path: "/api/v1/businesses/a/commands/execute", method: "POST", payload: { input: "/location Main", location_id: null } }]);
  assert.ok(root.textContent.includes("<script>command result</script>"));
  const consoleOutput = all(root).find(node => node.tagName === "pre");
  assert.equal(consoleOutput.textContent, output);
  assert.equal(consoleOutput.className, "command-output");
  assert.equal(consoleOutput.role, "region");
  assert.equal(consoleOutput.attributes["aria-label"], "Command output");
  assert.equal(consoleOutput.tabIndex, 0);
  assert.equal(field(root, "Command").value, "");
  assert.equal(field(root, "Command location").value, "loc");
  const link = all(root).find(node => node.tagName === "a");
  assert.equal(link.href, "/widget/?business_id=a"); assert.equal(link.rel, "noopener noreferrer");
  assert.equal(app.busy, false);
  const business = field(root, "Business"); business.value = "b"; business.dispatch("change"); await app.task;
  assert.equal(app.commandLocationId, null); assert.equal(app.commandOutput, ""); assert.equal(app.commandPreview, null);
  assert.ok(!root.textContent.includes("<script>command result</script>"));
});

test("admin command errors retain input and release controls; untrusted preview URLs are ignored", async () => {
  const { root, app, api } = setup(["business.read"]);
  const original = api.request;
  api.request = async path => path.endsWith("/commands") ? [{ name: "help", description: "Help" }] : original(path);
  api.mutate = async () => { throw new ApiError(403, "You do not have permission."); };
  app.tab = "Commands"; await app.start();
  let input = field(root, "Command"); input.value = "/disable --confirm"; input.dispatch("input");
  input.parent.parent.dispatch("submit"); await app.task;
  assert.equal(app.busy, false); assert.equal(button(root, "Run command").disabled, false);
  assert.equal(input.value, "/disable --confirm"); assert.match(app.message, /permission/);
  api.mutate = async () => ({ output: "Preview", location_id: null, preview_url: "https://evil.example/" });
  input.value = "/preview"; input.dispatch("input"); input.parent.parent.dispatch("submit"); await app.task;
  assert.equal(app.commandPreview, null); assert.ok(!all(root).some(node => node.tagName === "a"));
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

test("FAQ editor offers immediate remove and restore actions without changing FAQ details", async () => {
  const { root, app, api, writes, faqs } = setup();
  faqs.a.push({ id: "faq-one", question: "Parking?", answer: "Street parking.", location_id: "loc", enabled: true, is_public: false });
  let faqReads = 0;
  const request = api.request;
  api.request = async path => {
    if (path.endsWith("/faqs")) faqReads += 1;
    return request(path);
  };
  const confirmations = [];
  app.confirm = message => { confirmations.push(message); return true; };
  await app.start();
  button(root, "FAQs").dispatch("click"); await app.task;
  assert.ok(button(root, "Remove from customer answers"));
  assert.equal(faqReads, 1);
  button(root, "Edit FAQ").dispatch("click");
  const editForm = form(root, "Edit FAQ");
  assert.ok(button(editForm, "Remove from customer answers"));
  button(editForm, "Remove from customer answers").dispatch("click"); await app.task;
  assert.deepEqual(confirmations, ["Remove this answer from customer answers? Customers will stop seeing it. The FAQ is kept and can be restored later."]);
  assert.deepEqual(writes.at(-1), { path: "/api/v1/businesses/a/faqs/faq-one", method: "PATCH", payload: { enabled: false } });
  assert.equal(app.faqs[0].enabled, false);
  assert.equal(field(editForm, "FAQ enabled").checked, false);
  assert.ok(button(editForm, "Restore to customer answers"));
  assert.ok(root.textContent.includes("Main · Disabled · Non-public"));
  assert.equal(faqReads, 1, "remove updates the visible FAQ without a manual refresh");
  button(editForm, "Restore to customer answers").dispatch("click"); await app.task;
  assert.equal(confirmations.length, 1, "restoring an answer does not require another confirmation");
  assert.equal(writes.at(-1).payload.enabled, true);
  assert.equal(app.faqs[0].enabled, true);
  assert.equal(field(editForm, "FAQ enabled").checked, true);
  assert.ok(button(editForm, "Remove from customer answers"));
  assert.ok(root.textContent.includes("Main · Enabled · Non-public"));
  assert.equal(faqReads, 1, "restore updates the visible FAQ without a manual refresh");
  for (const faq of [faqs.a[0], app.faqs[0]]) {
    assert.equal(faq.question, "Parking?");
    assert.equal(faq.answer, "Street parking.");
    assert.equal(faq.location_id, "loc");
    assert.equal(faq.is_public, false);
    assert.equal(faq.enabled, true);
  }
});

test("failed FAQ removal preserves customer visibility and shows the error", async () => {
  const { root, app, api, faqs } = setup();
  faqs.a.push({ id: "faq-one", question: "Parking?", answer: "Street parking.", location_id: null, enabled: true, is_public: true });
  await app.start();
  button(root, "FAQs").dispatch("click"); await app.task;
  button(root, "Edit FAQ").dispatch("click");
  const editForm = form(root, "Edit FAQ");
  const confirmations = [];
  app.confirm = message => { confirmations.push(message); return true; };
  api.mutate = async () => { throw new ApiError(409, "Could not remove this answer. Please try again."); };
  button(editForm, "Remove from customer answers").dispatch("click"); await app.task;
  assert.equal(confirmations.length, 1);
  assert.equal(app.faqs[0].enabled, true);
  assert.equal(field(editForm, "FAQ enabled").checked, true);
  assert.ok(button(editForm, "Remove from customer answers"));
  assert.ok(root.textContent.includes("Parking?"));
  assert.ok(root.textContent.includes("Street parking."));
  assert.ok(root.textContent.includes("Could not remove this answer. Please try again."));
  assert.equal(app.failed, true);
});

test("Delete FAQ targets only the selected scope immediately and resets only its own editor", async () => {
  const { root, app, api, faqs } = setup();
  faqs.a.push(
    { id: "faq-business", question: "Do you have parking?", answer: "Parking across the business.", location_id: null, enabled: true, is_public: true },
    { id: "faq-location", question: "Do you have parking?", answer: "Parking at Main.", location_id: "loc", enabled: false, is_public: false },
  );
  let faqReads = 0;
  const request = api.request;
  api.request = async path => {
    if (path.endsWith("/faqs")) faqReads += 1;
    return request(path);
  };
  const confirmations = [];
  app.confirm = message => { confirmations.push(message); return true; };
  await app.start();
  button(root, "FAQs").dispatch("click"); await app.task;
  const listCard = all(root).find(node => node.tagName === "article" && node.textContent.includes("Parking across the business."));
  assert.ok(button(listCard, "Delete FAQ"));
  button(listCard, "Edit FAQ").dispatch("click");
  const locationCard = all(root).find(node => node.tagName === "article" && node.textContent.includes("Parking at Main."));
  button(locationCard, "Delete FAQ").dispatch("click"); await app.task;
  assert.deepEqual(confirmations, ["Delete this FAQ permanently?\nThis cannot be undone."]);
  assert.deepEqual(app.faqs.map(item => item.id), ["faq-business"]);
  assert.ok(root.textContent.includes("Parking across the business."));
  assert.ok(!root.textContent.includes("Parking at Main."));
  assert.equal(app.editFaqId, "faq-business", "deleting another scope must preserve the open editor");
  assert.ok(form(root, "Edit FAQ"));
  assert.ok(root.textContent.includes("FAQ deleted. The answer for Main was removed."));
  assert.equal(faqReads, 1, "list deletion updates locally without reloading FAQ data");

  button(form(root, "Edit FAQ"), "Delete FAQ").dispatch("click"); await app.task;
  assert.equal(confirmations.length, 2);
  assert.equal(confirmations[1], "Delete this FAQ permanently?\nThis cannot be undone.");
  assert.equal(app.editFaqId, null);
  assert.equal(form(root, "Edit FAQ"), undefined);
  assert.ok(form(root, "New FAQ"));
  assert.deepEqual(app.faqs, []);
  assert.ok(!root.textContent.includes("Parking across the business."));
  assert.ok(root.textContent.includes("FAQ deleted. The business-wide answer was removed."));
  assert.equal(faqReads, 1, "editor deletion updates locally without reloading FAQ data");
  assert.deepEqual(faqs.a, []);
});

test("cancelled or failed FAQ deletion keeps the record and provides clear feedback", async () => {
  const { root, app, api, faqs } = setup();
  faqs.a.push({ id: "faq-one", question: "Keep this FAQ?", answer: "Do not remove me.", location_id: null, enabled: true, is_public: true });
  await app.start();
  button(root, "FAQs").dispatch("click"); await app.task;
  const card = all(root).find(node => node.tagName === "article" && node.textContent.includes("Keep this FAQ?"));
  const confirmations = [];
  app.confirm = message => { confirmations.push(message); return false; };
  button(card, "Delete FAQ").dispatch("click"); await app.task;
  assert.equal(app.faqs.length, 1);
  assert.equal(faqs.a.length, 1);
  assert.ok(root.textContent.includes("Keep this FAQ?"));
  assert.ok(root.textContent.includes("Cancelled."));

  app.confirm = () => true;
  api.mutate = async () => { throw new ApiError(500, "Internal error marker"); };
  button(card, "Edit FAQ").dispatch("click");
  const editForm = form(root, "Edit FAQ");
  button(editForm, "Delete FAQ").dispatch("click"); await app.task;
  assert.equal(app.faqs.length, 1);
  assert.equal(faqs.a.length, 1);
  assert.equal(app.editFaqId, "faq-one");
  assert.ok(form(root, "Edit FAQ"));
  assert.ok(root.textContent.includes("Keep this FAQ?"));
  assert.ok(root.textContent.includes("Could not delete this FAQ. Please try again."));
  assert.equal(root.textContent.includes("Internal error marker"), false);
  assert.equal(app.failed, true);
});

test("Team uses plain role labels and shows a copy-once invitation link", async () => {
  const { root, app, writes, copied } = setup(); await app.start();
  button(root, "Team").dispatch("click"); await app.task;
  assert.ok(root.textContent.includes("Owner — full control, including Team access"));
  assert.ok(root.textContent.includes("Manager — view business information and manage locations and hours"));
  assert.equal(root.textContent.includes("membership.manage"), false);
  field(root, "Email").value = "new.person@example.test";
  field(root, "Role").value = "manager";
  form(root, "Add a person").dispatch("submit"); await app.task;
  assert.deepEqual(writes.at(-1), {
    path: "/api/v1/businesses/a/invitations", method: "POST",
    payload: { email: "new.person@example.test", role: "manager" },
  });
  assert.equal(field(root, "One-time invite link").value, "https://budbot.test/admin/activate.html#secret-one-time-token");
  assert.ok(root.textContent.includes("Invitation expires"));
  button(root, "Copy link").dispatch("click"); await app.task;
  assert.deepEqual(copied, ["https://budbot.test/admin/activate.html#secret-one-time-token"]);
  assert.ok(all(root).some(node => node.tagName === "p" && node.textContent === "Link copied."));
  button(root, "Business").dispatch("click");
  assert.equal(field(root, "One-time invite link"), undefined);
  button(root, "Team").dispatch("click"); await app.task;
  assert.equal(field(root, "One-time invite link"), undefined);
});

test("invitation copy failure shows accessible manual-copy guidance", async () => {
  const { root, app } = setup(); await app.start();
  button(root, "Team").dispatch("click"); await app.task;
  field(root, "Email").value = "new.person@example.test";
  field(root, "Role").value = "manager";
  form(root, "Add a person").dispatch("submit"); await app.task;
  app.document.defaultView.navigator.clipboard.writeText = async () => { throw new Error("synthetic clipboard failure"); };
  button(root, "Copy link").dispatch("click"); await app.task;
  assert.ok(all(root).some(node => node.tagName === "p"
    && node.textContent === "Couldn’t copy the link. Select it and copy it manually."
    && node.attributes.role === "alert" && node.attributes["data-error"] === "true"));
  assert.equal(app.failed, true);
});

test("Team clearly lists pending invitations and confirms then removes a revoked invite", async () => {
  const { root, app, api, writes, team } = setup();
  team.a.invitations.push({ invitation_id: "private-invitation-id", email: "pending.person@example.test", role: "manager",
    expires_at: "2026-10-30T00:00:00Z" });
  let teamReads = 0;
  const request = api.request;
  api.request = async path => {
    if (path.endsWith("/members")) teamReads += 1;
    return request(path);
  };
  const confirmations = [];
  app.confirm = message => { confirmations.push(message); return true; };
  await app.start();
  button(root, "Team").dispatch("click"); await app.task;
  assert.ok(root.textContent.includes("Pending invitations"));
  assert.ok(root.textContent.includes("pending.person@example.test"));
  assert.ok(root.textContent.includes("Manager — view business information and manage locations and hours"));
  assert.equal(teamReads, 1);
  assert.equal(root.textContent.includes("private-invitation-id"), false);
  assert.equal(root.textContent.includes("secret-one-time-token"), false);
  button(root, "Revoke invite").dispatch("click"); await app.task;
  assert.deepEqual(confirmations, ["Revoke the invitation for pending.person@example.test?"]);
  assert.ok(writes.some(write => write.path === "/api/v1/businesses/a/invitations/private-invitation-id" && write.method === "DELETE"));
  assert.equal(team.a.invitations.length, 0);
  assert.equal(app.team.invitations.length, 0);
  assert.equal(teamReads, 1, "successful revoke updates the current Team view without another list request");
  assert.ok(root.textContent.includes("No pending invitations."));
  assert.ok(root.textContent.includes("Invitation revoked."));
});

test("cancelled or failed invite revocation remains visible and reports the problem", async () => {
  const { root, app, api, writes, team } = setup();
  team.a.invitations.push({ invitation_id: "private-invitation-id", email: "pending.person@example.test", role: "viewer",
    expires_at: "2026-10-30T00:00:00Z" });
  await app.start();
  button(root, "Team").dispatch("click"); await app.task;
  app.confirm = () => false;
  button(root, "Revoke invite").dispatch("click"); await app.task;
  assert.equal(writes.some(write => write.method === "DELETE"), false);
  assert.equal(team.a.invitations.length, 1);

  app.confirm = () => true;
  const mutate = api.mutate;
  api.mutate = async (path, method, payload) => {
    if (path.includes("/invitations/") && method === "DELETE")
      throw new Error("Could not revoke the invite. Check your connection and try again.");
    return mutate(path, method, payload);
  };
  button(root, "Revoke invite").dispatch("click"); await app.task;
  assert.equal(team.a.invitations.length, 1);
  assert.equal(app.team.invitations.length, 1);
  assert.ok(root.textContent.includes("Could not revoke the invite. Check your connection and try again."));
  assert.equal(app.failed, true);
  assert.equal(button(root, "Revoke invite").disabled, false);
});

test("demoting another owner confirms that owner's access change", async () => {
  const { root, app, writes, team } = setup();
  team.a.members.push({ membership_id: "membership-two", user_id: "other-owner-id", display_name: "Second Owner", email: "second@example.test", role: "owner", active: true });
  const confirmations = [];
  app.confirm = message => { confirmations.push(message); return false; };
  await app.start();
  button(root, "Team").dispatch("click"); await app.task;
  const card = all(root).find(node => node.tagName === "article" && node.textContent.includes("Second Owner"));
  assert.ok(card);
  field(card, "Access").value = "admin";
  button(card, "Save role").dispatch("click"); await app.task;
  assert.deepEqual(confirmations, ["Change Second Owner's access? They will lose Team management and invitations they created will be revoked."]);
  assert.equal(writes.length, 0);
});

test("failed role change restores persisted role and retains the server error", async () => {
  const { root, app, api, team } = setup();
  app.confirm = () => true;
  const mutate = api.mutate;
  api.mutate = async (path, method, payload) => {
    if (path.endsWith("/membership-one") && method === "PATCH")
      throw new Error("You’re the only owner of this business. Add another owner before changing or removing your access.");
    return mutate(path, method, payload);
  };
  await app.start();
  button(root, "Team").dispatch("click"); await app.task;
  const card = all(root).find(node => node.tagName === "article" && node.textContent.includes("Store Owner"));
  const selector = field(card, "Access");
  selector.value = "admin";
  button(card, "Save role").dispatch("click"); await app.task;
  assert.equal(team.a.members[0].role, "owner");
  assert.equal(selector.value, "owner");
  assert.ok(root.textContent.includes("You’re the only owner of this business. Add another owner before changing or removing your access."));
  assert.equal(app.failed, true);
});

test("successful role change updates the persisted member and refreshed selector", async () => {
  const { root, app, writes, team } = setup();
  team.a.members.push({ membership_id: "membership-viewer", user_id: "viewer-id", display_name: "Team Viewer",
    email: "viewer@example.test", role: "viewer", active: true });
  await app.start();
  button(root, "Team").dispatch("click"); await app.task;
  const card = all(root).find(node => node.tagName === "article" && node.textContent.includes("Team Viewer"));
  field(card, "Access").value = "manager";
  button(card, "Save role").dispatch("click"); await app.task;
  assert.ok(writes.some(write => write.path === "/api/v1/businesses/a/members/membership-viewer"
    && write.method === "PATCH" && write.payload.role === "manager"));
  assert.equal(team.a.members[1].role, "manager");
  const updated = all(root).find(node => node.tagName === "article" && node.textContent.includes("Team Viewer"));
  assert.equal(field(updated, "Access").value, "manager");
  assert.ok(root.textContent.includes("Role updated."));
});

test("Team warns when an invitation address is an IPv6 loopback", async () => {
  const { root, app } = setup();
  app.document.defaultView.location.origin = "http://[::1]:8000";
  await app.start();
  button(root, "Team").dispatch("click"); await app.task;
  field(root, "Email").value = "new.person@example.test";
  form(root, "Add a person").dispatch("submit"); await app.task;
  assert.ok(all(root).some(node => node.role === "alert"
    && node.textContent.includes("only available on this computer")));
});

test("first-run sign-in guidance points owners to the supported local setup command", async () => {
  const { root, app } = setup(); app.renderLogin();
  assert.ok(root.textContent.includes("First time setting up BudBot?"));
  assert.ok(root.textContent.includes("python -m budbot.admin setup-owner"));
  assert.ok(root.textContent.includes("docker compose -f docker-compose.dev.yml"));
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
  assert.ok(button(root, "Test Connection"));
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

function localRuntime(available = true, permissions = ["business.read", "runtime.shutdown"]) {
  const result = setup(permissions); const request = result.api.request;
  result.api.request = async path => path.endsWith("/local-runtime")
    ? { available, state: available ? "running" : "unavailable" } : request(path);
  return result;
}

test("local System controls require both owner permission and a live local capability", async () => {
  for (const [available, permissions] of [[false, ["business.read", "runtime.shutdown"]], [true, ["business.read"]]]) {
    const { root, app } = localRuntime(available, permissions); await app.start();
    assert.equal(button(root, "System"), undefined);
    assert.equal(button(root, "Shut down BudBot"), undefined);
  }
  const { root, app, api } = localRuntime(); const request = api.request;
  api.request = async path => {
    if (path.endsWith("/local-runtime")) throw new ApiError(404, "Not found.");
    return request(path);
  };
  await app.start();
  assert.equal(button(root, "System"), undefined);
  assert.ok(form(root, "Business settings")); assert.equal(app.busy, false);
});

test("local shutdown uses the Window confirmation receiver and cancellation never sends a request", async () => {
  const { root, app, writes } = localRuntime(); let confirmed = false;
  app.confirm = function (message) { assert.equal(this, globalThis); assert.match(message, /all businesses/); return confirmed; };
  await app.start(); button(root, "System").dispatch("click");
  assert.match(root.textContent, /BudBot status: Running/);
  button(root, "Shut down BudBot").dispatch("click"); await app.task;
  assert.deepEqual(writes, []);
  confirmed = true;
  button(root, "Shut down BudBot").dispatch("click"); await app.task;
  assert.deepEqual(writes, [{ path: "/api/v1/businesses/a/local-runtime/shutdown", method: "POST", payload: {} }]);
  assert.match(root.textContent, /BudBot is shutting down\. You can close this tab\./);
  assert.equal(button(root, "Shut down BudBot"), undefined);
  assert.equal(app.busy, false);
});

test("shutdown connection loss leaves a clear terminal state without retrying or polling", async () => {
  for (const status of [0, 502]) {
  const { root, app, api } = localRuntime(); let reject; let calls = 0;
  api.mutate = () => { calls++; return new Promise((resolve, fail) => { reject = fail; }); };
  await app.start(); button(root, "System").dispatch("click");
  button(root, "Shut down BudBot").dispatch("click");
  assert.match(root.textContent, /Requesting local shutdown/);
  assert.equal(button(root, "Reload settings"), undefined);
  reject(new ApiError(status, "private transport details")); await app.task;
  assert.match(root.textContent, /connection closed before shutdown could be confirmed/);
  assert.match(root.textContent, /You can close this tab/);
  assert.ok(!root.textContent.includes("private transport details"));
  assert.equal(calls, 1); assert.equal(app.busy, false);
  }
});

test("rejected local shutdown releases controls and does not claim success", async () => {
  const { root, app, api } = localRuntime();
  api.mutate = async () => { throw new ApiError(403, "Shutdown was not authorized."); };
  await app.start(); button(root, "System").dispatch("click");
  button(root, "Shut down BudBot").dispatch("click"); await app.task;
  assert.match(root.textContent, /Shutdown was not authorized/);
  assert.ok(!root.textContent.includes("BudBot is shutting down"));
  assert.equal(button(root, "Shut down BudBot").disabled, false);
  assert.equal(app.busy, false);
});

function providerDiagnostics(permissions = ["business.read", "provider.read", "provider.write"]) {
  const result = setup(permissions);
  const profile = { configured: true, provider: "openai_compatible", model: "saved/model", base_url: "http://provider.test/v1",
    enabled: true, tool_calling: true, credential_configured: false, runtime_status: "ready", runtime_code: null };
  const request = result.api.request;
  result.api.request = async path => path.endsWith("/provider") ? structuredClone(profile) : request(path);
  result.api.mutate = async (path, method, payload) => {
    result.writes.push({ path, method, payload });
    if (path.endsWith("/test")) return { code: "AI_CONNECTION_OK" };
    Object.assign(profile, payload); return structuredClone(profile);
  };
  return { ...result, profile };
}

test("provider test uses saved tenant settings once, disables controls in flight and shows success", async () => {
  const { root, app, api, profile, writes } = providerDiagnostics();
  await app.start(); button(root, "AI Provider").dispatch("click"); await app.task;
  assert.match(root.textContent, /AI runtime: Enabled and configured/);
  assert.match(root.textContent, /Not tested/);
  let resolve;
  api.mutate = (path, method, payload) => { writes.push({ path, method, payload }); return new Promise(done => { resolve = done; }); };
  const testButton = button(root, "Test Connection");
  testButton.dispatch("click"); const task = app.task;
  assert.equal(testButton.disabled, true); assert.equal(app.busy, true);
  assert.match(root.textContent, /Testing saved configuration/);
  testButton.dispatch("click"); assert.equal(writes.length, 1);
  resolve({ code: "AI_CONNECTION_OK", message: "private marker", model: "private marker", provider: "private marker" }); await task;
  assert.deepEqual(writes, [{ path: "/api/v1/businesses/a/provider/test", method: "POST", payload: {} }]);
  assert.match(root.textContent, /Connected successfully/);
  assert.match(root.textContent, /If the compatible endpoint supports model discovery, the configured model ID was also checked/);
  assert.match(root.textContent, /Provider: LM Studio \/ OpenAI-compatible/);
  assert.ok(root.textContent.includes(`Model: ${profile.model}`));
  assert.ok(!root.textContent.includes("private marker"));
  assert.equal(button(root, "Test Connection").disabled, false); assert.equal(app.busy, false);
  assert.equal(field(root, "New API key").value, "");
});

test("provider diagnostics display each fixed failure class without raw server data", async () => {
  const failures = [
    ["AI_DISABLED", /AI is disabled/], ["AI_CONFIGURATION_INVALID", /configuration is incomplete/],
    ["AI_CREDENTIAL_MISSING", /requires a stored credential/], ["AI_ENDPOINT_DENIED", /not deployment-approved/],
    ["AI_PROVIDER_UNREACHABLE", /Check that the server .* is running/], ["AI_PROVIDER_TIMEOUT", /time limit/],
    ["AI_PROVIDER_AUTH_FAILED", /rejected the stored credential/], ["AI_MODEL_UNAVAILABLE", /model or API endpoint was not found/],
    ["AI_PROVIDER_BAD_RESPONSE", /incompatible response/], ["AI_PROVIDER_UNAVAILABLE", /temporarily unavailable or rate limited/],
    ["AI_PROVIDER_ERROR", /could not be completed/], ["private marker", /could not be completed/],
  ];
  for (const [code, explanation] of failures) {
    const { root, app, api } = providerDiagnostics();
    api.mutate = async () => ({ code, message: "<script>private marker</script>", response: "private marker" });
    await app.start(); button(root, "AI Provider").dispatch("click"); await app.task;
    button(root, "Test Connection").dispatch("click"); await app.task;
    assert.match(root.textContent, /Failed/); assert.match(root.textContent, explanation);
    assert.ok(!root.textContent.includes("private marker")); assert.equal(app.busy, false);
  }
});

test("provider test requires write permission and saved edits; changes and tenant switching clear results", async () => {
  const readOnly = providerDiagnostics(["business.read", "provider.read"]);
  await readOnly.app.start(); button(readOnly.root, "AI Provider").dispatch("click"); await readOnly.app.task;
  assert.equal(button(readOnly.root, "Test Connection"), undefined);
  assert.equal(readOnly.writes.length, 0);
  const { root, app, writes } = providerDiagnostics();
  await app.start(); button(root, "AI Provider").dispatch("click"); await app.task;
  button(root, "Test Connection").dispatch("click"); await app.task;
  const model = field(root, "Model identifier"); model.value = "new/model"; model.dispatch("input");
  assert.equal(button(root, "Test Connection").disabled, true); assert.match(root.textContent, /Not tested/);
  button(root, "Test Connection").dispatch("click"); assert.equal(writes.length, 1);
  form(root, "Provider configuration").dispatch("submit"); await app.task;
  assert.equal(app.dirty, false); assert.equal(button(root, "Test Connection").disabled, false);
  button(root, "Test Connection").dispatch("click"); await app.task;
  assert.match(root.textContent, /Connected successfully/);
  const businesses = field(root, "Business"); businesses.value = "b"; businesses.dispatch("change"); await app.task;
  assert.equal(app.providerTest, null); assert.ok(!root.textContent.includes("Connected successfully"));
});

test("runtime status distinguishes disabled and incomplete; test transport errors remain safe and recoverable", async () => {
  for (const [status, label] of [["disabled", "Disabled"], ["incomplete", "Configuration incomplete"]]) {
    const { root, app, profile, api } = providerDiagnostics(); profile.runtime_status = status;
    await app.start(); button(root, "AI Provider").dispatch("click"); await app.task;
    assert.ok(root.textContent.includes(`AI runtime: ${label}`));
    api.mutate = async () => { throw new ApiError(500, "private marker"); };
    button(root, "Test Connection").dispatch("click"); await app.task;
    assert.match(root.textContent, /could not be completed/); assert.ok(!root.textContent.includes("private marker"));
    assert.equal(button(root, "Test Connection").disabled, false);
  }
  for (const status of [401, 403]) {
    const { root, app, api } = providerDiagnostics();
    await app.start(); button(root, "AI Provider").dispatch("click"); await app.task;
    api.mutate = async () => { throw new ApiError(status, "private marker"); };
    button(root, "Test Connection").dispatch("click"); await app.task;
    assert.ok(!root.textContent.includes("private marker")); assert.equal(app.busy, false);
    assert.ok(button(root, status === 401 ? "Sign in" : "Test Connection"));
  }
});
