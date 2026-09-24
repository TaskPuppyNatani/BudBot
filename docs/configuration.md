# BudBot Configuration Model

Status: V1 project contract  
Last updated: 2026-09-23

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
region_code             optional canonical two-letter region identifier
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

M6 stores industry-neutral `catalog_categories`, `catalog_products`,
`product_offerings`, and `catalog_deals`. Category and product identity are
business-scoped; offerings bind a product to one same-business location and hold
that location's offered state, normalized availability (`available`, `unavailable`,
or `unknown`), optional integer `price_minor` with an ISO currency code, and optional
source freshness. Deals are factual configured descriptions scoped to the business
or one same-business location, with optional product/category links and timezone-aware
start/end timestamps. Database composite foreign keys reinforce tenant/location
integrity. M6 does not calculate discount eligibility, tax, stacking, or checkout
prices.

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
M6 adds `products_enabled` for `/products`, `/search`, and `/categories`, and
`promotions_enabled` for `/deals`; both default to enabled.

## AI configuration

M7 AI selection is server/runtime configuration only, loaded through the typed
`BUDBOT_AI_*` settings. AI is disabled by default. The main settings are:

```text
BUDBOT_AI_ENABLED
BUDBOT_AI_PROVIDER                 openai_compatible | openai | anthropic
BUDBOT_AI_BASE_URL                 required for openai_compatible; operator-trusted
BUDBOT_AI_MODEL                    required, trimmed, 1–200 characters
BUDBOT_AI_HARNESS                  explicit registered adapter key
BUDBOT_AI_API_KEY                  optional for compatible; required for hosted providers
BUDBOT_AI_TIMEOUT_SECONDS
BUDBOT_AI_CONNECT_TIMEOUT_SECONDS
BUDBOT_AI_MAX_OUTPUT_TOKENS
BUDBOT_AI_TEMPERATURE
BUDBOT_AI_CAPABILITY_*             explicit booleans for the configured tuple
```

See `.env.example` for safe placeholder values. The implemented provider/harness
pairs and defaults are documented in `docs/providers.md`. No model is hard-coded;
the model identifier must be selected by the operator. Provider capability flags
are assertions about the configured model/harness, not capabilities inferred from
provider names. A workflow that requires an unavailable capability fails honestly.
The deterministic `mock` provider is test-injected and is not a runtime setting.

Provider endpoints and credentials are trusted server settings. Customer chat
payloads cannot override provider, model, harness, base URL, or API key. Never put
credentials in ordinary business rows, prompts, logs, or committed example files.
M7 has no per-business or per-location AI overrides and adds no encrypted secret
storage. A future authenticated admin path must validate endpoint destinations
against SSRF risks before exposing operator-configurable URLs. M9 owns admin
configuration; resolution currently uses server-level defaults only.

## Compliance configuration

A business references a compliance profile:

```text
compliance_profile_id = "oregon_cannabis"
compliance_profile_version = "..."
```

M5.5 adds `Business.compliance_domain`, a validated `general_retail` or
`cannabis` value. `industry` is not interpreted as a compliance domain. A
location keeps its display `region`; its optional `region_code` is normalized
to uppercase and combines with its two-letter `country` (for example `US-OR`).
Existing locations are left unset by migration and must be explicitly
configured before a cannabis profile can resolve. Legacy business profile
fields remain readable/configurable for compatibility and domain selection,
but cannabis jurisdiction profiles are selected from location/catalog
applicability rather than that business-wide profile ID.

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
