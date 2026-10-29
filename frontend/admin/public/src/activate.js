const root = typeof document === "undefined" ? null : document.getElementById("activation");
const node = (tag, text = "", attrs = {}) => {
  const element = document.createElement(tag);
  element.textContent = text;
  for (const [key, value] of Object.entries(attrs)) element[key] = value;
  return element;
};
const request = async (path, payload, csrf = null) => {
  const response = await globalThis.fetch.call(globalThis, path, {
    method: "POST", credentials: "same-origin", cache: "no-store",
    headers: { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}) },
    body: JSON.stringify(payload),
  });
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : "This invitation can’t be used. Ask the business owner for a new link.");
  return body;
};

export async function startActivation(target = root, browser = globalThis) {
  if (!target) return;
  let token = browser.location.hash.slice(1);
  browser.history.replaceState(null, "", `${browser.location.pathname}${browser.location.search}`);
  target.replaceChildren();
  const card = node("section", "", { className: "card login" });
  card.append(node("h1", "Join a BudBot business"));
  target.append(card);
  if (!token) { card.append(node("p", "This invitation can’t be used. Ask the business owner for a new link.", { role: "alert" })); return; }
  let invite;
  try { invite = await request("/api/v1/invitations/inspect", { token }); }
  catch (error) { token = ""; card.append(node("p", error.message, { role: "alert" })); return; }
  card.append(node("p", `You’re invited to join ${invite.business_name} as ${({ owner: "an owner", admin: "an admin", manager: "a manager", viewer: "a viewer" })[invite.role] || "a team member"}.`));
  card.append(node("p", `This invitation is for ${invite.email}.`));
  const newForm = node("form", "", { className: "card" });
  newForm.append(node("h2", "New to BudBot?"));
  const nameLabel = node("label", "", { className: "field" }); nameLabel.append(node("span", "Your name"));
  const name = node("input", "", { type: "text", required: true, maxLength: 200, autocomplete: "name" }); nameLabel.append(name);
  const passwordLabel = node("label", "", { className: "field" }); passwordLabel.append(node("span", "Choose a password (at least 12 characters)"));
  const password = node("input", "", { type: "password", required: true, minLength: 12, maxLength: 1024, autocomplete: "new-password" }); passwordLabel.append(password);
  const repeatLabel = node("label", "", { className: "field" }); repeatLabel.append(node("span", "Confirm password"));
  const repeat = node("input", "", { type: "password", required: true, minLength: 12, maxLength: 1024, autocomplete: "new-password" }); repeatLabel.append(repeat);
  const newStatus = node("p", "", { className: "status", role: "status", "aria-live": "polite" });
  const newSubmit = node("button", "Create account and join", { type: "submit" });
  newForm.append(nameLabel, passwordLabel, repeatLabel, newStatus, newSubmit);
  newForm.addEventListener("submit", async event => {
    event.preventDefault();
    if (password.value !== repeat.value) { newStatus.textContent = "Those passwords don’t match. Try again."; password.value = ""; repeat.value = ""; return; }
    newSubmit.disabled = true; newStatus.textContent = "Creating your account…";
    try {
      await request("/api/v1/invitations/accept/new", { token, display_name: name.value.trim(), password: password.value });
      token = ""; password.value = ""; repeat.value = "";
      newStatus.textContent = "Your account is ready. Go to the BudBot sign-in page to continue.";
      const signIn = node("a", "Sign in to BudBot", { href: "/admin/" }); newForm.append(signIn);
    } catch (error) { newStatus.textContent = error.message; }
    finally { newSubmit.disabled = false; password.value = ""; repeat.value = ""; }
  });
  card.append(newForm);

  const existingForm = node("form", "", { className: "card" });
  existingForm.append(node("h2", "Already have a BudBot account?"));
  const emailLabel = node("label", "", { className: "field" }); emailLabel.append(node("span", "Email"));
  const email = node("input", "", { type: "email", required: true, maxLength: 320, autocomplete: "username", value: invite.email }); emailLabel.append(email);
  const existingPasswordLabel = node("label", "", { className: "field" }); existingPasswordLabel.append(node("span", "Password"));
  const existingPassword = node("input", "", { type: "password", required: true, maxLength: 1024, autocomplete: "current-password" }); existingPasswordLabel.append(existingPassword);
  const existingStatus = node("p", "", { className: "status", role: "status", "aria-live": "polite" });
  const existingSubmit = node("button", "Sign in and accept invitation", { type: "submit" });
  existingForm.append(emailLabel, existingPasswordLabel, existingStatus, existingSubmit);
  existingForm.addEventListener("submit", async event => {
    event.preventDefault(); existingSubmit.disabled = true; existingStatus.textContent = "Signing in…";
    let session;
    try {
      session = await request("/api/v1/auth/login", { email: email.value, password: existingPassword.value });
      existingPassword.value = "";
      if (session.user.email.trim().toLowerCase() !== invite.email.trim().toLowerCase()) {
        await request("/api/v1/auth/logout", {}, session.csrf_token);
        throw new Error("Sign in using the account invited to this business.");
      }
      await request("/api/v1/invitations/accept", { token }, session.csrf_token);
      token = ""; existingStatus.textContent = "You’ve joined the business. Open the BudBot dashboard to continue.";
      existingForm.append(node("a", "Open BudBot", { href: "/admin/" }));
    } catch (error) { existingStatus.textContent = error.message; }
    finally { existingPassword.value = ""; existingSubmit.disabled = false; }
  });
  card.append(existingForm);
}

if (root) startActivation();
