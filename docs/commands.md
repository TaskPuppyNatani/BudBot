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

### `/payments`

Show configured payment methods.

### `/policies`

Show customer-facing store policies.

### `/age`

Explain the active age requirement and age-gate status in clear language.

For Oregon cannabis, this command must not imply that website age attestation replaces legally required purchase/acquisition ID verification.

### `/clear`

Clear conversational context for the current chat while preserving security/compliance state that should survive a conversational reset, such as the current tenant and valid age-gate/session state.

The implementation must define exactly which state is cleared.

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

Show the active compliance profile, version, important enforced controls, and source/update metadata.

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

## V1 command checklist

### Customer

- [ ] `/help`
- [ ] `/hours`
- [ ] `/locations`
- [ ] `/location`
- [ ] `/directions`
- [ ] `/contact`
- [ ] `/faq`
- [ ] `/products`
- [ ] `/search`
- [ ] `/categories`
- [ ] `/deals`
- [ ] `/payments`
- [ ] `/policies`
- [ ] `/age`
- [ ] `/clear`
- [ ] `/about`

### Admin

- [ ] `/help`
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
