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
function setup(permissions = ["business.read", "business.write", "location.write", "assistant.write", "branding.write"]) {
  const document = { createElement: tag => new Element(tag, document) };
  const root = document.createElement("main"); const writes = []; const opened = [];
  const account = { user: { email: "owner@example.test" }, businesses: [{ business_id: "a", display_name: "<script>business</script>", role: "owner", permissions }, { business_id: "b", display_name: "Second business", role: "viewer", permissions: ["business.read"] }] };
  const business = { id: "a", display_name: "<script>business</script>", industry: "general_retail", active: true, default_timezone: "UTC", products_enabled: true, promotions_enabled: true };
  const assistant = { display_name: "Assistant", greeting: "Hello", fallback_message: "Ask staff", enabled: true };
  const location = { id: "loc", display_name: "Main", active: true, hours: [], timezone: "UTC" };
  const api = {
    session: null, restore: async function () { this.session = structuredClone(account); return this.session; },
    login: async function () { this.session = structuredClone(account); return this.session; }, logout: async function () { this.session = null; },
    can: function (id, permission) { return this.session?.businesses.find(item => item.business_id === id)?.permissions.includes(permission) || false; },
    request: async path => {
      if (path.endsWith("assistant-override")) return null;
      if (path.endsWith("effective-assistant")) return structuredClone(assistant);
      if (path.includes("compliance-profile/locations")) return { status: "resolved", location_active: true, profile: { profile_id: "general_retail" } };
      if (path.endsWith("compliance-profile")) return { profile_id: "general_retail", requires_age_gate: false };
      if (path.endsWith("/assistant")) return structuredClone(assistant);
      if (path.includes("/locations?")) return [structuredClone(location)];
      return { ...structuredClone(business), id: path.split("/").at(-1) };
    },
    mutate: async (path, method, payload) => { writes.push({ path, method, payload }); Object.assign(business, payload); return { id: "loc" }; },
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
