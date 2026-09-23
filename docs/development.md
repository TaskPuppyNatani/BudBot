# BudBot Development Workflow

Status: V1 project contract  
Last updated: 2026-09-23

## Purpose

This document defines how BudBot should be developed so that implementation stays aligned with the V1 architecture and product contracts.

The goal is to keep changes reviewable, testable, provider-neutral, self-hostable, and safe for multi-tenant use.

## Source of truth

The following documents define V1 behavior:

- `architecture.md`
- `commands.md`
- `compliance.md`
- `configuration.md`
- `providers.md`
- `self-hosting.md`
- `development.md`

If implementation and documentation disagree, do not silently choose one.

Instead:

1. identify the conflict;
2. decide whether the code or contract should change;
3. update both in the same milestone when appropriate.

## Development principles

### 1. Multi-tenant safety first

Every feature that stores or retrieves tenant-owned data must prove that one business cannot access another business's records.

Tenant isolation is not optional test coverage.

### 2. Multi-location is a core assumption

Do not implement business logic that assumes one business equals one physical location.

Any location-sensitive feature should explicitly resolve the active location.

### 3. Customer-facing assistant identity is configurable

Never hard-code `BudBot` into customer-facing UI, prompts, responses, accessibility labels, or command help.

Use the effective assistant display name from configuration.

`BudBot` remains the platform/project name.

### 4. Compliance is backend-enforced

Do not rely on:

- frontend-only checks;
- prompt wording alone;
- LLM self-restraint;
- hidden UI elements.

Mandatory compliance must be enforced before protected actions execute.

### 5. Tool-first factual behavior

Store facts should come from structured data/services/providers.

Examples:

```text
hours       -> location service
address     -> location service
FAQ         -> knowledge service
products    -> inventory/catalog provider
directions  -> maps capability
compliance  -> compliance engine
```

The AI layer should not invent authoritative business facts.

### 6. Provider neutrality

Core logic must not depend directly on one AI, maps, inventory, or secrets provider.

Provider-specific code belongs behind provider interfaces.

### 7. Self-hosting must remain viable

Do not introduce a mandatory proprietary cloud dependency without explicitly changing the self-hosting contract.

## Recommended development flow

For each milestone:

1. define the bounded milestone scope;
2. identify the relevant project-contract docs;
3. implement only that scope;
4. add or update tests;
5. run focused tests;
6. run the broader relevant test suite;
7. review for confirmed defects and contract drift;
8. fix confirmed findings;
9. update documentation when behavior/contracts changed;
10. verify git status;
11. commit only when the milestone is coherent.

Do not automatically begin the next milestone after finishing one.

## Suggested V1 milestone sequence

### M1 - Project foundation

Scope:

- Python backend packaging;
- FastAPI application;
- configuration loading;
- PostgreSQL connection;
- Alembic setup;
- health endpoint;
- baseline test framework;
- Docker development baseline.

Acceptance:

- app starts locally;
- tests run;
- database migrations run;
- health endpoint responds;
- no business feature behavior yet.

### M2 - Tenant and multi-location domain

Scope:

- users/accounts;
- businesses/tenants;
- locations;
- tenant scoping;
- business defaults;
- location overrides;
- assistant identity/configuration.

Acceptance:

- one business can own multiple locations;
- another business cannot access them;
- effective configuration resolves correctly;
- assistant rename works through backend configuration.

### M3 - Sessions and compliance foundation

Scope:

- customer sessions;
- compliance registry;
- `general_retail`;
- `oregon_cannabis`;
- age-gate state;
- server-side protected capability enforcement.

Acceptance:

- cannabis product capability is blocked before required age attestation;
- general-retail flow is not incorrectly gated;
- direct API requests cannot bypass compliance;
- cross-tenant session reuse is rejected.

### M4 - Command framework

Scope:

- registry;
- parser;
- aliases;
- scopes;
- permissions;
- capability requirements;
- compliance hooks;
- dynamic `/help`.

Acceptance:

