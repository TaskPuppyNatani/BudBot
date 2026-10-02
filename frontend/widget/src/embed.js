export function matchingCommands(commands, input) {
  const query = input.trim().toLowerCase();
  if (!query.startsWith("/")) return [];
  return commands.filter((item) => item.available && (
    `/${item.name}`.startsWith(query) || item.aliases.some((alias) => `/${alias}`.startsWith(query))
  ));
}

export function needsAgeGate(profile, session) {
  return profile.requires_age_gate && session.age_gate_status !== "VERIFIED";
}

export function safeLocalAssetUrl(reference, apiBase) {
  if (typeof reference !== "string" || !reference.startsWith("/local-assets/")) return null;
  if (!/^\/local-assets\/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\/[0-9a-f]{32}\.(?:png|jpg|webp)$/.test(reference)) return null;
  try {
    const base = new URL(apiBase);
    const asset = new URL(reference, base);
    if (asset.origin !== base.origin || asset.search || asset.hash || asset.username || asset.password) return null;
    return asset.href;
  } catch {
    return null;
  }
}

export function widgetBootstrapConfig(element, defaultApiBase) {
  return {
    businessId: element.getAttribute("business-id") || "",
    apiBase: (element.getAttribute("api-base") || defaultApiBase).replace(/\/$/, ""),
  };
}

export function chatAvatarReference(businessLogoReference, assistantAvatarReference) {
  return assistantAvatarReference || businessLogoReference || null;
}

const css = `
:host{font:14px system-ui,sans-serif;color:#18202c;--brand:#54f575;--brand-text:#10151e}
*{box-sizing:border-box}
.panel{width:min(380px,calc(100vw - 32px));height:min(590px,82vh);min-height:420px;display:flex;flex-direction:column;border:1px solid color-mix(in srgb,var(--brand),#121725 45%);border-radius:18px;overflow:hidden;background:#10141e;box-shadow:0 14px 44px #090c18aa}
.head{min-height:78px;padding:13px 15px;background:linear-gradient(115deg,color-mix(in srgb,var(--brand),#161c2d 36%),#17213a);color:#fff;display:flex;align-items:center;gap:11px}
.business-logo-wrap{width:48px;height:48px;flex:0 0 48px;border-radius:14px;background:#ecf0f7;display:grid;place-items:center;overflow:hidden;color:#24314b;font-weight:800}
.business-logo{width:100%;height:100%;object-fit:contain}.business-logo[hidden]{display:none}.business-name{font-weight:750;font-size:15px;line-height:1.2;overflow-wrap:anywhere}.business-subtitle{font-size:12px;color:#d4ddf0;margin-top:4px}
.loc{margin-left:auto;max-width:135px;padding:7px;border:1px solid #ffffff70;border-radius:8px;background:#111a2c;color:#fff}
.messages{flex:1;overflow:auto;padding:13px 12px;background:radial-gradient(ellipse at top right,#263b3129,transparent 50%),#131824}
.message-row{display:flex;align-items:flex-end;gap:8px;margin:9px 0}.message-row.mine{justify-content:flex-end}.bubble{max-width:86%;white-space:pre-wrap;overflow-wrap:anywhere;padding:10px 12px;border-radius:13px;background:#222a3c;color:#f4f6ff;border:1px solid #ffffff12}.mine .bubble{background:color-mix(in srgb,var(--brand),#142238 65%);color:#fff}.error .bubble{color:#ffb5c2;border-color:#ff648355}
.assistant-avatar{width:30px;height:30px;flex:0 0 30px;border-radius:50%;object-fit:cover;border:1px solid var(--brand);background:#242c40}.assistant-avatar[hidden]{display:none}.avatar-fallback{width:30px;height:30px;flex:0 0 30px;border-radius:50%;display:grid;place-items:center;color:#c7a4ff;border:1px solid #8b38ff;background:#231936;font-weight:700}
.stage{min-height:95px}.controls{padding:12px;background:#151b29;border-top:1px solid #293247}.row{display:flex;gap:8px}.row input{flex:1;min-width:0;padding:11px 12px;border:1px solid #39435a;border-radius:10px;background:#1d2536;color:#fff;outline:none}.row input:focus{border-color:var(--brand)}.row button,button{padding:10px 14px;border:0;border-radius:9px;background:var(--brand);color:var(--brand-text);font-weight:700;cursor:pointer}.loc{padding:7px;border-radius:7px}.suggest{font-size:12px;color:#c9d3e7;padding:3px 2px 8px;min-height:17px}.gate{padding:18px;color:#fff}.gate label{display:block;margin:14px 0}.status{padding:12px;color:#d0d7e7;font-size:12px}.status.error{color:#ff899e}.powered{font-size:10px;color:#aab4c8;text-align:center;padding:5px 0 8px;background:#151b29}
`;

