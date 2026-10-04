import test from "node:test";
import assert from "node:assert/strict";
import { hoursRows, hoursPayload, overridePatch, OVERRIDE_FIELDS, previewUrl, brandAssetUrl, encodeImage } from "../public/src/forms.js";

test("hours distinguish unconfigured, closed and open and validate intervals", () => {
  const rows = hoursRows([{ day_of_week: 0, is_closed: false, open_time: "09:00", close_time: "17:00" }, { day_of_week: 1, is_closed: true }]);
  assert.deepEqual(rows.map(row => row.state), ["open", "closed", "unconfigured", "unconfigured", "unconfigured", "unconfigured", "unconfigured"]);
  assert.deepEqual(hoursPayload(rows), [{ day_of_week: 0, is_closed: false, open_time: "09:00", close_time: "17:00" }, { day_of_week: 1, is_closed: true }]);
  assert.throws(() => hoursPayload([{ day_of_week: 0, state: "open", open_time: "17:00", close_time: "09:00" }]), /Monday/);
});

test("opening inherited overrides never materializes effective values", () => {
  const fields = Object.fromEntries(OVERRIDE_FIELDS.map(key => [key, { mode: "inherit", value: key === "enabled" ? "true" : "Inherited display value" }]));
  assert.deepEqual(overridePatch(null, fields), {});
  fields.greeting = { mode: "override", value: "Local greeting" };
  assert.deepEqual(overridePatch(null, fields), { greeting: "Local greeting" });
  assert.deepEqual(overridePatch({ greeting: "Previous override" }, { ...fields, greeting: { mode: "inherit", value: "" } }), { greeting: null });
  fields.enabled = { mode: "override", value: "false" };
  assert.equal(overridePatch(null, fields).enabled, false);
});

test("preview contains only the selected business and branding URLs stay local", () => {
  assert.equal(previewUrl("business-id"), "/widget/?business_id=business-id");
  assert.ok(!previewUrl("business-id").includes("token"));
  const ref = "/local-assets/12345678-1234-4678-9234-567812345678/0123456789abcdef0123456789abcdef.png";
  assert.equal(brandAssetUrl(ref), ref.replace("/local-assets/", "/assets/branding/"));
  for (const ref of ["https://other.test/image.png", "/assets/branding/../../secret", "/private/path"]) assert.equal(brandAssetUrl(ref), null);
});

test("image encoding rejects invalid size/type before making an upload", async () => {
  await assert.rejects(encodeImage({ size: 5 * 1024 * 1024, type: "image/png" }), /4 MB/);
  await assert.rejects(encodeImage({ size: 10, type: "image/svg+xml" }), /PNG/);
  const file = new File([new Uint8Array([1, 2, 3])], "test.png", { type: "image/png" });
  assert.deepEqual(await encodeImage(file), { content_base64: "AQID" });
});
