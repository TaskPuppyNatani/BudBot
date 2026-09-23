# BudBot Provider Architecture

Status: V1 project contract  
Last updated: 2026-09-19

## Goal

BudBot must not be locked to one AI vendor, one hosting model, one POS system, or one maps implementation.

Providers are adapters behind stable internal interfaces.

## Provider categories

```text
providers/
├── ai/
├── inventory/
├── maps/
└── secrets/
```

Provider-specific SDK objects must not become core domain types.

## AI providers

### Required V1 provider types

- `mock`
- `openai_compatible`
- `openai`
- `anthropic`

The OpenAI-compatible provider is important for local/self-hosted inference such as:

- LM Studio;
- llama.cpp server;
- vLLM;
- other compatible endpoints.

### Conceptual protocol

```python
class ChatProvider(Protocol):
    async def generate(self, request: ChatRequest) -> ChatResponse:
        ...
```

Internal request/response objects should normalize:

- messages;
- tool definitions;
- tool calls/results;
- finish reason;
- usage where available;
- raw-provider metadata where safe/needed.

### Provider configuration

Provider choice should be configuration-driven.

Examples:

```yaml
ai:
  provider: openai_compatible
  base_url: http://127.0.0.1:1234/v1
  model: local-model
```

or:

```yaml
ai:
  provider: openai
  model: configured-model
  secret_reference: secret://...
```

Do not bake provider names into chat business logic.

## Inventory/catalog providers

V1 must define an inventory/catalog interface even though production cannabis POS adapters are deferred.

Initial implementations:

- `local` (the business-managed/internal database catalog).

The M6 `CatalogProvider` contract supports normalized product listing and search,
category listing, and active deal listing. `CatalogService` validates tenant and
selected-location scope, applies a bounded result count and deterministic ordering,
and owns server-side provider resolution. The `local` provider reads configured
BudBot records and carries source/update metadata in its internal results. Unknown
provider keys and provider failures become stable customer-safe errors. No external
provider credentials or arbitrary module imports are accepted as configuration.

The provider seam is intentionally independent of Dutchie, Treez, Flowhub, or other
POS schemas; later adapters must map their data to the same normalized catalog values.

Future adapters may include:

- Dutchie;
- Treez;
- Flowhub.

Conceptual capabilities:

```text
list_categories(location)
list_products(location, filters)
search_products(location, query, filters)
get_product(location, product_id)
```

A provider response should carry source/freshness metadata.

## Maps provider

V1 should support directions using stored location information.

A Google Maps adapter/link builder may provide:

- directions URLs;
- future place enrichment;
- future synchronized place details.

BudBot must degrade gracefully if an external maps API is unavailable.

Basic configured address/contact information remains available.

## Secret providers

Secrets must be separated from tenant configuration.

Define a secret-store abstraction.

Self-hosted V1 may use an encrypted local/database-backed implementation or environment-backed references, provided secrets are not exposed through normal APIs/logging.

A future managed deployment may use a cloud secret manager without changing core business logic.

Conceptual interface:

```text
get_secret(reference)
set_secret(...)
delete_secret(...)
```

Secret values must be redacted from:

- logs;
- audit output;
- `/provider`;
- API serialization;
- exception text.

## Provider registry

Provider resolution should use an explicit registry/factory.

Conceptual example:

```python
provider = ai_registry.create(config.provider_type, config)
```

Unknown provider types fail closed with a clear configuration error.

## Timeouts and failures

All external providers need bounded timeouts.

Provider failures should become normalized BudBot errors, such as:

```text
PROVIDER_UNAVAILABLE
PROVIDER_TIMEOUT
PROVIDER_AUTH_ERROR
PROVIDER_BAD_RESPONSE
CAPABILITY_UNAVAILABLE
```

Do not leak vendor secrets or raw credential-bearing error messages to customers.

## Source/freshness metadata

Operational facts should retain provenance where possible.

Example:

```text
value: "$24"
source: "internal_catalog"
source_updated_at: "..."
```

or:

```text
source: "dutchie"
fetched_at: "..."
```

This metadata is primarily internal but is important for debugging stale or incorrect answers.

## Tool-first assistant behavior

The model should call authoritative capabilities instead of guessing.

Examples:

```text
"Are you open?"       -> hours service
"Where are you?"      -> location service
"Do you have X?"      -> inventory/catalog provider
"How do I get there?" -> maps capability
```

If authoritative data is unavailable, the assistant should say it cannot verify the fact instead of fabricating an answer.

## Testing

Each provider interface must have contract tests.

The mock providers should allow deterministic testing of:

- success;
- empty results;
- timeouts;
- malformed responses;
- auth failures;
- stale data;
- provider unavailability.

Core tests should not require paid external API calls.

## V1 acceptance criteria

- changing AI provider requires configuration, not business-logic edits;
- an OpenAI-compatible local endpoint can be configured;
- at least one cloud AI adapter is operational;
- mock AI works deterministically in tests;
- product commands operate through the catalog/inventory abstraction;
- provider errors are normalized;
- secrets never appear in serialized configuration or logs;
- core chat behavior remains testable without network access.
