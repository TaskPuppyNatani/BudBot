# BudBot administration (M9B Passes 1 and 2)

## V1 local Catalog

Admin → Catalog lets owners and admins add/edit products, enter a category by
name, and choose existing locations with their own price and availability.
Other business readers can inspect the catalog without changing it. Prices use
ordinary currency amounts; blank means not listed. No IDs or JSON are needed.
“Remove product from customers” hides the existing record and offers Restore;
it is not permanent deletion. The same area provides simple business/location
deals. Successful writes update the screen from the saved response immediately.
Customer visibility still depends on enabled flags, active selected location,
offered/available state, and the existing compliance rules. Catalog writes use
business.write with CSRF and tenant-scoped validation; audit stores metadata only.

A separate, dependency-free ES-module application served at `/admin/` by the
backend. Only `public/` is served or copied into the runtime Docker image. Tests
use Node's built-in assertions/test runner and a small DOM harness; there is no
package installation or build step.

```bash
npm --prefix frontend/admin test
npm --prefix frontend/admin run check
```

An additional native-browser login/coordination regression uses an already
available Playwright and Chromium runtime (no frontend build dependency):

```bash
npm --prefix frontend/admin run test:browser
```

Set `NODE_PATH` if Playwright is supplied by a shared runtime, and optionally
`BUDBOT_TEST_BROWSER_EXECUTABLE` to select its installed Chromium executable.
The test serves isolated synthetic HTTP responses; it does not use real accounts
or a running BudBot database. It checks native fetch, anonymous startup, invalid
credential retry, dashboard loading and same-origin Web Locks across two tabs.
Synchronous request-setup errors have a safe browser-client message and retain
their original `cause` for developer inspection; network failures stay generic.

Sign in with an account initialized through `python -m budbot.admin setup-owner`.
Browser authentication is separate from Control Center. The account response
supplies each membership's effective permissions from the central backend policy;
this client has no role-to-permission table. Server membership/permission checks
remain authoritative.

Sessions/CSRF tokens stay in memory. Requests use same-origin HttpOnly cookies,
not the development tenant header. There is no `/auth/me` polling. Foreground
writes refresh CSRF immediately before mutation, under a same-origin Web Lock
where supported. A CSRF rejection gets one bounded refresh/retry; permission
failures do not. Other browsers still serialize this tab's writes and recover
from CSRF changes with a bounded retry. A connection timeout never triggers an
automatic mutation retry: reload settings to check whether the write completed.
Successful login and `/auth/me` explicitly commit session/CSRF issuance before
returning the cookie/token; later request cleanup cannot expose uncommitted
security state. `/auth/me` still rotates the token, with only its digest stored.
Response construction failures roll back before this narrow commit boundary;
unrelated application transactions retain their normal rollback behavior.

Business settings, locations/hours, assistant defaults/overrides, compliance
visibility and branding reuse existing domain services. An inherited override is
sent as `null` only when explicitly clearing a prior override; opening a form
does not create anything. Hours distinguish unconfigured, closed and open days.
The UI deliberately does not offer business deactivation or compliance bypasses.

Branding saves use the protected `/api/v1/businesses/{business_id}/branding`
endpoint, not `/api/v1/local`. Uploads use bounded base64 JSON and the existing
image decoder/re-encoder. The server streams a bounded body after authentication,
strips metadata, and publishes only the active business's current logo/avatar at
`/assets/branding/{business_id}/{filename}`. Existing saved `/local-assets/`
references remain readable through that published route; the development alias
also checks publication instead of exposing the storage directory.

Preview opens `/widget/?business_id=...` with `noopener,noreferrer`. No owner
credentials or tokens are transferred. The widget creates a new public customer
session and uses its normal location/age/compliance flow. Customer API and
branding-image fetches use `credentials: "omit"`.

## Manual acceptance

1. Rebuild/restart the backend with the existing development Compose stack, then
   open `http://127.0.0.1:8000/admin/`. Sign in with the owner account.