export class BudBotWidget extends (globalThis.HTMLElement || class {}) {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    Object.assign(this, widgetBootstrapConfig(this, location.origin));
    this.session = null;
    this.commands = [];
    this.shadowRoot.innerHTML = `<style>${css}</style><section class="panel"><header class="head"><div class="business-logo-wrap"><span class="business-initial">B</span><img class="business-logo" alt="" hidden></div><div class="identity"><div class="business-name">Your Business</div><div class="business-subtitle">Ask us anything</div></div><select class="loc" aria-label="Choose location" hidden></select></header><div class="messages" aria-live="polite"></div><div class="stage"><div class="status">Loading assistant…</div></div><div class="powered">Powered by BudBot</div></section>`;
  }
  connectedCallback() { this.initialize().catch((error) => this.fail(error)); }
  $(selector) { return this.shadowRoot.querySelector(selector); }

  async api(path, options = {}) {
    const response = await fetch(`${this.apiBase}${path}`, {
      ...options,
      credentials: "omit",
      headers: { "Content-Type": "application/json", "X-BudBot-Business-ID": this.businessId, ...(options.headers || {}) },
    });
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try { detail = (await response.json()).detail || detail; } catch {}
      throw new Error(typeof detail === "string" ? detail : "The assistant is temporarily unavailable.");
    }
    return response.json();
  }

  setBusinessLogo(reference) {
    const image = this.$(".business-logo");
    const safeUrl = safeLocalAssetUrl(reference, this.apiBase);
    image.hidden = true;
    this.$(".business-initial").hidden = false;
    if (!safeUrl) return;
    image.onload = () => { image.hidden = false; this.$(".business-initial").hidden = true; };
    image.onerror = () => { image.hidden = true; this.$(".business-initial").hidden = false; };
    image.src = safeUrl;
  }

  setBrandColor(color) {
    if (typeof color === "string" && /^#[0-9a-fA-F]{6}$/.test(color)) this.style.setProperty("--brand", color);
  }

  async initialize() {
    // `customElements.define` can run before the preview bootstrap creates the
    // element, so reflect attributes after they have been applied.
    Object.assign(this, widgetBootstrapConfig(this, location.origin));
    if (!this.businessId) throw new Error("Open the widget preview from BudBot Control Center.");
    this.session = await this.api("/api/v1/sessions", { method: "POST", body: JSON.stringify({}) });
    const { locations } = await this.loadConfiguration();
    const select = this.$("select.loc");
    if (locations.length > 1) {
      select.hidden = false;
      select.innerHTML = `<option value="">Choose a location…</option>`;
      for (const item of locations) {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = item.display_name;
        select.append(option);
      }
      select.addEventListener("change", () => this.chooseLocation(select.value).catch((error) => this.fail(error)));
      this.$(".status").textContent = "Choose a location to start chatting.";
    } else {
      await this.chooseLocation(locations[0]?.id || null);
    }
  }

  async loadConfiguration() {
    const data = await this.api(`/api/v1/sessions/${this.session.id}/widget`);
    const { business, assistant, compliance } = data;
    this.business = business;
    this.compliance = compliance;
    this.assistant = assistant;
    this.$(".business-name").textContent = business.display_name;
    this.$(".business-initial").textContent = (business.display_name || "B").trim().slice(0, 1).toUpperCase();
    this.$(".business-subtitle").textContent = `Ask ${assistant.display_name} anything`;
    this.setBusinessLogo(business.logo_reference);
    this.setBrandColor(assistant.primary_color || business.primary_brand_color);
    return data;
  }

  async chooseLocation(id) {
    if (!id && this.$("select.loc").options.length > 1) return;
    if (this.session) {
      this.session = await this.api(`/api/v1/sessions/${this.session.id}/location`, { method: "PATCH", body: JSON.stringify({ selected_location_id: id }) });
    } else {
      this.session = await this.api("/api/v1/sessions", { method: "POST", body: JSON.stringify({ selected_location_id: id }) });
    }
    await this.loadConfiguration();
    this.commands = await this.api(`/api/v1/commands?session_id=${this.session.id}`);
    if (needsAgeGate(this.compliance, this.session)) this.showGate();
    else this.showChat();
  }

  showGate() {
    const notice = this.compliance.website_attestation_notice;
    this.$(".stage").innerHTML = `<div class="gate"><strong>Age confirmation required</strong><p class="notice"></p><label><input type="checkbox"> I confirm I meet the required age.</label><button class="confirm">Continue</button><p class="status" role="status"></p></div>`;
    this.$(".notice").textContent = notice;
    this.$(".confirm").addEventListener("click", async () => {
      try {
        if (!this.$(".gate input").checked) throw new Error("Please confirm before continuing.");
        this.session = await this.api(`/api/v1/sessions/${this.session.id}/age-attestation`, { method: "POST", body: JSON.stringify({ confirmed_21_or_older: true }) });
        this.showChat();
      } catch (error) { this.$(".gate .status").textContent = error.message; }
    });
  }

  showChat() {
    this.$(".stage").innerHTML = `<div class="controls"><div class="suggest" aria-live="polite"></div><form class="row"><input aria-label="Message" autocomplete="off" placeholder="Ask a question or type /help"><button>Send</button></form></div>`;
    const input = this.$(".controls input");
    input.addEventListener("input", () => {
      const items = matchingCommands(this.commands, input.value);
      this.$(".suggest").textContent = items.slice(0, 6).map((item) => `/${item.name} — ${item.description}`).join(" · ");
    });
    this.$("form").addEventListener("submit", (event) => { event.preventDefault(); this.send(input).catch((error) => this.fail(error)); });
    this.addMessage(this.assistant.greeting || `Hi, I’m ${this.assistant.display_name}.`);
  }

  addMessage(text, mine = false, error = false) {
    const row = document.createElement("div");
    row.className = `message-row${mine ? " mine" : ""}${error ? " error" : ""}`;
    if (!mine) {
      const avatarReference = chatAvatarReference(
        this.business.logo_reference,
        this.assistant.avatar_reference,
      );
      const imageUrl = safeLocalAssetUrl(avatarReference, this.apiBase);
      if (imageUrl) {
        const avatar = document.createElement("img");
        avatar.className = "assistant-avatar";
        avatar.alt = "";
        avatar.src = imageUrl;
        avatar.onerror = () => avatar.remove();
        row.append(avatar);
      } else {
        const fallback = document.createElement("span");
        fallback.className = "avatar-fallback";
        fallback.setAttribute("aria-hidden", "true");
        fallback.textContent = (this.assistant.display_name || "B").trim().slice(0, 1).toUpperCase();
        row.append(fallback);
      }
    }
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    row.append(bubble);
    this.$(".messages").append(row);
    this.$(".messages").scrollTop = this.$(".messages").scrollHeight;
  }

  async send(input) {
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    this.addMessage(message, true);
    try {
      const result = message.startsWith("/")
        ? await this.api("/api/v1/commands/execute", { method: "POST", body: JSON.stringify({ session_id: this.session.id, input: message }) })
        : await this.api("/api/v1/chat", { method: "POST", body: JSON.stringify({ session_id: this.session.id, message }) });
      this.addMessage(result.output ?? result.content ?? "");
    } catch (error) { this.addMessage(error.message || "The assistant is temporarily unavailable.", false, true); }
  }

  fail(error) {
    const status = this.$(".status");
    if (status) { status.className = "status error"; status.textContent = error.message || "Unable to load the assistant."; }
  }
}

if (typeof customElements !== "undefined" && !customElements.get("budbot-widget")) customElements.define("budbot-widget", BudBotWidget);
if (typeof document !== "undefined") {
  const script = document.querySelector("script[data-business-id][src*='embed.js']");
  if (script) {
    const widget = document.createElement("budbot-widget");
    widget.setAttribute("business-id", script.dataset.businessId);
    if (script.dataset.apiBase) widget.setAttribute("api-base", script.dataset.apiBase);
    script.insertAdjacentElement("afterend", widget);
  }
}
