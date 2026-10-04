import test from "node:test";
import assert from "node:assert/strict";
import { BudBotWidget, chatAvatarReference, matchingCommands, needsAgeGate, safeLocalAssetUrl, widgetBootstrapConfig } from "../src/embed.js";

test("slash autocomplete includes available command names and aliases", () => {
  const commands = [
    { name: "locations", aliases: ["location"], available: true },
    { name: "products", aliases: [], available: false },
  ];
  assert.deepEqual(matchingCommands(commands, "/loc"), [commands[0]]);
  assert.deepEqual(matchingCommands(commands, "hello"), []);
  assert.deepEqual(matchingCommands(commands, "/products"), []);
});

test("age gate follows backend profile and session state", () => {
  assert.equal(needsAgeGate({ requires_age_gate: true }, { age_gate_status: "REQUIRED_UNVERIFIED" }), true);
  assert.equal(needsAgeGate({ requires_age_gate: true }, { age_gate_status: "VERIFIED" }), false);
  assert.equal(needsAgeGate({ requires_age_gate: false }, { age_gate_status: "NOT_REQUIRED" }), false);
});

test("customer logo and assistant avatar accept only generated same-origin assets", () => {
  const ref = "/local-assets/12345678-1234-4678-9234-567812345678/0123456789abcdef0123456789abcdef.png";
  assert.equal(safeLocalAssetUrl(ref, "http://127.0.0.1:8000"), `http://127.0.0.1:8000${ref}`);
  assert.equal(safeLocalAssetUrl("https://tracker.example/logo.png", "http://127.0.0.1:8000"), null);
  assert.equal(safeLocalAssetUrl("/local-assets/../../secret.png", "http://127.0.0.1:8000"), null);
  assert.equal(safeLocalAssetUrl(`${ref}?size=large`, "http://127.0.0.1:8000"), null);
  assert.equal(safeLocalAssetUrl("/local-assets/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/0123456789abcdef0123456789abcdef.png", "http://127.0.0.1:8000"), null);
});

test("widget reads attributes after the custom element is constructed", () => {
  const attributes = { "business-id": "demo-business", "api-base": "http://127.0.0.1:8000/" };
  const element = { getAttribute: (name) => attributes[name] || null };
  assert.deepEqual(widgetBootstrapConfig(element, "http://localhost:3000"), {
    businessId: "demo-business",
    apiBase: "http://127.0.0.1:8000",
  });
});

test("business logo is the default chat avatar and an assistant avatar overrides it", () => {
  const logo = "/local-assets/12345678-1234-4678-9234-567812345678/0123456789abcdef0123456789abcdef.png";
  const avatar = "/local-assets/12345678-1234-4678-9234-567812345678/1123456789abcdef0123456789abcdef.webp";
  assert.equal(chatAvatarReference(logo, null), logo);
  assert.equal(chatAvatarReference(logo, ""), logo);
  assert.equal(chatAvatarReference(logo, avatar), avatar);
  assert.equal(chatAvatarReference(null, null), null);
});

function customerWidget(t, locations, { requiresAgeGate = false } = {}) {
  const previousLocation = globalThis.location;
  const previousDocument = globalThis.document;
  globalThis.location = { origin: "http://widget.test" };
  globalThis.document = { createElement: () => ({}) };
  t.after(() => {
    if (previousLocation === undefined) delete globalThis.location;
    else globalThis.location = previousLocation;
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  });
  const calls = [];
  let selected = null;
  const business = { display_name: "Widget Shop", logo_reference: "saved-logo", primary_brand_color: "#123456" };
  t.mock.method(globalThis, "fetch", async (url, options) => {
    const path = new URL(url).pathname;
    calls.push({ path, options });
    // The old startup requests reproduce M9A's admin authentication failure.
    if (path.startsWith("/api/v1/businesses/")) {
      return { ok: false, status: 401, json: async () => ({ detail: "Authentication is required." }) };
    }
    let data;
    if (path === "/api/v1/sessions" || path === "/api/v1/sessions/customer-session/location") {
      assert.equal(options.method, path.endsWith("location") ? "PATCH" : "POST");
      selected = JSON.parse(options.body).selected_location_id || null;
      data = { id: "customer-session", selected_location_id: selected,
        age_gate_status: requiresAgeGate ? "REQUIRED_UNVERIFIED" : "NOT_REQUIRED" };
    } else if (path === "/api/v1/sessions/customer-session/widget") {
      data = { business, locations,
        assistant: { display_name: selected ? "Location Helper" : "Test Assistant",
          greeting: selected ? "Welcome to the location." : "Welcome.", primary_color: "#654321", avatar_reference: null },
        compliance: { requires_age_gate: requiresAgeGate, website_attestation_notice: selected ? "Selected location notice" : "Choose a location" } };
    } else if (path === "/api/v1/commands") {
      assert.equal(new URL(url).searchParams.get("session_id"), "customer-session");
      data = [];
    } else if (path === "/api/v1/chat" || path === "/api/v1/commands/execute") {
      data = { content: "Customer reply", output: "Command reply" };
    } else {
      assert.fail(`Unexpected widget request: ${url}`);
    }
    return { ok: true, json: async () => data };
  });
  const widget = Object.create(BudBotWidget.prototype);
  const nodes = new Map();
  widget.$ = (selector) => {
    if (!nodes.has(selector)) nodes.set(selector, {
      options: [], append(option) { this.options.push(option); },
      addEventListener() {}, textContent: "", hidden: true,
    });
    return nodes.get(selector);
  };
  const attributes = { "business-id": "public-business", "api-base": "http://api.test" };
  widget.getAttribute = (name) => attributes[name];
  widget.setBusinessLogo = (reference) => { widget.logo = reference; };
  widget.setBrandColor = (color) => { widget.color = color; };
  widget.showChat = () => { widget.screen = "chat"; };
  widget.showGate = () => { widget.screen = "gate"; };
  widget.addMessage = () => {};
  return { widget, calls };
}

