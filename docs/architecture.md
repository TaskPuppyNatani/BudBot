# BudBot Architecture

Status: V1 project contract  
Last updated: 2026-09-23

## Purpose

BudBot is a white-label, multi-tenant local-business assistant platform. Dispensaries are the first supported vertical, but the core platform must remain industry-neutral.

A business may rename the customer-facing assistant to any display name without changing code or redeploying the application. "BudBot" is the product/platform name, not a required assistant name.

## V1 architectural goals

V1 must support:

- multiple businesses/tenants;
- multiple locations per business from day one;
- business-wide configuration with location-specific overrides;
- customer-configurable assistant name and branding;
- server-enforced age gating;
- a versioned compliance-profile system, including Oregon and New Mexico cannabis profiles;
- a provider-neutral AI layer;
- self-hosted deployment;
- cloud deployment;
- local/self-hosted or cloud AI providers;
- an embeddable customer chat widget;
- an authenticated business/admin interface;
- an extensible slash-command system;
- strict tenant isolation;
- audit logging for important administrative changes;
- PostgreSQL as the canonical production database.

## Non-goals for initial V1

V1 does not require production integrations for Dutchie, Treez, Flowhub, ordering, payments, or browser geolocation.

The architecture must leave clean extension points for those capabilities.

Product-related slash commands operate against the tenant-managed local catalog until production POS adapters are added.

## Repository layout

```text
BudBot/
├── backend/
│   ├── budbot/
│   │   ├── api/
│   │   ├── commands/
│   │   ├── compliance/
│   │   ├── core/
│   │   ├── database/
│   │   ├── models/
│   │   ├── providers/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── utils/
│   └── tests/
├── frontend/
│   ├── admin/
│   └── widget/
├── deploy/
├── docs/
├── examples/
└── scripts/
```

## Core domain model

### Account/User

An authenticated person who can administer one or more businesses, subject to permissions.

### Business/Tenant

The tenant security boundary.

A business owns:

- branding;
- assistant configuration;
- compliance profile;
- business-wide knowledge;
- locations;
- integrations;
- provider configuration;
- feature flags;
- users/roles;
- audit events.

Every tenant-owned record must be scoped by a stable tenant/business identifier. Tenant isolation must be enforced in backend data access and authorization, not by frontend convention.

### Location

A business has one or more locations.

A location may define:

- display name;
- address;
- phone;
- timezone;
- opening hours;
- active/inactive status;
- Google Maps destination data;
- location-specific knowledge;
- location-specific feature settings;
- selected business-setting overrides.

Do not model a business and location as the same entity.

### Assistant

The assistant has a stable internal ID and a configurable customer-facing identity.

Business-level assistant configuration includes:

- display name;
- greeting;
- avatar reference;
- primary branding color;
- enabled/disabled state;
- fallback message.

The display name must never be used as a primary key, routing key, or permanent identifier.

Location-specific assistant overrides are permitted, but inherit business defaults when absent.

### Chat Session

A visitor conversation belongs to:

- one tenant;
- zero or one selected location until selection is complete;
- one stable session identifier;
- an age-gate state;
- timestamps;
- conversation state.

Age verification/attestation belongs to the visitor session, not to the business.

For cannabis tenants, the session also binds the effective compliance domain,
canonical selected-location jurisdiction, profile ID, and profile version.
Location display text is never used to infer legal jurisdiction. See
`docs/compliance.md` for M5.5 resolution and fail-closed behavior.

## Configuration inheritance

Use explicit inheritance:

```text
Business default
    ↓
Location override, if present
    ↓
Effective configuration
```

An unset location field inherits the business default. An explicit override replaces the inherited value.

Avoid duplicating business configuration into every location row.

## Request pipeline

A customer request should conceptually pass through:

```text
Widget/API request
    ↓
Tenant resolution
    ↓
Session resolution
    ↓
Location resolution
    ↓
Authentication/permission checks when applicable
    ↓
Compliance checks
    ↓
Slash-command parsing OR natural-language routing
    ↓
Tool/provider execution
    ↓
Response composition
    ↓
Audit/usage logging as appropriate
```

No slash command, AI provider, or direct API route may bypass mandatory compliance controls.

## AI architecture

M7 keeps three concerns separate:

```text
AIService orchestration
    ↓
provider transport (HTTP protocol, endpoint, authentication)
    ↓
model/serving harness (message, tool, reasoning, and response behavior)
    ↓
configured model
```