2. Confirm the business selector contains only authorized businesses. With a
   multi-business account, switch businesses and verify that settings and the
   selected location change together.
3. Change the business name/contact/timezone, payment information and policies;
   save, reload settings, and reload the page. Verify the saved values.
4. Toggle products/promotions separately; save/reload and confirm persistence.
5. Create/edit a location. Enter canonical country/region codes and timezone.
   Configure one open day, one closed day and one unconfigured day. Save/reload;
   verify all three states. Reject an invalid interval. Confirm deactivation,
   verify it disappears from customer selection, then reactivate if needed.
6. Change the business assistant name/greeting/fallback and save. Inspect a
   location with inherited values: simply opening its form must not create an
   override. Save one explicit greeting override, change the default and verify
   the override remains; switch it to inherit and verify the default returns.
7. Inspect configured and effective location compliance. For cannabis locations,
   check supported/unsupported jurisdiction behavior in the customer preview.
   There must be no compliance-disable control.
8. Upload a PNG/JPG/WebP logo/avatar and set a brand color. Save/reload. Check the
   customer preview's images, name and greeting; reject SVG, oversized and invalid
   images. Remove a published image and confirm its previous URL is unavailable.
9. Open customer preview. Verify a separate customer session, normal location
   selection/age gates/chat, and no admin cookies on widget API/image fetches in
   browser developer tools. A private browser window can load the same preview.
10. Open two admin tabs and save from each. Neither tab should become stuck because
    of `/auth/me` token rotation. Do not weaken CSRF or disable cookies to test.
11. Sign out; protected settings must require login. Sign in again. Revoke/expire
    a test session and confirm the UI returns to an enabled sign-in form. Test a
    denied request: it should retain edits and show an actionable error.
12. Restart/reconnect using Control Center. Confirm its owner sign-in, branding
    load/save, Start/Stop/Restart and clean window shutdown remain functional.
13. With existing owner/admin/manager/viewer test memberships, confirm admins can
    save general settings, managers can save locations only, and viewers cannot
    save. Direct requests still require membership and valid CSRF regardless of
    the visible controls or `X-BudBot-Business-ID`.

## Pass 2: FAQs and audit history

The FAQs section lists all business-owned entries, including disabled and
non-public drafts. Owners/admins can create or edit question (1–500 characters),
answer (1–10,000), business-wide/location scope, enabled and public state.
Managers/viewers can read. Scope choices include only this business's locations.
There is no hard-delete action: disable an entry to retain its configuration and
history while removing it from customer lookup. A non-public entry is also hidden
from customers. Location matches override business-wide entries using the existing
case/whitespace normalization. Duplicate enabled/public questions in the same scope
are rejected, including when republishing a draft or changing scope. Duplicate
disabled/private drafts remain editable, so legacy ambiguity can be resolved.

Audit History is owner-only under the existing `audit.read` policy. It shows
business events in descending timestamp/ID order, 25 per page, with Newest/Older
controls. The API allows 1–100 rows and offsets 0–10,000; offset pagination is a
recent-history browser, not a consistent snapshot/export while new events arrive.
Actor and resource identifiers are displayed without exposing account profiles.
Account-wide login/logout events have no business attribution and are excluded.
Only recognized safe metadata is returned, never arbitrary stored details or FAQ
content. Opening a section does not record a mutation. Business changes, logout
and session expiry clear prior FAQ/audit state; neither panel is polled.

### Pass 2 manual acceptance

1. Sign in as owner, choose the intended business, open **FAQs**, and create a
   business-wide `Parking?` / `Use the main lot.` entry, enabled and public.
2. Open **Customer preview**, complete normal location/age checks as needed,
   and run `/faq parking?`. Confirm the configured answer.
3. Edit the answer, save, and repeat the customer search. Confirm the new answer.
4. Disable the entry or make it non-public. Confirm it disappears from `/faq`
   and `/faq parking?` returns no match. Re-enable/publish it for the next check.
5. Add a second FAQ with the same normalized question for one location and a
   different answer. Select that location in preview; confirm its answer wins.
   Disable the override and confirm the business-wide answer returns. A duplicate
   enabled/public question in the same scope must be rejected with a useful error.