test("widget bootstraps a customer session without any admin request or cookie", async (t) => {
  const { widget, calls } = customerWidget(t, [{ id: "main", display_name: "Main" }]);
  await widget.initialize();
  assert.deepEqual(calls.map(({ path }) => path), [
    "/api/v1/sessions", "/api/v1/sessions/customer-session/widget",
    "/api/v1/sessions/customer-session/location", "/api/v1/sessions/customer-session/widget",
    "/api/v1/commands",
  ]);
  assert.equal(widget.$(".business-name").textContent, "Widget Shop");
  assert.equal(widget.$(".business-subtitle").textContent, "Ask Location Helper anything");
  assert.equal(widget.logo, "saved-logo");
  assert.equal(widget.color, "#654321");
  assert.equal(widget.screen, "chat");
  assert.equal(widget.session.id, "customer-session");
  await widget.send({ value: "Hello" });
  await widget.send({ value: "/help" });
  const [chat, command] = calls.slice(-2);
  assert.equal(chat.path, "/api/v1/chat");
  assert.deepEqual(JSON.parse(chat.options.body), { session_id: "customer-session", message: "Hello" });
  assert.equal(command.path, "/api/v1/commands/execute");
  assert.deepEqual(JSON.parse(command.options.body), { session_id: "customer-session", input: "/help" });
  for (const { options } of calls) {
    assert.equal(options.credentials, "omit");
    assert.equal(options.headers["X-BudBot-Business-ID"], "public-business");
    assert.equal(options.headers["X-CSRF-Token"], undefined);
  }
});

test("multiple locations retain one customer session and refresh effective branding and age notice", async (t) => {
  const { widget, calls } = customerWidget(t, [
    { id: "main", display_name: "Main" }, { id: "other", display_name: "Other" },
  ], { requiresAgeGate: true });
  await widget.initialize();
  assert.equal(widget.$("select.loc").hidden, false);
  assert.equal(widget.$(".status").textContent, "Choose a location to start chatting.");
  assert.equal(calls.length, 2);
  await widget.chooseLocation("other");
  assert.equal(widget.session.id, "customer-session");
  assert.equal(widget.session.selected_location_id, "other");
  assert.equal(widget.assistant.display_name, "Location Helper");
  assert.equal(widget.compliance.website_attestation_notice, "Selected location notice");
  assert.equal(widget.screen, "gate");
  assert.equal(calls.filter(({ path }) => path === "/api/v1/sessions").length, 1);
});

test("business with no locations can load its base assistant and chat", async (t) => {
  const { widget } = customerWidget(t, []);
  await widget.initialize();
  assert.equal(widget.session.selected_location_id, null);
  assert.equal(widget.assistant.display_name, "Test Assistant");
  assert.equal(widget.screen, "chat");
});

test("published branding accepts saved legacy references through the safe public route", async () => {
  const { publishedBrandAssetUrl } = await import("../src/embed.js");
  const reference = "/local-assets/12345678-1234-4678-9234-567812345678/0123456789abcdef0123456789abcdef.png";
  assert.equal(publishedBrandAssetUrl(reference, "https://budbot.test"), `https://budbot.test${reference.replace("/local-assets/", "/assets/branding/")}`);
  assert.equal(publishedBrandAssetUrl(reference.replace("/local-assets/", "/assets/branding/"), "https://budbot.test"), `https://budbot.test${reference.replace("/local-assets/", "/assets/branding/")}`);
  assert.equal(publishedBrandAssetUrl("https://other.test/logo.png", "https://budbot.test"), null);
});

test("customer branding image requests omit owner cookies", async t => {
  const { loadBrandImage } = await import("../src/embed.js");
  const previousFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = previousFetch; });
  let options;
  globalThis.fetch = async (url, provided) => { options = provided; return { ok: true, blob: async () => new Blob(["image bytes"], { type: "image/png" }) }; };
  const callbacks = {};
  const image = { addEventListener: (name, fn) => { callbacks[name] = fn; } };
  await loadBrandImage(image, "https://budbot.test/assets/branding/test.png");
  assert.deepEqual(options, { credentials: "omit" });
  assert.ok(image.src.startsWith("blob:"));
  callbacks.load();
});
