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

## Administrative authentication

M9A uses the existing account and membership tables for administrative identity.
Runtime settings include:

```text
BUDBOT_ADMIN_SESSION_TTL_SECONDS       default 28800; maximum 86400
BUDBOT_ADMIN_LOGIN_FAILURE_LIMIT       default 5 attempts
BUDBOT_ADMIN_LOGIN_WINDOW_SECONDS      default 900
BUDBOT_ADMIN_LOGIN_LOCKOUT_SECONDS     default 900
BUDBOT_ADMIN_LOGIN_RATE_LIMIT_KEY      required in production; at least 32 bytes
```

Login throttling uses separate HMAC digests for normalized email and direct peer
IP. The backend does not trust `X-Forwarded-For`; without a trusted-proxy
contract, throttling uses the direct connection address. Development and tests
may omit the key; the process generates a random development-only key in memory.
Restarting the process clears the effective identity of those rate-limit
buckets. Production must supply a unique random key, such as one generated with
`openssl rand -hex 32`; keep it in the deployment's secret store and do not
commit it. Changing the production key clears the effective identity of
existing rate-limit buckets.

Admin sessions use an opaque host-only cookie with server-side revocation.
Cookie-authenticated unsafe requests require `X-CSRF-Token`. The business-ID
header does not authorize admin requests.

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

M9B Pass 2 exposes authenticated FAQ management in `/admin/`. Questions are
trimmed and bounded to 1–500 characters; answers to 1–10,000. An enabled/public
question must be unique after case/whitespace normalization within its exact
business-wide or location scope. Disabled/non-public drafts may duplicate but
cannot be enabled/published into ambiguity. Disable instead of deleting entries.
Changing public/enabled/scope state uses the same CSRF and membership checks as
other admin writes. Customer sessions and compliance checks are unchanged.

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
storage. M9A provides authenticated identity and permission foundations but does
not yet expose provider configuration. M9B must validate endpoint destinations
against SSRF risks before exposing operator-configurable URLs; resolution currently
uses server-level defaults only.

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

## M9B Pass 3: business AI providers

Owners configure AI in `/admin/` → **AI Provider**. Existing owner-only provider
permissions apply. Save disabled configuration, explicitly set a new key, then
enable AI. Normal saves preserve credentials; removing a credential disables AI.
Remove credentials before changing provider identity or endpoint.

OpenRouter uses the existing compatible transport at `https://openrouter.ai/api/v1`
with generic_openai harness. OpenAI uses openai_chat; Anthropic uses
anthropic_native. Those providers require keys. LM Studio uses generic_openai,
requires a base URL and permits keyless operation. Tool calling is explicitly
operator-declared, not assumed or probed. Other unsupported capabilities remain off.

Compatible endpoints must match the trusted deployment's exact JSON allowlist,
`BUDBOT_AI_COMPATIBLE_ENDPOINTS`, e.g. `["http://host.docker.internal:1234/v1"]`.
It defaults to empty; tenants cannot authorize new network destinations themselves.
Restrict the list to services/DNS names controlled by the deployment operator and
use network egress rules against DNS rebinding/untrusted DNS. Never allow a
customer-controlled hostname. URLs reject userinfo, query, fragment and control
characters. This is configuration for normal runtime requests, not a probe API.
The URL must be reachable FROM the backend container: localhost points to BudBot,
not LM Studio. Docker Desktop commonly provides host.docker.internal; Linux may
need an explicit host-gateway mapping, server bind address and firewall rules.
No networking automation is supplied.

### Encryption deployment and recovery

Set `BUDBOT_PROVIDER_ROOT_KEY` to URL-safe base64 of 32 cryptographically random
bytes in trusted process/deployment configuration. It is never in the database.
For a fresh installation only, append directly to the existing private Compose
`.env` without printing the value:

```sh
umask 077
python3 - <<'PY'
import base64, os
with open('.env', 'a') as configuration:
    configuration.write('\nBUDBOT_PROVIDER_ROOT_KEY=' + base64.urlsafe_b64encode(os.urandom(32)).decode() + '\n')
PY
```

Protect existing `.env` permissions too; umask affects newly created files.
Restart/recreate the backend. Do not regenerate this key for an existing install.
Never commit/log the key; production may inject it via a deployment secret facility.
Back it up separately from database backups. Losing/replacing it requires
re-entering provider credentials. There is no plaintext or ephemeral-key fallback.

cryptography AES-256-GCM uses fresh random 96-bit nonces and tenant/provider/endpoint
associated data. Version plus ciphertext live in a separate credential table.
SecretStore allows a future versioned KMS adapter without requiring cloud services
now. Online rotation is deferred. Only runtime configuration resolution decrypts;
admin GET returns safe metadata and credential_configured only. Missing/malformed
root keys, wrong-key/corrupt ciphertext and unknown versions fail closed with safe
errors. Plaintext exists transiently in requests/runtime, not persistent ORM state;
Python cannot promise memory zeroization. SQL parameter logging is suppressed.

Persisted profiles are authoritative, including disabled profiles. Unconfigured
tenants never inherit global credentials. Explicit `BUDBOT_AI_LEGACY_BUSINESS_ID`
may bind process AI settings to exactly one trusted business. The test environment
retains synthetic process fixtures; never deploy with environment=test.
`BUDBOT_AI_ENABLED` now controls legacy process fallback only;
`BUDBOT_AI_TENANT_ENABLED=false` disables tenant AI globally. Timeouts/output limits
remain deployment controls. No Test Connection, diagnostics or model discovery.