- commands are inspectable and testable;
- disabled capabilities do not appear in `/help`;
- admin commands require authentication/permission;
- command handlers cannot bypass compliance.

### M5 - Core customer information commands

M4 customer `/help` remains implemented and expands automatically as real
customer handlers are registered.

Implement fully:

- `/hours`
- `/locations`
- `/location`
- `/directions`
- `/contact`
- `/faq`
- `/payments`
- `/policies`
- `/age`
- `/clear`
- `/about`

Acceptance:

- every command is end-to-end functional;
- multi-location behavior works;
- assistant display name is honored;
- help/autocomplete metadata is correct.

Implementation notes: Alembic revision `0004_m5_customer_information` adds the FAQ
table, configured payment/policy data, and four business capability flags with enabled
defaults. FAQ access is tenant-scoped and location overrides are deterministic.
Location selection goes through the M3 locked session update; `/clear` is an honest
no-op until conversational history exists and preserves session/compliance state.
Focused M5 tests cover aliases, location behavior, FAQ visibility/overrides, and age state.

### M5.5 - Multi-jurisdiction compliance resolution

Alembic revision `0005_m55_jurisdictional_compliance` adds the explicit business
compliance domain, optional canonical location region code, and session binding
snapshot. It deliberately leaves legacy free-text regions unmapped. The immutable
profile catalog and one resolver support general retail, Oregon cannabis, and
New Mexico cannabis; unsupported or unconfigured cannabis jurisdictions remain
unresolved and fail closed for regulated capabilities. Location switching locks
and rebinds the session, preserving attestation only when the effective
domain/jurisdiction/profile/version fingerprint is unchanged. M5.5 adds no M6
product commands or remote profile updater.

### M6 - Product/catalog command capability

Scope:

- inventory/catalog interface;
- internal or mock catalog provider;
- structured product data;
- source/freshness metadata.

Implement fully:

- `/products`
- `/search`
- `/categories`
- `/deals`

Acceptance:

- all commands use provider abstractions;
- cannabis product access is compliance-gated;
- no product facts are fabricated;
- no production POS integration is required yet.

M6 implementation notes: Alembic revision `0006_m6_provider_neutral_catalog` adds
normalized categories, products, per-location offerings, and configured deals, with
composite tenant/location constraints. The explicit `local` provider reads these
records through `CatalogService`; the command executor performs feature and compliance
checks before handlers run. Generic catalog capabilities are public for general retail
and age-gated for Oregon/New Mexico cannabis. There is no catalog provider-selection
UI, POS synchronization, AI search, or checkout behavior in M6.

### M7 - AI provider layer

Scope:

- normalized chat request/response contracts;
- mock provider;
- OpenAI-compatible provider;
- at least one cloud provider adapter;
- provider registry;
- timeout/error normalization;
- secret references.

Acceptance:

- tests use deterministic mock provider;
- local OpenAI-compatible endpoint can be configured;
- cloud provider can be configured;
- changing provider does not require chat business-logic changes.

### M8 - Public widget

Scope:

- embeddable widget;
- assistant branding/name;
- age gate;
- location picker;
- chat UI;
- slash-command autocomplete;
- basic error states.

Acceptance:

- widget can be embedded independently;
- multi-location selection works;
- age gate is shown when required;
- frontend cannot bypass backend enforcement;
- no hard-coded assistant name.

### M9 - Admin UI and admin commands

Admin UI must support:

- business settings;
- assistant rename;
- greeting;
- locations;
- hours;
- FAQs;
- feature flags;
- provider metadata/configuration;
- compliance visibility;
- preview;
- audit history.

M4 admin `/help` remains implemented and expands automatically as authenticated
admin handlers are registered.

Implement fully:

- `/status`
- `/locations`
- `/location`
- `/hours`
- `/set-hours`
- `/bot-name`
- `/greeting`
- `/faq`
- `/add-faq`
- `/disable`
- `/enable`
- `/provider`
- `/test`
- `/preview`
- `/compliance`
- `/audit`