6. Open **Audit History**. Confirm FAQ create/edit/state events, actor/resource
   IDs and safe state metadata appear, with no question/answer text. Check paging
   if more than 25 events exist; empty history should be clear.
7. Reload the page and sign out/in. Confirm saved FAQ and audit state persists.
8. If the account already has multiple memberships, switch businesses in both
   sections. Prior tenant content must disappear while loading and never appear
   in the other business's results. No database editing is needed.
9. With existing admin/manager/viewer accounts, confirm the permissions above.
   Denied operations must show useful errors; UI visibility does not grant access.

Provider settings/credentials/tests, administrative slash commands and
account/membership management remain reserved for later passes. Control Center
is unchanged: open the admin URL manually. No Pass 3 provider work is included.

## Pass 3: AI Provider

Owners can save per-business configuration, explicitly set/replace a write-only
key and remove it (disabling AI). Ordinary saves never send a credential. Key
inputs clear on submission, including failures. Configure the deployment root key
and exact compatible-endpoint allowlist as documented in docs/configuration.md.
The model/tool-calling declaration must match the chosen provider. No Test
Connection, diagnostics, discovery or credential rehydration is implemented.

## Pass 5: authenticated commands

Open **Commands** after selecting a business. `/help` and the command input's
suggestions use current server-filtered permissions. The optional **Command
location** dropdown (or `/location Main`) selects the local working
scope. `/location --business` restores business defaults. Commands do not use or
change customer sessions. The panel is ephemeral and clears on reload, business
switch or logout; no command history or credentials are stored in the browser.

The dashboard remains the primary editor. Commands reuse its services/validation,
audited mutations, authenticated cookie and fresh CSRF flow. Read commands also
use the CSRF-protected execution endpoint. Provider credentials cannot be supplied
through commands. `/provider` exposes safe metadata, `/test` reuses Pass 4 saved
provider diagnostics, and `/audit` renders the existing sanitized history only.
Use `/set-hours mon-fri 9am-9pm; sat 10am-8pm; sun closed` for a weekly schedule,
or `/set-hours monday 9am 10pm` for a quick edit, and
`/add-faq Do you have parking? | Street parking only.` Hours changes affect only
the named days. Groups such as weekdays, weekends, everyday/daily and day ranges
are supported. Overlapping days or invalid groups reject the whole command.
FAQs use the selected location, or become business-wide when
Business defaults is selected. No JSON or IDs are needed. Provider results and
audit entries use plain-English labels; the full output stays in the scrollable
console. See `docs/commands.md` for syntax, permissions and limits.

### Pass 5 manual acceptance

1. Sign in and open **Commands**. Run `/help`, `/status`, `/locations`, then
   `/location <an existing location name>` and `/hours`.
2. Run `/greeting <a temporary greeting>`, then `/greeting`. Reload settings and
   confirm the selected-location override in **Assistant**; restore its original
   value or clear the explicit override in that editor.
3. Run `/location --business`, then `/disable`. Confirm it refuses without
   confirmation and leaves state unchanged. Run `/disable --confirm`, followed
   immediately by `/enable` to restore the business default. Explicit location
   overrides keep their normal precedence.
4. Run `/provider`, `/test`, `/compliance`, `/audit 20` and `/preview`. Follow
   **Open customer preview** and complete normal location/age checks. Confirm
   normal customer chat remains functional and audit output contains safe event
   metadata without credentials or greeting/FAQ content.
5. If existing non-owner accounts/multiple memberships are available, confirm
   `/help` omits privileged commands, denied writes remain denied, and business
   switching clears command output and working location.

Prefer a disposable test location/FAQ for manual writes. Try changing Monday,
then marking Monday closed; other days must stay unchanged. Add a FAQ with
`question | answer` and confirm it appears under the selected location (or
Business defaults). Automated tests cover validation, scope and rollback without
touching the operator's data. Account and
membership management and onboarding cleanup remain a later slice.
