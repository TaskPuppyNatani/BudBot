# BudBot administration (M9B Pass 1)

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

Provider settings/credentials/tests, FAQ management, audit browsing, admin commands
and account/membership management are reserved for later passes. Control Center
can remain unchanged: open the admin URL manually.
