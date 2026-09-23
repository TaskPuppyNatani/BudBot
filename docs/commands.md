# BudBot Slash Command Contract

Status: V1 project contract  
Last updated: 2026-09-19

## Rule

Every command listed as part of V1 is an implementation commitment.

A command is not complete until it is:

- registered;
- parsed correctly;
- documented;
- permission checked;
- compliance checked where applicable;
- implemented end-to-end;
- covered by tests;
- represented correctly in `/help` and autocomplete.

Do not ship permanent placeholder commands that return "coming soon."

If a promised command is intentionally removed from V1, update this document and the acceptance criteria explicitly before release.

## Command design

Commands are shortcuts, not the only interface. Customers should still be able to ask the same questions naturally.

Each registered command should define:

- canonical name;
- aliases;
- description;
- scope (`customer` or `admin`);
- argument schema;
- required permissions;
- required feature/capability;
- compliance requirements;
- handler;
- help/autocomplete metadata.

Aliases resolve to one canonical handler.

Slash commands must never bypass normal tenant, session, permission, location, or compliance checks.

## Customer commands

### `/help`

Show customer commands currently available for the tenant and selected location.

The list must be capability-aware. Disabled features must not be advertised.

### `/hours`

Show current configured hours for the selected location.

If no location is selected and the business has multiple active locations, prompt for location selection.

### `/locations`

List active business locations and allow the visitor to select/switch location.

### `/location`

Show the currently selected location.

Where supported, an argument may select a location:

```text
/location Hawthorne
```

### `/directions`

Show the selected location's address and a directions action/link.

Must not require browser geolocation in V1.

### `/contact`

Show public contact information for the selected location, with business-wide fallback where appropriate.

### `/faq`

Browse or search business/location FAQ content.

### `/products`

Browse products from the configured catalog/inventory capability.

For initial V1 this may use a business-managed catalog or mock/development provider. A production Dutchie/Treez/Flowhub integration is not required for V1.

Cannabis product access must pass the active compliance profile and age-gate requirements.

### `/search <query>`

Search configured product/catalog data and eligible business knowledge.

Example:

```text
/search Blue Dream
```

Results must identify their authoritative source internally.

### `/categories`

Show configured product categories when product/catalog capability is enabled.

### `/deals`

Show business-provided promotions/deals that are enabled and permitted by the active compliance profile.

BudBot must not invent a promotion.

M6 implements all four catalog commands through the provider-neutral catalog service.
They require an active selected location. `/products [category]` lists enabled products
explicitly offered there; `/search <query>` performs bounded, deterministic
case-insensitive matching across factual product, brand, category, and description
fields; `/categories` lists enabled categories represented by visible local offerings;
and `/deals` lists enabled business-wide or selected-location deals whose UTC start/end
window is active. Catalog outputs are capped at 25 entries and disclose when more
matches exist. Missing price is shown as not listed; availability `unknown` is shown
as not reported. These commands do not infer inventory, prices, discounts, or deal
terms. Cannabis catalog access, including categories, is protected by the resolved
location compliance profile and age gate.

### `/payments`

Show configured payment methods.

### `/policies`

Show customer-facing store policies.

### `/age`

Explain the active age requirement and age-gate status in clear language.

The command reports the effective selected-location profile. With no selected
cannabis location it asks the visitor to choose one; an unsupported jurisdiction
is reported as unavailable without borrowing another jurisdiction's rules.
Website/session attestation must never be described as purchase-ID verification.

### `/clear`

M5 stores no conversational history. The command reports that there is nothing to clear
and preserves the tenant, selected location, age-gate status, and compliance-profile
snapshot. It does not create or reset chat history.

### `/about`

Explain what the configured assistant can do, identify the business it serves, and state important limitations.

Use the business-configured assistant display name, not a hard-coded "BudBot" name.

## Customer aliases

Aliases may be provided where useful. Examples:

```text
/map        -> /directions
/address    -> /directions
/open       -> /hours
/closing    -> /hours
```

Aliases are not separate implementations.

## M5 customer-command behavior

M5 registers functional customer handlers for `/hours`, `/locations`, `/location`,
`/directions`, `/contact`, `/faq`, `/payments`, `/policies`, `/age`, `/clear`, and
`/about`. They execute only through the central command executor. `/open` and
`/closing` resolve to `/hours`; `/map` and `/address` resolve to `/directions`.

Location lists contain active same-tenant locations in deterministic name order and
mark the current selection. `/location <name>` matches an exact display name after
case-folding and collapsing whitespace; duplicate normalized names are rejected as
ambiguous. Location-sensitive commands require an active selected location and direct
the customer to `/locations` and `/location` when none is selected. `/hours` shows
ordinary weekly hours, including closed or unconfigured days; it does not claim
current open status or invent holiday hours. `/directions` builds an encoded maps URL
from the configured address and makes no external API request.

`/contact` uses the selected location's public phone when configured, otherwise the
business phone, plus the business website and location address when present. `/faq`
lists and searches enabled public business FAQs; a selected location's matching FAQ
overrides the business-wide entry. Search is deterministic and never generates
answers. `/payments` and `/policies` render only explicitly configured business data.

