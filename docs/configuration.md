# BudBot Configuration Model

Status: V1 project contract  
Last updated: 2026-09-19

## Goal

A business must be able to configure BudBot without editing application code or redeploying.

Configuration is divided into:

1. business-wide defaults;
2. location-specific configuration/overrides;
3. assistant branding;
4. capabilities/feature flags;
5. compliance selection;
6. provider configuration;
7. secrets.

Secrets are not ordinary configuration.

## Business configuration

V1 business fields should include at least:

```text
business_id
display_name
legal_name            optional
industry
website_url            optional
main_phone             optional
logo_reference         optional
primary_brand_color    optional
active
default_timezone       optional
```

M5 adds optional business-wide `payment_methods` (objects with `name` and optional
`details`) and `store_policies` (objects with `title` and `text`). These are explicit
customer-facing data, not payment processing or executable markup. A null value means
not configured; an empty list means none are listed.

## Assistant configuration

At minimum:

```text
assistant_id
business_id
display_name
greeting
fallback_message
avatar_reference       optional
primary_color_override optional
enabled
```

The assistant `display_name` is entirely customer configurable.

Examples:

```text
Bud
Leaf
GreenGuide
Poppy
Store Helper
```

"BudBot" must not be hard-coded into customer-facing messages.

Internal references use stable IDs.

## Location configuration

Each business may own multiple locations.

At minimum:

```text
location_id
business_id
display_name
address_line_1
address_line_2        optional
city
region/state
postal_code
country
phone                  optional
timezone
active
maps_place_id          optional
maps_destination       optional
```

Location hours should be normalized rather than stored only as display strings.

The model should support:

- ordinary weekly hours;
- closed days;
- temporary/special hours later without schema replacement.

## Inheritance

Effective settings are resolved as:

```text
business default
    ↓
location override, when explicitly configured
```

Do not copy every business setting into every location.

The code should expose one effective-configuration resolver so different API routes do not independently implement inheritance rules.

## Knowledge/FAQ

Knowledge entries should have explicit scope:

```text
knowledge_id
business_id
location_id     nullable
type
question/title
content
enabled
source
updated_at
```

`location_id = null` means business-wide.

Examples include:

- parking;
- payment methods;
- return policy;
- accessibility;
- loyalty program;
- store policies;
- frequently asked questions.

M5 persists public FAQs in `faq_entries`, with `business_id`, optional `location_id`,
`question`, `answer`, `enabled`, and `is_public`. Location-scoped rows must belong to
the same business. Only enabled/public rows are exposed; for the selected location, a
matching normalized question overrides the business-wide entry. Matching is exact-first
then case-insensitive substring search, not semantic retrieval.

## Product/catalog configuration

V1 must define the capability even though production POS integrations are deferred.

A product record/provider response should support enough structured information for slash commands such as `/products`, `/search`, and `/categories`.

Useful fields:

```text
external_id
business_id
location_id
name
brand
category
description
price
available
quantity            optional
thc                  optional/structured
cbd                  optional/structured
source
source_updated_at
```

Do not invent missing product facts.

## Feature flags

Capabilities should be explicit.

Example conceptual flags:

```text
chat_enabled
directions_enabled
faq_enabled
products_enabled
promotions_enabled
payments_info_enabled
policies_info_enabled
custom_commands_enabled
```

Compliance may disable a capability regardless of a business feature flag.

M5's four customer-information flags default to enabled; disabling a flag hides the
command from help/autocomplete and rejects execution without confusing it with missing data.

## AI configuration

AI/provider selection should be business scoped for V1.

Conceptually:

```text
provider_type
base_url             when applicable
model
timeout
max_output_tokens
provider_options
secret_reference
```

Do not store plaintext API secrets in ordinary configuration rows.

Location-specific AI providers are not required for V1.

## Compliance configuration

A business references a compliance profile:

```text
compliance_profile_id = "oregon_cannabis"
compliance_profile_version = "..."
```

Optional profile-approved settings may be configurable.

Mandatory safeguards are not business-disableable.

Customer sessions use `BUDBOT_CUSTOMER_SESSION_TTL_SECONDS` for their bounded
lifetime. The development default is 86,400 seconds (24 hours); expiration is
evaluated server-side and is not an immortal verification. Mandatory profile
rules and the active profile version are not business-disableable options.

## Maps configuration

A location may contain enough data to generate a Google Maps directions URL without making a live Places API request for every chat.

A future maps provider may enrich:

- place details;
- synchronized hours;
- location metadata.

Core business data should not become unavailable merely because a maps API is down.

## Custom command configuration

Safe custom commands are declarative.

Example:

```text
name = "parking"
action_type = "knowledge_response"
target = "knowledge:parking"
```

Allowed action types must be enumerated by BudBot.

Do not permit arbitrary code/script execution.

## Validation

Configuration writes must validate:

- tenant ownership;
- required fields;
- known enum/profile/provider values;
- URLs;
- timezones;
- hour ranges;
- command-name collisions;
- protected command names;
- secret/reference boundaries.

## Audit behavior

Important configuration changes should create audit records, including:

- assistant rename;
- greeting change;
- location creation/deactivation;
- hours changes;
- compliance-profile changes;
- AI-provider changes;
- assistant enable/disable;
- permission/role changes.

Audit logs must not record plaintext credentials.

## V1 acceptance criteria

- one business can create at least two locations;
- each location can have distinct address, contact data, timezone, and hours;
- business defaults resolve correctly;
- location overrides resolve correctly;
- assistant display name can be changed and appears in the widget without redeployment;
- general FAQs and location-specific FAQs resolve correctly;
- feature flags affect `/help` and command availability;
- secrets are not returned through ordinary configuration APIs.
