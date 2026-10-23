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

### M7 implemented transports

| Registry key | Transport | Default endpoint | Harness |
| --- | --- | --- | --- |
| `openai_compatible` | Async OpenAI Chat Completions-compatible HTTP; local or operator-selected compatible endpoint | Required `BUDBOT_AI_BASE_URL` | `generic_openai` or `qwen_openai` |
| `openai` | Hosted OpenAI using the shared compatible transport | `https://api.openai.com/v1` | `openai_chat` |
| `anthropic` | Native Anthropic Messages HTTP protocol | `https://api.anthropic.com/v1` | `anthropic_native` |

The deterministic `mock` provider is injected into registries by tests and is not
registered in the default runtime registry. The generic transport supports
self-hosted services such as LM Studio, vLLM,
llama.cpp servers, and other endpoints that implement the expected compatible
request/response shape. Tool support is not assumed: the configured capability
flags represent the operator's verified behavior for that model and harness.

Gemini, xAI/Grok, and provider-specific OpenRouter transports are not implemented
or advertised. An endpoint from one of those services may be configured under
`openai_compatible` only if it actually implements this wire protocol. Adding a
native transport requires a functioning adapter, harness compatibility rules, and
contract tests.

### Normalized transport and harness contracts

`ProviderTransport.generate(request, config, harness)` owns endpoint delivery,
authentication, async HTTP, timeout, and provider error handling. `ModelHarness`
encodes normalized messages/tools and validates/decodes the provider response.
`AIService` sees only normalized BudBot values and does not contain vendor response
parsing or model-family branches.

The core values include system/user/assistant/tool messages, declarative JSON-schema
tool definitions, structured tool calls, finish reasons, generation controls,
explicit capabilities, and optional usage metadata. Vendor SDK objects and raw
response envelopes do not leave adapters.

The harness registry is explicit and maps `generic_openai`, `qwen_openai`,
`openai_chat`, and `anthropic_native`. Qwen adaptation strips `<think>` blocks and
discards hidden reasoning fields. Provider/harness pairs are checked in a static
compatibility map; arbitrary imports, class paths, or customer-supplied templates
are not supported.

### Trusted configuration and security boundary

Provider, endpoint, model, harness, credentials, timeout, output limit, and
capabilities come from server-side environment/configuration. AI is disabled by
default. Public chat requests cannot select any of those values. A configured base
URL is trusted operator input; BudBot does not fetch customer-supplied URLs. Protect
operator configuration and deployments against SSRF if endpoint configuration is
ever exposed through a future admin surface.

API keys use `SecretStr` while loading settings and are kept out of prompts,
responses, and normalized exceptions. M7 does not store tenant-specific credentials
in database columns. M9A provides authenticated admin sessions and business
permissions but stores no per-business provider configuration or credentials.
M9B will need a durable secret-reference/encryption boundary for tenant-specific
provider credentials, including businesses that use their own OpenRouter keys.
No provider setup GUI or credential storage is part of M9A.

### Tool and failure behavior

The provider transports tool declarations and normalized tool requests only.
Execution is owned by BudBot's static `AIToolRegistry`, which validates arguments
and calls existing customer commands so feature gates, tenant checks, selected
location, and `ComplianceEngine` checks run again. The public chat loop is limited
to three rounds and eight calls per round. Unknown/malformed/unadvertised calls fail
closed. Customer-visible tool-backed answers are composed from the deterministic
command outputs, and provider-generated final prose is discarded. Irrelevant tool
results therefore cannot establish additional facts, and empty catalog results
retain their honest command output. If no tool executes, the customer receives a
fixed safe response instead of guessed business facts.

HTTP response bodies are size bounded. Provider errors normalize to stable codes
such as `AI_PROVIDER_TIMEOUT`, `AI_PROVIDER_AUTH_FAILED`,
`AI_PROVIDER_BAD_RESPONSE`, `AI_MODEL_UNAVAILABLE`, and
`AI_CAPABILITY_UNSUPPORTED`; upstream bodies, secrets, and stack traces are not
returned to customers. Readiness and deterministic slash commands do not depend on
provider availability.

