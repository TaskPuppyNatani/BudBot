export const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const FLAGS = ["directions_enabled", "faq_enabled", "payments_info_enabled", "policies_info_enabled", "products_enabled", "promotions_enabled"];
export const OVERRIDE_FIELDS = ["display_name", "greeting", "fallback_message", "enabled"];

export function hoursRows(hours = []) {
  return DAYS.map((_, day) => {
    const entry = hours.find(item => item.day_of_week === day);
    return { day_of_week: day, state: !entry ? "unconfigured" : entry.is_closed ? "closed" : "open",
      open_time: entry?.open_time || "", close_time: entry?.close_time || "" };
  });
}
export function hoursPayload(rows) {
  return rows.filter(row => row.state !== "unconfigured").map(row => {
    if (row.state === "closed") return { day_of_week: row.day_of_week, is_closed: true };
    if (!row.open_time || !row.close_time || row.open_time >= row.close_time)
      throw new Error(`${DAYS[row.day_of_week]} needs an opening time earlier than its closing time.`);
    return { day_of_week: row.day_of_week, is_closed: false, open_time: row.open_time, close_time: row.close_time };
  });
}
export function overridePatch(original, values) {
  const patch = {};
  for (const field of OVERRIDE_FIELDS) {
    const control = values[field];
    const value = control.mode === "inherit" ? null : field === "enabled" ? control.value === "true" : control.value;
    if (value !== (original?.[field] ?? null)) patch[field] = value;
  }
  return patch;
}
export function previewUrl(businessId) {
  return `/widget/?business_id=${encodeURIComponent(businessId)}`;
}
export function brandAssetUrl(reference) {
  if (typeof reference !== "string" || !/^\/(?:local-assets|assets\/branding)\/[0-9a-f-]{36}\/[0-9a-f]{32}\.(png|jpg|webp)$/.test(reference)) return null;
  return reference.replace("/local-assets/", "/assets/branding/");
}
export async function encodeImage(file) {
  if (!file) return null;
  if (file.size < 1 || file.size > 4 * 1024 * 1024) throw new Error("Choose an image no larger than 4 MB.");
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) throw new Error("Use a PNG, JPG, or WebP image.");
  const bytes = new Uint8Array(await file.arrayBuffer());
  let text = "";
  for (let start = 0; start < bytes.length; start += 8192)
    text += String.fromCharCode(...bytes.subarray(start, start + 8192));
  return { content_base64: btoa(text) };
}
