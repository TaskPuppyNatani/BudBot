import test from "node:test";
import assert from "node:assert/strict";
import { chatAvatarReference, matchingCommands, needsAgeGate, safeLocalAssetUrl, widgetBootstrapConfig } from "../src/embed.js";

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