### Provider configuration

See `docs/configuration.md` and `.env.example` for the server environment names.
Local example:

```text
BUDBOT_AI_ENABLED=true
BUDBOT_AI_PROVIDER=openai_compatible
BUDBOT_AI_BASE_URL=http://127.0.0.1:1234/v1
BUDBOT_AI_MODEL=operator-selected-model
BUDBOT_AI_HARNESS=generic_openai
BUDBOT_AI_CAPABILITY_TOOL_CALLING=true
```

Only enable a capability after verifying it for the selected model and serving
stack. Do not bake provider names or model names into chat business logic.

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

### Saved tenant connection diagnostics (M9B Pass 4)

Owners can use **Admin → AI Provider → Test Connection** after saving settings
and credentials. `POST /api/v1/businesses/{business_id}/provider/test` requires
the existing owner-only `provider.write` permission and session CSRF token. Its
empty body cannot override the saved endpoint, provider, model or credential.
Compatible endpoints are checked against the exact deployment allowlist before
decryption or network access. Keyless compatible servers are supported. Hosted
providers require a stored credential; legacy/global credentials are never used
by this action.

The test reuses `ProviderService.runtime()` and the existing provider/harness
registries. For a saved OpenAI-compatible profile it first requests the saved
endpoint's standard `/models` resource, using the stored credential when present.
The bounded discovery request has a 2-second timeout; if a valid model list is
returned, the configured model ID must match exactly. A clear unsupported response
(HTTP 404, 405 or 501) falls through to the generation check so compatible servers
without model discovery still work. Malformed lists and other failures produce a
fixed diagnostic code without exposing response text. The test then sends one
fixed short user prompt with no tools, at most 16 output tokens, within a maximum
10-second overall operation timeout and a maximum 3-second connect timeout
(smaller configured limits still apply). It may incur a minimal provider charge
or load a local model. There are no provider retries, customer sessions, chat
history, or business configuration writes. A successful result means the
configuration accepted a small request in BudBot's response format; compatible
model identity is confirmed when model discovery is supported. It does not prove
tool calling or customer-answer quality. A cold local model may need to be loaded
before retrying a timeout.

The response contains only the saved provider/model identity and one stable code:
`AI_CONNECTION_OK`, `AI_DISABLED`, `AI_CONFIGURATION_INVALID`,
`AI_CREDENTIAL_MISSING`, `AI_ENDPOINT_DENIED`, `AI_PROVIDER_UNREACHABLE`,
`AI_PROVIDER_TIMEOUT`, `AI_PROVIDER_AUTH_FAILED`, `AI_MODEL_UNAVAILABLE`,
`AI_PROVIDER_BAD_RESPONSE`, `AI_PROVIDER_UNAVAILABLE`, or `AI_PROVIDER_ERROR`.
The shared transport treats HTTP 404 or a structured `model_not_found` error code
on HTTP 400/422 as model/endpoint unavailable. Other unrecognized request
rejections map to incompatible response, without parsing free-form upstream
error text. Rate limits and upstream server failures map to
temporarily unavailable. No raw provider content or exception text is returned.

Provider reads also include a metadata-based `runtime_status` (`ready`,
`disabled`, `incomplete`) and an optional fixed `runtime_code`. `ready` means
locally configured, not a live connectivity or credential-validity guarantee.
Last-test results are kept only in the current Admin view and clear on reload,
business switch or settings/credential changes; no migration is required.

`admin.provider.connection_tested` audit events contain only the fixed action,
allowlisted provider identity, success boolean and diagnostic code, with the
normal actor/business relation. Audit reads re-project these fields through
typed allowlists. Model names, endpoints, prompts, responses, keys and ciphertext
are excluded from diagnostic audit details.

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