Core values in `providers/ai/base.py` normalize messages, tool definitions/calls,
generation options, capabilities, finish reasons, usage, and response identity.
Transport and harness registries contain only explicit, trusted implementations;
configuration cannot name Python modules or classes. Local OpenAI-compatible
endpoints may select either the generic OpenAI-style harness or the Qwen harness.
Native OpenAI and Anthropic transports use their paired harnesses.

The configured provider/model/harness capability tuple is operator-declared. BudBot
does not assume that a model supports tools, usage, or generation controls just
because its provider or model name suggests it. Unsupported required capabilities
fail safely.

## Tool-first behavior

The single `AIService` may interpret a request and select tools backed by existing
deterministic commands and services. The bounded tool loop is capped at three
rounds and validates every call against a server-owned schema and static mapping.
Tool results remain tool-role data; neither user nor FAQ/catalog text is
concatenated into system instructions. Customer-visible tool-backed output is
composed from the deterministic command results. The provider's free-form final
prose is not returned, so an irrelevant or empty result cannot authorize a model
to invent a business fact. With no tool result, the service returns a fixed safe
response.

Examples:

- hours/contact/locations -> existing M5 customer-information commands;
- FAQs -> tenant-scoped public knowledge;
- products/categories/deals -> the M6 catalog service and compliance policy;
- compliance -> the authoritative `ComplianceEngine`.

AI is additive. Slash commands and readiness checks do not depend on an AI provider.
The M7 `POST /api/v1/chat` endpoint uses the existing temporary tenant/session
conventions; authentication and the customer widget remain later work.

## Provider boundaries

Keep providers separated by capability:

```text
providers/
├── ai/          # normalized AI transports and model/serving harnesses
├── inventory/   # normalized catalog providers
├── maps/
└── secrets/
```

M7 implements mock, generic OpenAI-compatible HTTP, hosted OpenAI, and native
Anthropic transports. Gemini, xAI/Grok, OpenRouter-specific, and other native
protocols are not registered as implemented; a compatible endpoint can use the
generic transport only when it honors the configured wire contract. No live
provider credentials are persisted in tenant rows.

Future POS integrations should be adapters behind the inventory/catalog interfaces
rather than special cases inside chat logic. M6's catalog path is command framework
→ `ComplianceEngine` → `CatalogService` → registered `CatalogProvider` → the
tenant-managed `local` catalog. AI tools reuse that path rather than accessing SQL.

## Frontend separation

### Admin frontend

Authenticated business-management UI.

Primary responsibilities:

- business settings;
- assistant branding/name;
- location management;
- hours/contact information;
- FAQs;
- compliance-profile visibility;
- AI/provider configuration;
- feature flags;
- preview;
- audit history.

### Widget frontend

Small public embeddable client.

Primary responsibilities:

- branding;
- age gate;
- location selection;
- chat;
- slash-command autocomplete;
- basic session handling.

Do not ship the admin application inside the public widget bundle.

## Deployment model

BudBot must support both:

1. self-hosted deployment; and
2. managed/cloud deployment.

These must remain independent from AI-provider choice.

Valid combinations include:

- self-hosted BudBot + local LLM;
- self-hosted BudBot + cloud LLM;
- hosted BudBot + cloud LLM;
- hosted BudBot + reachable customer-managed LLM endpoint.

Core functionality must not require a proprietary cloud runtime.

## Database

PostgreSQL is the canonical production database.

SQLite may be used only where tests or local tooling benefit from it, provided behavior important to production is verified against PostgreSQL.

Alembic owns schema migrations.

## Security requirements

V1 must include:

- strict tenant scoping;
- authenticated admin routes;
- role/permission checks;
- server-side age-gate enforcement;
- secret redaction from logs;
- secrets separated from normal tenant configuration;
- input validation;
- rate limiting for public chat endpoints;
- safe error handling;
- audit logging for sensitive configuration changes.

## Definition of done for V1 architecture

The architecture is considered V1-ready when:

- one business can own multiple independent locations;
- business defaults and location overrides work;
- the customer-facing assistant can be renamed without code changes;
- cannabis sessions cannot access gated capabilities before the server records the required age-gate state;
- general-retail tenants can operate without the cannabis gate;
- both self-hosted and cloud deployment paths are documented;
- at least one local/OpenAI-compatible AI path and one cloud AI path are supported;
- every V1 slash command in `docs/commands.md` is implemented, documented, permission/compliance checked, and tested;
- tests demonstrate tenant isolation.