`/age` renders the active M3 compliance-profile notices and session status. For
Oregon cannabis, the 21+ website/session attestation is not ID or transaction
verification, does not replace retailer/POS checks, and does not claim to cover
qualifying OMMP pathways. `/about` uses the configured assistant name and current
available command metadata. Missing information does not disable a command; the
`directions_enabled`, `faq_enabled`, `payments_info_enabled`, and
`policies_info_enabled` business flags control only those respective capabilities.

## Admin commands

Admin commands require authenticated administrative context and appropriate permissions.

### `/help`

Show admin commands available to the authenticated user.

### `/status`

Show useful service/configuration status without exposing secrets.

Examples:

- assistant enabled/disabled;
- active location;
- configured AI-provider type;
- capability health;
- migration/application status where appropriate.

### `/locations`

List locations available to the current business/admin.

### `/location [name]`

Show or select the admin's current working location.

### `/hours`

Show configured effective hours for the selected location.

### `/set-hours`

Update location hours through a validated admin flow.

Avoid brittle free-form parsing when a structured editor is safer.

### `/bot-name [name]`

Show or update the customer-facing assistant display name.

Renaming must take effect without redeployment.

Changing the name must not change stable internal IDs.

### `/greeting [text]`

Show or update the configured greeting.

### `/faq`

List/manage FAQ entries within the user's permitted business/location scope.

### `/add-faq`

Create a new FAQ entry with explicit business-wide or location-specific scope.

### `/disable`

Disable the customer-facing assistant for the appropriate scope.

The command must require confirmation if disabling would affect an entire business.

### `/enable`

Enable the customer-facing assistant for the appropriate scope.

### `/provider`

Show configured AI-provider metadata without exposing credentials.

Provider changes should use a safe configuration flow.

### `/test`

Run a bounded assistant/provider health test.

Must not mutate business data.

### `/preview`

Open or provide a preview of the current customer experience using effective branding/configuration.

### `/compliance`

Future informational/update subcommands may include `/compliance status`,
`/compliance check`, `/compliance update`, and `/compliance sources`.

A submitted regulator URL is source metadata or a review request only. It must
never directly rewrite or activate live compliance rules; activation requires a
trusted, authenticated, schema-valid declarative profile package.

This command is informational. Mandatory compliance controls cannot be disabled through it.

### `/audit`

Show recent administrative configuration changes that the authenticated user is authorized to view.

Sensitive secrets must never be included in audit output.

## Safe custom commands

The architecture should allow safe business-defined commands such as:

```text
/parking
/events
/rewards
/delivery
```

Custom commands must map to approved declarative actions, for example:

- `knowledge_response`;
- `external_link`;
- `location_info`.

Custom commands must not execute arbitrary server-side code, shell commands, SQL, provider calls, or user-supplied scripts.

Custom commands may not override protected built-in commands or bypass compliance.

## Registry model

Conceptual example:

```python
Command(
    name="hours",
    aliases=["open", "closing"],
    scope="customer",
    capability="business_hours",
    handler=get_hours,
)
```

The concrete API may differ, but the registry must remain explicit and inspectable.

## Current M4 framework

M4 provides typed command definitions, explicit registry bootstrap, case-insensitive
command-name parsing, aliases, customer/admin scope separation, argument metadata,
permission and feature requirements, M3 compliance-capability hooks, deterministic
introspection, and dynamic `/help`.

M4 introduced customer and admin `/help`. M5 registers the real customer information
commands described above. Later-milestone names remain protected but are not
executable, visible in help, or autocomplete options. Unknown and unavailable
commands fail closed.

Customer command execution and autocomplete use the existing tenant and customer
session boundaries. The bounded M4 HTTP API does not expose admin execution because
production authentication does not exist yet. Admin command contexts and permission
evaluation are explicit framework inputs for later authenticated integration; the
development tenant header is not authentication.

Customer feature requirements resolve from persisted business flags after live
tenant/session validation; compliance requirements delegate to the M3
`ComplianceEngine`. Safe future custom commands have a declarative action shape
(`knowledge_response`, `external_link`, or `location_info`) and protected-name
validation, but are not persisted or executed.

## V1 command checklist

### Customer

- [x] `/help`
- [x] `/products`
- [x] `/search`
- [x] `/categories`
- [x] `/deals`
- [x] `/hours`
- [x] `/locations`
- [x] `/location`
- [x] `/directions`
- [x] `/contact`
- [x] `/faq`
- [x] `/payments`
- [x] `/policies`
- [x] `/age`
- [x] `/clear`
- [x] `/about`

### Admin

- [x] `/help`
- [ ] `/status`
- [ ] `/locations`
- [ ] `/location`
- [ ] `/hours`
- [ ] `/set-hours`
- [ ] `/bot-name`
- [ ] `/greeting`
- [ ] `/faq`
- [ ] `/add-faq`
- [ ] `/disable`
- [ ] `/enable`
- [ ] `/provider`
- [ ] `/test`
- [ ] `/preview`
- [ ] `/compliance`
- [ ] `/audit`

No V1 release while a promised command remains unchecked unless the V1 contract is deliberately amended.