Acceptance:

- all commands are end-to-end functional;
- permissions are enforced;
- secrets are not exposed;
- destructive/broad actions use confirmation where appropriate.

### M10 - Self-hosting and hardening

Scope:

- production Dockerfiles;
- Compose stack;
- health/readiness;
- persistent PostgreSQL storage;
- rate limiting;
- security review;
- logs/redaction;
- backup/restore documentation;
- deployment verification.

Acceptance:

- fresh Docker-capable host can launch BudBot;
- data persists through restart;
- demo business can be created;
- multiple locations can be configured;
- widget/admin UI are usable;
- local or cloud AI provider can be configured.

## Testing strategy

Tests should be organized by behavior, not merely by file.

Required categories include:

```text
tests/
├── unit/
├── integration/
├── api/
├── commands/
├── compliance/
├── providers/
└── tenancy/
```

## Required test themes

### Tenant isolation

Test:

- read isolation;
- write isolation;
- session isolation;
- command isolation;
- provider/integration configuration isolation;
- audit visibility isolation.

### Multi-location behavior

Test:

- multiple locations under one business;
- selected-location resolution;
- business defaults;
- location overrides;
- inactive locations;
- no-location-selected behavior.

### Compliance

Test:

- age-gate state transitions;
- gated capability denial;
- permitted capability access;
- direct API bypass attempts;
- command bypass attempts;
- `/clear` behavior;
- general-retail behavior;
- Oregon cannabis restrictions.

### Commands

Each V1 command requires tests for:

- registration;
- parsing;
- arguments;
- aliases where applicable;
- permissions;
- capability gating;
- compliance gating;
- success behavior;
- relevant error behavior.

### Providers

Provider contract tests should cover:

- success;
- empty response;
- timeout;
- unavailable provider;
- auth/configuration failure;
- malformed upstream response;
- secret redaction.

## External-service testing

Core test suites must not require:

- paid AI API calls;
- live Google Maps calls;
- live POS calls.

Use deterministic mocks/fakes for CI.

Optional smoke tests may target configured real services and should be clearly separated from the default test suite.

## Database migrations

All production schema changes require Alembic migrations.

Do not silently depend on ORM auto-create behavior for production deployment.

Migration changes should include tests or verification for important upgrade paths.

## Logging

Logs should be useful but conservative.

Never log:

- plaintext API keys;
- database passwords;
- encryption keys;
- full secret-store values.

Customer chat content should not be logged by default unless a deliberate privacy-aware feature enables it.

## Code style

Prefer:

- typed Python;
- small service boundaries;
- explicit domain models;
- dependency injection where it improves testability;
- normalized provider interfaces;
- boring, readable code over clever abstractions.

Avoid:

- giant god-services;
- route handlers containing business logic;
- provider SDK objects escaping provider modules;
- tenant filters manually duplicated everywhere when a safer shared mechanism can be used;
- compliance rules embedded only in prompts;
- silent exception swallowing.

## Documentation updates

A milestone is not complete if it changes a contract but leaves the docs stale.

Examples requiring doc updates:

- adding/removing a V1 command;
- changing age-gate behavior;
- changing configuration inheritance;
- changing supported providers;
- adding a mandatory dependency;
- changing deployment expectations.

## Review checklist

Before sealing a milestone, review:

```text
[ ] Scope stayed bounded
[ ] Tenant isolation considered
[ ] Multi-location behavior considered
[ ] Compliance path considered
[ ] Provider boundaries preserved
[ ] Self-hosting compatibility preserved
[ ] Assistant name is not hard-coded
[ ] Tests added/updated
[ ] Focused tests pass
[ ] Relevant broader tests pass
[ ] Docs match behavior
[ ] Secrets absent from logs/output
[ ] Git status understood
```

## V1 release gate

BudBot V1 is not complete until:

