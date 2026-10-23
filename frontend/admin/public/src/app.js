import { AdminClient } from "./client.js";
import { DAYS, FLAGS, OVERRIDE_FIELDS, hoursRows, hoursPayload, overridePatch, previewUrl, brandAssetUrl, encodeImage } from "./forms.js";

export class AdminApp {
  constructor(root, api = new AdminClient(), { confirm = globalThis.confirm, open = globalThis.open } = {}) {
    this.root = root; this.document = root.ownerDocument; this.api = api;
    this.confirm = confirm; this.open = open; this.controls = [];
    this.busy = false; this.dirty = false; this.tab = "Business";
    this.businessId = null; this.locationId = null; this.newLocation = false;
    this.message = ""; this.failed = false;
    this.runtime = null; this.shutdownState = null;
    this.resetManagementData();
  }
  node(tag, text = "", attributes = {}) {
    const node = this.document.createElement(tag);
    if (text) node.textContent = text;
    for (const [key, value] of Object.entries(attributes)) {
      if (key.startsWith("aria-") || key.startsWith("data-")) node.setAttribute(key, value);
      else node[key] = value;
    }
    return node;
  }
  control(node, permission = null, condition = () => true) {
    this.controls.push({ node, permission, condition });
    return node;
  }
  updateControls() {
    for (const { node, permission, condition } of this.controls)
      node.disabled = this.busy || (permission && !this.api.can(this.businessId, permission)) || !condition();
  }
  button(text, action, permission = null, className = "") {
    const button = this.control(this.node("button", text, { type: "button", className }), permission);
    button.addEventListener("click", () => { this.task = action(); });
    return button;
  }
  field(parent, label, value, { type = "text", permission = null, required = false, options = null, condition, trackChanges = true, maxLength = 250 } = {}) {
    const wrapper = this.node("label", "", { className: "field" });
    wrapper.append(this.node("span", label));
    const tag = options ? "select" : type === "textarea" ? "textarea" : "input";
    const input = this.control(this.node(tag), permission, condition);
    if (tag === "input") input.type = type;
    if (options) for (const [id, name] of options) input.append(this.node("option", name, { value: id }));
    if (type === "checkbox") input.checked = Boolean(value);
    else input.value = value ?? "";
    input.required = required;
    if (tag !== "select") input.maxLength = maxLength;
    if (trackChanges) {
      input.addEventListener("input", () => { this.dirty = true; });
      input.addEventListener("change", () => { this.dirty = true; });
    }
    wrapper.append(input); parent.append(wrapper);
    return input;
  }
  form(title, permission, submit) {
    const form = this.node("form", "", { className: "card" });
    form.append(this.node("h2", title));
    if (!this.api.can(this.businessId, permission)) form.append(this.node("p", "You have read-only access to this section.", { className: "muted" }));
    form.addEventListener("submit", event => {
      event.preventDefault();
      if (this.busy || !this.api.can(this.businessId, permission)) return;
      this.task = this.run(submit, "Saved. Reloaded the current configuration.");
    });
    return form;
  }
  saveButton(form, permission, text = "Save changes") {
    const button = this.control(this.node("button", text, { type: "submit" }), permission);
    form.append(button);
  }
  path(suffix = "") { return `/api/v1/businesses/${encodeURIComponent(this.businessId)}${suffix}`; }
  discard() { return !this.dirty || this.confirm.call(globalThis, "Discard unsaved changes?"); }
  notice() {
    if (this.status) {
      this.status.textContent = this.message;
      this.status.setAttribute("data-error", String(this.failed));
    }
  }
  openPreview() {
    try {
      // Call synchronously within the click gesture, with Window as receiver.
      const preview = this.open.call(globalThis, previewUrl(this.businessId), "_blank", "noopener,noreferrer");
      // noopener may return null even on success; do not claim it was blocked
      // or opened. Keep actionable guidance visible when there is no handle.
      this.message = preview ? "Customer preview opened in a separate tab."
        : "Customer preview requested. If no tab opened, allow popups for BudBot and try again.";
      this.failed = false;
    } catch {
      this.message = "Could not open customer preview. Allow popups for BudBot and try again.";
      this.failed = true;
    }
    this.notice();
  }
  async run(operation, success = "") {
    if (this.busy) return;
    this.busy = true; this.failed = false; this.message = "Working…";
    this.notice(); this.updateControls();
    try {
      const result = await operation();
      this.message = result === false ? "Cancelled." : success; this.failed = false;
    } catch (error) {
      this.message = error.message || "The operation failed. Please retry."; this.failed = true;
      if (error.status === 401) { this.businessId = null; this.dirty = false; this.renderLogin(); }
      else if (this.api.session && !this.businessId) this.render();
    } finally {
      this.busy = false; this.notice(); this.updateControls();
      if (this.businessSelect) this.businessSelect.value = this.businessId || "";
      if (this.locationSelect) this.locationSelect.value = this.locationId || "";
    }
  }
  async start() {
    // A failed initial request must still leave visible errors and enabled
    // recovery controls, rather than the static "Loading" shell.
    this.renderLogin();
    await this.run(async () => {
      await this.api.restore();
      const first = this.api.session.businesses[0];
      if (first) await this.loadBusiness(first.business_id);
      this.render();
    });
  }
  async loadBusiness(id = this.businessId, selectedLocation = this.locationId) {
    this.runtime = null;
    this.resetManagementData();
    if (this.managementPanel) this.managementPanel.replaceChildren(this.node("p", "Loading selected business…"));
    const base = `/api/v1/businesses/${encodeURIComponent(id)}`;
    const [business, assistant, locations, compliance] = await Promise.all([
      this.api.request(base), this.api.request(`${base}/assistant`),
      this.api.request(`${base}/locations?include_inactive=true`), this.api.request(`${base}/compliance-profile`),
    ]);
    const location = locations.find(item => item.id === selectedLocation) || locations.find(item => item.active) || locations[0];
    const detail = location ? await this.locationData(base, location.id) : {};
    Object.assign(this, { businessId: id, business, assistant, locations, compliance, locationId: location?.id || null, ...detail });
    this.newLocation = false; this.dirty = false;
    if (this.api.can(id, "runtime.shutdown")) {
      try { this.runtime = await this.api.request(`${base}/local-runtime`); }
      catch (error) { if (error.status === 401) throw error; }
    }
    if (this.tab === "System" && !this.runtime?.available) this.tab = "Business";
    await this.loadManagementPanel();
  }
  resetManagementData() {
    this.providerProfile = null;
    this.faqs = []; this.editFaqId = null; this.auditPage = null;
    this.auditOffset = 0; this.panelError = ""; this.panelLoaded = false;
  }
  async loadManagementPanel(offset = 0) {
    const id = this.businessId;
    const permission = this.tab === "FAQs" ? "faq.read" : this.tab === "Audit History" ? "audit.read" : this.tab === "AI Provider" ? "provider.read" : null;
    this.panelError = ""; this.panelLoaded = false;
    if (!permission || !this.api.can(id, permission)) return;
    try {
      const result = await this.api.request(this.path(this.tab === "FAQs" ? "/faqs" : this.tab === "AI Provider" ? "/provider" : `/audit?limit=25&offset=${offset}`));
      if (id !== this.businessId) return;
      if (this.tab === "FAQs") this.faqs = result;
      else if (this.tab === "AI Provider") this.providerProfile = result;
      else { this.auditPage = result; this.auditOffset = offset; }
      this.panelLoaded = true;
    } catch (error) {
      if (error.status === 401) throw error;
      this.panelError = error.message || "Could not load this section. Reload settings to retry.";
    }
  }
  async locationData(base, id) {
    const [override, effectiveAssistant, effectiveCompliance] = await Promise.all([
      this.api.request(`${base}/locations/${id}/assistant-override`),
      this.api.request(`${base}/locations/${id}/effective-assistant`),
      this.api.request(`${base}/compliance-profile/locations/${id}`),
    ]);
    return { override, effectiveAssistant, effectiveCompliance };
  }
  renderLogin() {
    this.runtime = null;
    this.resetManagementData(); this.managementPanel = null;
    this.controls = []; this.businessSelect = null; this.locationSelect = null;
    const form = this.node("form", "", { className: "card login" });
    form.append(this.node("h1", "Sign in to BudBot"), this.node("p", "Use your owner or authorized business account. Browser sign-in is separate from Control Center."));
    const email = this.field(form, "Email", "", { type: "email", required: true, maxLength: 320 });
    email.autocomplete = "username";
    const password = this.field(form, "Password", "", { type: "password", required: true, maxLength: 1024 });
    password.autocomplete = "current-password";
    this.status = this.node("p", "", { className: "status", role: "status", "aria-live": "polite" });
    form.append(this.status, this.control(this.node("button", "Sign in", { type: "submit" })));
    form.addEventListener("submit", event => {
      event.preventDefault();
      this.task = this.run(async () => {
        try { await this.api.login(email.value, password.value); }
        finally { password.value = ""; }
        const first = this.api.session.businesses[0];
        if (first) await this.loadBusiness(first.business_id);
        this.render();
      });
    });
    this.root.replaceChildren(form); this.updateControls(); this.notice();
  }
  render() {
    if (this.shutdownState) {
      this.controls = []; this.businessSelect = null; this.locationSelect = null; this.status = null;
      const panel = this.node("section", "", { className: "card", role: "status", "aria-live": "polite" });
      panel.append(this.node("h1", "Local BudBot runtime"));
      panel.append(this.node("p", this.shutdownState === "requesting" ? "Requesting local shutdown…"
        : this.shutdownState === "accepted" ? "BudBot is shutting down. You can close this tab."
        : "The connection closed before shutdown could be confirmed. BudBot may be shutting down. You can close this tab; relaunch BudBot to check."));
      panel.append(this.node("p", "To launch again, run scripts/start_budbot.sh. Saved data is preserved."));
      this.root.replaceChildren(panel); return;
    }
    if (!this.api.session) { this.renderLogin(); return; }
    this.controls = []; this.locationSelect = null;
    const fragment = this.node("div");
    fragment.append(this.node("h1", "Business management"));
    const toolbar = this.node("div", "", { className: "toolbar" });
    this.businessSelect = this.field(toolbar, "Business", this.businessId, { trackChanges: false, options: this.api.session.businesses.map(item => [item.business_id, item.display_name]) });
    this.businessSelect.addEventListener("change", () => {
      const id = this.businessSelect.value;
      if (!this.discard()) { this.businessSelect.value = this.businessId; return; }
      this.task = this.run(async () => { await this.loadBusiness(id, null); this.render(); });
    });
    toolbar.append(this.node("span", `${this.api.session.user.email} · ${this.api.session.businesses.find(item => item.business_id === this.businessId)?.role || "No business access"}`));
    toolbar.append(this.button("Sign out", async () => {
      if (!this.discard()) return;
      await this.run(async () => { await this.api.logout(); this.businessId = null; this.dirty = false; this.renderLogin(); }, "Signed out.");
    }));
    if (this.businessId) toolbar.append(this.button("Reload settings", async () => {
      if (!this.discard()) return;
      await this.run(async () => { await this.loadBusiness(); this.render(); }, "Reloaded current settings.");
    }));
    fragment.append(toolbar);
    this.status = this.node("p", "", { className: "status", role: "status", "aria-live": "polite" }); fragment.append(this.status);
    if (!this.businessId) {
      fragment.append(this.node("p", this.api.session.businesses.length
        ? "Choose a business to load its settings."
        : "No active business memberships are available. Contact your business owner."));
      this.root.replaceChildren(fragment); this.updateControls(); return;
    }
    const nav = this.node("nav", "", { "aria-label": "Management sections" });
    const sections = ["Business", "Locations", "Assistant", "Compliance", "Branding", "FAQs", "Audit History", "AI Provider"];
    if (this.runtime?.available && this.api.can(this.businessId, "runtime.shutdown")) sections.push("System");
    for (const title of sections) {
      const button = this.button(title, () => {
        if (!this.discard()) return;
        this.dirty = false; this.tab = title;
        if (["FAQs", "Audit History", "AI Provider"].includes(title)) return this.run(async () => {
          this.resetManagementData(); this.render();
          await this.loadManagementPanel(); this.render();
        });
        this.render();
      });
      if (title === this.tab) button.setAttribute("aria-current", "page");
      nav.append(button);
    }
    nav.append(this.button("Customer preview", () => this.openPreview(), "business.read"));
    fragment.append(nav, this.node("p", "Customer preview creates a separate customer session and applies the normal location and age checks.", { className: "muted" }));
    if (["Locations", "Assistant", "Compliance"].includes(this.tab)) {
      const selection = this.node("div", "", { className: "toolbar" });
      this.locationSelect = this.field(selection, "Location", this.locationId, { trackChanges: false, options: [["", "Select a location"], ...this.locations.map(item => [item.id, `${item.display_name}${item.active ? "" : " (inactive)"}`])] });
      this.locationSelect.addEventListener("change", () => {
        const id = this.locationSelect.value;
        if (!id || !this.discard()) { this.locationSelect.value = this.locationId || ""; return; }
        this.task = this.run(async () => {
          const detail = await this.locationData(this.path(), id);
          Object.assign(this, { locationId: id, ...detail }); this.newLocation = false; this.dirty = false; this.render();
        });
      });
      fragment.append(selection);
    }
    const builders = { Business: "businessForm", Locations: "locationForm", Assistant: "assistantForms", Compliance: "complianceView", Branding: "brandingForm", FAQs: "faqView", "Audit History": "auditView", "AI Provider": "providerView", System: "runtimeView" };
    const panel = this[builders[this.tab]]();
    this.managementPanel = ["FAQs", "Audit History", "AI Provider"].includes(this.tab) ? panel : null;
    fragment.append(panel);
    this.root.replaceChildren(fragment); this.updateControls(); this.notice();
  }
  runtimeView() {
    const section = this.node("section", "", { className: "card" });
    section.append(this.node("h2", "Local System / Runtime"));
    const state = this.runtime?.state;
    section.append(this.node("p", state === "stopping" ? "BudBot is shutting down. You can close this tab."
      : state === "error" ? "The last shutdown attempt failed. Check Docker and retry." : "BudBot status: Running"));
    section.append(this.node("p", "Shutdown stops this entire local development stack, including all businesses. Saved data is kept."));
    if (this.runtime?.available && state !== "stopping")
      section.append(this.button("Shut down BudBot", () => this.shutdownBudBot(), "runtime.shutdown"));
    return section;
  }
  async shutdownBudBot() {
    if (this.busy || !this.runtime?.available || !this.api.can(this.businessId, "runtime.shutdown")) return;
    if (!this.confirm.call(globalThis, "Shut down the local BudBot stack for all businesses? Saved data will be kept.")) return;
    this.busy = true; this.shutdownState = "requesting"; this.render();
    try {
      await this.api.mutate(this.path("/local-runtime/shutdown"), "POST", {});
      this.shutdownState = "accepted";
    } catch (error) {
      if ([0, 502].includes(error.status)) this.shutdownState = "disconnected";
      else {
        this.shutdownState = null; this.message = error.status ? error.message : "Shutdown was not accepted. Reload settings and retry."; this.failed = true;
        if (error.status === 401) { this.api.session = null; this.businessId = null; }
      }
    } finally {
      this.busy = false; this.render();
    }
  }
  listEditor(parent, title, entries, keys, permission) {
    const section = this.node("section"); section.append(this.node("h3", title));
    const list = this.node("div"); section.append(list);
    const rows = [];
    const add = values => {
      const row = this.node("div", "", { className: "entry" });
      const fields = Object.fromEntries(keys.map(([key, label]) => [key, this.field(row, label, values?.[key], { permission, required: key !== "details", type: key === "text" ? "textarea" : "text", maxLength: key === "text" ? 2000 : key === "details" ? 500 : 200 })]));
      const record = { row, fields }; rows.push(record);
      row.append(this.button("Remove", () => { rows.splice(rows.indexOf(record), 1); row.remove(); this.dirty = true; }, permission));
      list.append(row); this.updateControls();
    };
    for (const entry of entries || []) add(entry);
    section.append(this.button("Add entry", () => { add({}); this.dirty = true; }, permission));
    parent.append(section);
    return () => rows.map(({ fields }) => Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, input.value.trim() || (key === "details" ? null : "")])));
  }
  managementSection(title, permission) {
    const section = this.node("section", "", { className: "card" });
    section.append(this.node("h2", title));
    if (!this.api.can(this.businessId, permission)) {
      section.append(this.node("p", "You do not have permission to view this section."));
    } else if (this.panelError) section.append(this.node("p", this.panelError, { role: "alert" }));
    else if (!this.panelLoaded) section.append(this.node("p", "Loading…"));
    return section;
  }
  faqView() {
    const section = this.managementSection("FAQ management", "faq.read");
    if (!this.api.can(this.businessId, "faq.read") || !this.panelLoaded) return section;
    section.append(this.node("p", "Only enabled, public entries reach customers. Matching location questions override business-wide answers. Disable an entry to remove it from customer lookup; records are retained."));
    if (!this.faqs.length) section.append(this.node("p", "No FAQs yet."));
    for (const entry of this.faqs) {
      const card = this.node("article", "", { className: "card" });
      const scope = entry.location_id ? this.locations.find(item => item.id === entry.location_id)?.display_name || entry.location_id : "Business-wide";
      card.append(this.node("h3", entry.question), this.node("p", entry.answer),
        this.node("p", `${scope} · ${entry.enabled ? "Enabled" : "Disabled"} · ${entry.is_public ? "Public" : "Non-public"}`));
      card.append(this.button("Edit FAQ", () => {
        if (!this.discard()) return;
        this.editFaqId = entry.id; this.dirty = false; this.render();
      }, "faq.write"));
      section.append(card);
    }
    section.append(this.button("New FAQ", () => {
      if (!this.discard()) return;
      this.editFaqId = null; this.dirty = false; this.render();
    }, "faq.write"));
    const entry = this.faqs.find(item => item.id === this.editFaqId);
    let question, answer, location, enabled, isPublic;
    const permission = "faq.write";
    const form = this.form(entry ? "Edit FAQ" : "New FAQ", permission, async () => {
      const payload = { question: question.value.trim(), answer: answer.value.trim(),
        location_id: location.value || null, enabled: enabled.checked, is_public: isPublic.checked };
      await this.api.mutate(this.path(entry ? `/faqs/${entry.id}` : "/faqs"), entry ? "PATCH" : "POST", payload);
      this.dirty = false; this.editFaqId = null;
      await this.loadManagementPanel(); this.render();
    });
    question = this.field(form, "Question", entry?.question, { permission, required: true, maxLength: 500 });
    answer = this.field(form, "Answer", entry?.answer, { permission, required: true, type: "textarea", maxLength: 10000 });
    location = this.field(form, "FAQ scope", entry?.location_id || "", { permission,
      options: [["", "Business-wide"], ...this.locations.map(item => [item.id, `${item.display_name}${item.active ? "" : " (inactive)"}`])] });
    enabled = this.field(form, "FAQ enabled", entry?.enabled ?? true, { permission, type: "checkbox" });
    isPublic = this.field(form, "Public to customers", entry?.is_public ?? true, { permission, type: "checkbox" });
    this.saveButton(form, permission, entry ? "Save FAQ" : "Create FAQ");
    section.append(form); return section;
  }
  auditView() {
    const section = this.managementSection("Audit History", "audit.read");
    if (!this.api.can(this.businessId, "audit.read") || !this.panelLoaded) return section;
    section.append(this.node("p", "Business-scoped administrative history, newest first. Account-wide login/logout events are not attributed to a business and are excluded. Actor identifiers are account IDs."));
    if (!this.auditPage.items.length) section.append(this.node("p", "No audit events for this business."));
    for (const event of this.auditPage.items) {
      const card = this.node("article", "", { className: "card" });
      card.append(this.node("h3", event.event_type), this.node("p", event.created_at),
        this.node("p", `Actor: ${event.actor_user_id || "Unavailable"}`),
        this.node("p", `Resource: ${event.resource_type || "Unavailable"} ${event.resource_id || ""}`));
      for (const [key, value] of Object.entries(event.details || {})) card.append(this.node("p", `${key}: ${value ?? "Business-wide"}`));
      section.append(card);
    }
    const page = offset => this.run(async () => {
      this.auditPage = null; this.panelLoaded = false; this.render();
      await this.loadManagementPanel(offset); this.render();
    });
    if (this.auditOffset > 0) section.append(this.button("Newest events", () => page(0), "audit.read"));
    if (this.auditPage.next_offset !== null) section.append(this.button("Older events", () => page(this.auditPage.next_offset), "audit.read"));
    return section;
  }
  providerView() {
    const section = this.managementSection("AI Provider", "provider.read");
    if (!this.api.can(this.businessId, "provider.read") || !this.panelLoaded) return section;
    const profile = this.providerProfile; const permission = "provider.write";
    section.append(this.node("p", `Credential configured: ${profile.credential_configured ? "Yes" : "No"}. Existing credentials are never returned to this browser.`));
    section.append(this.node("p", "Save configuration disabled first, set the credential, then enable AI. Removing a credential disables AI. Remove the credential before changing provider identity."));
    let provider, model, endpoint, enabled, tools;
    const form = this.form("Provider configuration", permission, async () => {
      await this.api.mutate(this.path("/provider"), "PUT", { provider: provider.value, model: model.value.trim(), enabled: enabled.checked,
        base_url: provider.value === "openai_compatible" ? endpoint.value.trim() : null, tool_calling: tools.checked });
      await this.loadManagementPanel(); this.render();
    });
    provider = this.field(form, "Provider", profile.provider || "openrouter", { permission, options: [["openrouter", "OpenRouter"], ["openai_compatible", "LM Studio / OpenAI-compatible"], ["openai", "OpenAI"], ["anthropic", "Anthropic"]] });
    model = this.field(form, "Model identifier", profile.model, { permission, required: true, maxLength: 200 });
    endpoint = this.field(form, "Backend-reachable base URL", profile.base_url, { permission, maxLength: 2048, condition: () => provider.value === "openai_compatible" });
    const guide = this.node("p"); form.append(guide);
    const refresh = () => {
      endpoint.required = provider.value === "openai_compatible";
      guide.textContent = provider.value === "openai_compatible" ? "Use an endpoint reachable FROM the BudBot backend container. Container localhost points to BudBot itself. Local servers may not need a key." : "This provider uses its standard cloud endpoint and requires an API key.";
      this.updateControls();
    };
    provider.addEventListener("change", refresh); refresh();
    enabled = this.field(form, "AI enabled", profile.enabled, { permission, type: "checkbox" });
    tools = this.field(form, "Model supports tool calling", profile.tool_calling, { permission, type: "checkbox" });
    form.append(this.node("p", "Declare tool calling only when your selected model supports it. Customer chat requires verified tools; capabilities are not probed."));
    this.saveButton(form, permission, "Save provider configuration"); section.append(form);
    let credential;
    const secretForm = this.form("Replace provider credential", permission, async () => {
      try { await this.api.mutate(this.path("/provider/credential"), "PUT", { credential: credential.value }); }
      finally { credential.value = ""; }
      await this.loadManagementPanel(); this.render();
    });
    credential = this.field(secretForm, "New API key", "", { permission, type: "password", required: true, maxLength: 10000 });
    credential.autocomplete = "new-password";
    this.saveButton(secretForm, permission, "Set or replace credential");
    secretForm.append(this.button("Remove credential and disable AI", () => {
      if (!this.confirm.call(globalThis, "Remove this business's provider credential and disable AI?")) return;
      return this.run(async () => { await this.api.mutate(this.path("/provider/credential"), "DELETE"); await this.loadManagementPanel(); this.render(); }, "Credential removed; AI disabled.");
    }, permission));
    section.append(secretForm); return section;
  }
  businessForm() {
    const permission = "business.write"; let fields, flags, payments, policies;
    const form = this.form("Business settings", permission, async () => {
      const payload = Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, input.value.trim() || null]));
      for (const [key, input] of Object.entries(flags)) payload[key] = input.checked;
      payload.payment_methods = payments(); payload.store_policies = policies();
      await this.api.mutate(this.path(), "PATCH", payload); await this.loadBusiness(); this.render();
    });
    form.append(this.node("p", `Industry: ${this.business.industry} · Business status: ${this.business.active ? "Active" : "Inactive"}`));
    fields = Object.fromEntries([
      ["display_name", "Business name", true], ["legal_name", "Legal name"], ["website_url", "Website"], ["main_phone", "Main phone"], ["default_timezone", "Default timezone (IANA, e.g. America/Los_Angeles)"],
    ].map(([key, label, required]) => [key, this.field(form, label, this.business[key], { permission, required, maxLength: key === "display_name" ? 200 : key === "website_url" ? 2048 : 250 })]));
    form.append(this.node("h3", "Customer features"));
    flags = Object.fromEntries(FLAGS.map(key => [key, this.field(form, key.replace(/_/g, " "), this.business[key], { type: "checkbox", permission })]));
    payments = this.listEditor(form, "Payment information", this.business.payment_methods, [["name", "Method"], ["details", "Optional details"]], permission);
    policies = this.listEditor(form, "Store policies", this.business.store_policies, [["title", "Title"], ["text", "Policy"]], permission);
    this.saveButton(form, permission); return form;
  }
  locationForm() {
    const section = this.node("section"); const permission = "location.write";
    section.append(this.button("Create location", () => {
      if (!this.discard()) return;
      this.newLocation = true; this.locationId = null; this.dirty = false; this.render();
    }, permission));
    const location = this.newLocation ? null : this.locations.find(item => item.id === this.locationId);
    if (!location && !this.newLocation) { section.append(this.node("p", "No locations yet. Create one to configure its address and hours.")); return section; }
    let fields, rows;
    const form = this.form(location ? "Location settings" : "New location", permission, async () => {
      const payload = Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, input.value.trim() || null]));
      payload.hours = hoursPayload(rows.map(row => ({ day_of_week: row.day, state: row.state.value, open_time: row.open.value, close_time: row.close.value })));
      const saved = await this.api.mutate(location ? this.path(`/locations/${location.id}`) : this.path("/locations"), location ? "PATCH" : "POST", payload);
      await this.loadBusiness(this.businessId, saved.id); this.render();
    });
    const definitions = [["display_name", "Location name", true], ["address_line_1", "Address", true], ["address_line_2", "Address line 2"], ["city", "City", true], ["region", "Region (display name)", true], ["region_code", "Region code (2 letters; used for compliance)"], ["postal_code", "Postal code", true], ["country", "Country code (2 letters)", true], ["phone", "Phone"], ["timezone", "Timezone (IANA)", true], ["maps_place_id", "Maps place ID"], ["maps_destination", "Maps destination"]];
    const grid = this.node("div", "", { className: "grid" }); form.append(grid);
    fields = Object.fromEntries(definitions.map(([key, label, required]) => [key, this.field(grid, label, location?.[key] ?? (key === "timezone" ? this.business.default_timezone : ""), { permission, required, maxLength: key === "country" || key === "region_code" ? 2 : key === "maps_destination" ? 2048 : key === "display_name" ? 200 : 250 })]));
    form.append(this.node("h3", "Weekly hours"), this.node("p", "Unconfigured has no hours entry. Closed is an explicit closed day. Open requires an opening time before closing; overnight intervals are not supported."));
    rows = hoursRows(location?.hours).map(entry => {
      const row = this.node("div", "", { className: "hours-day" }); row.append(this.node("strong", DAYS[entry.day_of_week]));
      const state = this.field(row, "State", entry.state, { permission, options: [["unconfigured", "Unconfigured"], ["closed", "Closed"], ["open", "Open"]] });
      const open = this.field(row, "Opens", entry.open_time, { permission, type: "time", condition: () => state.value === "open" });
      const close = this.field(row, "Closes", entry.close_time, { permission, type: "time", condition: () => state.value === "open" }); open.step = close.step = 1;
      state.addEventListener("change", () => this.updateControls());
      form.append(row); return { day: entry.day_of_week, state, open, close };
    });
    this.saveButton(form, permission, location ? "Save location and hours" : "Create location");
    if (location) form.append(this.button(location.active ? "Deactivate location" : "Reactivate location", async () => {
      if (!this.confirm.call(globalThis, `${location.active ? "Deactivate" : "Reactivate"} ${location.display_name}?${location.active ? " It will no longer be selectable by customers." : ""}`)) return;
      await this.run(async () => {
        await this.api.mutate(location.active ? this.path(`/locations/${location.id}/deactivate`) : this.path(`/locations/${location.id}`), location.active ? "POST" : "PATCH", location.active ? undefined : { active: true });
        await this.loadBusiness(); this.render();
      }, "Location availability updated.");
    }, permission, "danger"));
    section.append(form); return section;
  }
  assistantForms() {
    const section = this.node("section"); const permission = "assistant.write"; let fields;
    const form = this.form("Business assistant defaults", permission, async () => {
      if (this.assistant.enabled && !fields.enabled.checked && !this.confirm.call(globalThis, "Disable the business assistant? This affects customer chat across locations using this default.")) return false;
      const payload = Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, key === "enabled" ? input.checked : input.value.trim() || null]));
      await this.api.mutate(this.path("/assistant"), "PATCH", payload); await this.loadBusiness(); this.render();
    });
    fields = Object.fromEntries([["display_name", "Assistant name"], ["greeting", "Greeting"], ["fallback_message", "Fallback message"], ["primary_color_override", "Assistant color override (#RRGGBB; blank inherits business color)"], ["enabled", "Assistant enabled"]].map(([key, label]) => [key, this.field(form, label, this.assistant[key], { permission, required: ["display_name", "greeting", "fallback_message"].includes(key), type: key === "enabled" ? "checkbox" : key.includes("greeting") || key === "fallback_message" ? "textarea" : "text", maxLength: key === "display_name" ? 200 : 1000 })]));
    this.saveButton(form, permission); section.append(form);
    if (!this.locationId) { section.append(this.node("p", "Select a location to inspect or edit its overrides.")); return section; }
    const values = {};
    const override = this.form("Location assistant overrides", permission, async () => {
      const patch = overridePatch(this.override, Object.fromEntries(OVERRIDE_FIELDS.map(key => [key, { mode: values[key].mode.value, value: values[key].value.value }])));
      if (!Object.keys(patch).length) throw new Error("No override changes to save.");
      await this.api.mutate(this.path(`/locations/${this.locationId}/assistant-override`), "PATCH", patch); await this.loadBusiness(); this.render();
    });
    for (const key of OVERRIDE_FIELDS) {
      const row = this.node("div", "", { className: "override" });
      const explicit = this.override?.[key] !== null && this.override?.[key] !== undefined;
      const mode = this.field(row, key.replace(/_/g, " "), explicit ? "override" : "inherit", { permission, options: [["inherit", "Inherit business default"], ["override", "Use explicit override"]] });
      const value = this.field(row, "Override value", explicit ? String(this.override[key]) : key === "enabled" ? String(this.effectiveAssistant.enabled) : "", { permission, options: key === "enabled" ? [["true", "Enabled"], ["false", "Disabled"]] : null, type: key === "greeting" || key === "fallback_message" ? "textarea" : "text", maxLength: key === "display_name" ? 200 : 1000, condition: () => mode.value === "override" });
      value.placeholder = String(this.effectiveAssistant[key]);
      mode.addEventListener("change", () => this.updateControls());
      row.append(this.node("p", `Current effective value: ${this.effectiveAssistant[key]}`, { className: "effective" }));
      values[key] = { mode, value }; override.append(row);
    }
    this.saveButton(override, permission, "Save explicit override changes"); section.append(override); return section;
  }
  complianceView() {
    const section = this.node("section", "", { className: "card" });
    section.append(this.node("h2", "Compliance visibility"), this.node("p", "Mandatory rules are enforced by BudBot. These views do not disable or override customer compliance checks."));
    const profile = (title, value) => {
      section.append(this.node("h3", title));
      if (!value) { section.append(this.node("p", "No applicable profile. Protected customer actions remain blocked.")); return; }
      for (const key of ["profile_id", "version", "jurisdiction", "compliance_domain", "minimum_age", "website_attestation_notice", "medical_eligibility_notice", "effective_from", "reviewed_at"])
        if (value[key] != null) section.append(this.node("p", `${key.replace(/_/g, " ")}: ${value[key]}`));
      section.append(this.node("p", `Age gate required: ${value.requires_age_gate ? "Yes" : "No"}`));
      const sources = this.node("ul", "", { className: "source-list" });
      for (const source of value.source_references || []) sources.append(this.node("li", source));
      section.append(sources);
    };
    profile("Configured business profile", this.compliance);
    if (this.locationId) {
      section.append(this.node("p", `Location resolution: ${this.effectiveCompliance.status} · ${this.effectiveCompliance.jurisdiction_code || "No jurisdiction"}${this.effectiveCompliance.location_active ? "" : " · Location inactive"}`));
      if (this.effectiveCompliance.reason_code) section.append(this.node("p", this.effectiveCompliance.reason_code));
      profile("Effective location profile", this.effectiveCompliance.profile);
    } else section.append(this.node("p", "Select a location to inspect effective compliance."));
    return section;
  }
  brandingForm() {
    const permission = "branding.write"; let logo, avatar, removeLogo, removeAvatar, color;
    const form = this.form("Published branding", permission, async () => {
      const payload = { primary_brand_color: color.value.trim() || null, remove_business_logo: removeLogo.checked, remove_assistant_avatar: removeAvatar.checked };
      const encodedLogo = await encodeImage(logo.files[0]); const encodedAvatar = await encodeImage(avatar.files[0]);
      if (encodedLogo) payload.business_logo = encodedLogo;
      if (encodedAvatar) payload.assistant_avatar = encodedAvatar;
      await this.api.mutate(this.path("/branding"), "PUT", payload); await this.loadBusiness(); this.render();
    });
    form.append(this.node("p", "PNG, JPG or WebP, up to 4 MB each; at most 8192 pixels per dimension and 16 megapixels. Saved images are published to customers. Metadata is removed."));
    for (const [name, reference] of [["Business logo", this.business.logo_reference], ["Assistant avatar", this.assistant.avatar_reference]]) {
      form.append(this.node("h3", name)); const url = brandAssetUrl(reference);
      if (url) form.append(this.node("img", "", { src: url, alt: name, className: "brand-image" }));
      else form.append(this.node("p", "No published image."));
    }
    logo = this.field(form, "Choose business logo", "", { type: "file", permission });
    avatar = this.field(form, "Choose assistant avatar", "", { type: "file", permission }); logo.accept = avatar.accept = "image/png,image/jpeg,image/webp";
    removeLogo = this.field(form, "Remove business logo", false, { type: "checkbox", permission });
    removeAvatar = this.field(form, "Remove assistant avatar", false, { type: "checkbox", permission });
    color = this.field(form, "Business color (#RRGGBB; blank clears)", this.business.primary_brand_color, { permission, maxLength: 7 });
    this.saveButton(form, permission, "Save branding"); return form;
  }
}

if (typeof document !== "undefined") {
  const root = document.getElementById("app");
  if (root) new AdminApp(root).start();
}