- every V1 command in `commands.md` is complete;
- multi-location behavior is proven;
- assistant renaming works;
- Oregon cannabis age gating/compliance behavior is enforced server-side;
- self-hosting works from documented steps;
- local/OpenAI-compatible AI works;
- a cloud AI path works;
- tenant isolation tests pass;
- no known blocking security/compliance defects remain;
- documentation matches shipped behavior.

## Current M2 implementation notes

These details describe the concrete M2 implementation without changing the V1
contracts above:

- Domain identifiers are application-generated UUIDs stored through
  SQLAlchemy's UUID type, which maps to native PostgreSQL UUID columns.
- `user_accounts` and `business_memberships` form an explicit many-to-many
  account/business relationship. Membership carries a bounded role label, but
  M2 does not assign authorization semantics or implement login.
- Normal tenant-owned queries use `TenantScopedRepository`, initialized with an
  immutable request-level `TenantContext`. Primary-key reads add the business
  predicate automatically and return the same not-found result for missing and
  cross-tenant records.
- Until authentication is implemented, M2 API routes resolve tenant context
  from `X-BudBot-Business-ID`. This is a development/test selector, not proof of
  identity. Business creation is the only unscoped bootstrap route.
- Each business has one stable assistant configuration. A location may have one
  nullable override row for display name, greeting, fallback message, and
  enabled state. `AssistantService.resolve` is the single inheritance resolver:
  non-null location values win; null values inherit the business default.
- Weekly hours are normalized as one optional row per weekday and location.
  Weekdays use Monday `0` through Sunday `6`. Closed rows contain no times;
  open rows require `open_time < close_time`.
  Special/temporary hours remain a later extension.

## Current M3 implementation notes

These details describe the bounded M3 implementation without starting M4:

- `CustomerSession` uses an application-generated UUID as its opaque public
  reference and is accessed through `TenantScopedRepository`.
- Sessions snapshot `compliance_profile_id` and
  `compliance_profile_version`. The built-in profiles are
  `general_retail@1.0` and `oregon_cannabis@1.0`; the former is the safe
  backfill/default.
- `ComplianceEngine.authorize` is the single server-side capability guard.
  `requires_capability(...)` is a reusable FastAPI dependency for future
  routes/tools. Unknown profiles, capabilities, and invalid states fail
  closed.
- `BUDBOT_CUSTOMER_SESSION_TTL_SECONDS` defaults to 86,400 seconds. Expiry is
  checked during session access and capability authorization; no cleanup
  worker is introduced in M3.
- The temporary `X-BudBot-Business-ID` header remains a development/test
  tenant selector, not authentication. M3 adds only the minimum profile
  configuration path needed for development/testing; full authentication and
  admin UI remain later work.
- The PostgreSQL-only location-selection concurrency test is skipped unless
  `BUDBOT_TEST_POSTGRES_URL` points to an isolated database already migrated
  to Alembic head. SQLite tests do not prove PostgreSQL row-lock behavior.

## Current M4 implementation notes

- M4 uses an explicit in-memory command registry and bootstrap. It adds no database
  model or Alembic migration.
- Command names are case-insensitive; argument text retains its original case.
  Natural-language input remains distinguishable from slash commands and is not
  routed through the command executor.
- One executor owns scope, permission, feature, compliance, argument, and handler
  ordering. Protected capability checks reuse the M3 `ComplianceEngine`.
- Customer and admin `/help` are the only executable M4 built-ins. Future V1 command
  names are protected from custom-command collisions but are not registered or
  advertised before their handlers exist.
- `POST /api/v1/commands/execute` and `GET /api/v1/commands` are customer-only M4
  surfaces. Both require the temporary tenant header and a live same-tenant customer
  session. They do not create an admin-authentication mechanism.
- Admin permission state and feature availability are request-scoped inputs designed
  for future authenticated and persisted providers. Missing admin identity,
  permissions, features, or compliance approval fails closed.
- Future custom commands are represented only by a safe declarative definition and
  protected-name validation. M4 does not execute arbitrary custom actions, Python,
  shell commands, SQL, providers, or client-selected handlers.
