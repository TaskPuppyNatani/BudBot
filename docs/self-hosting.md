# BudBot Self-Hosting and Deployment Contract

Status: V1 project contract  
Last updated: 2026-09-19

## Goal

BudBot V1 must support both:

- self-hosted deployment; and
- managed/cloud deployment.

Self-hosting must be a real supported path, not a theoretical possibility.

AI-provider choice is independent of application deployment.

## Supported combinations

BudBot architecture must permit:

```text
Self-hosted BudBot + local/self-hosted AI
Self-hosted BudBot + cloud AI
Hosted BudBot      + cloud AI
Hosted BudBot      + reachable customer-managed AI
```

## Baseline stack

The self-hosted baseline should favor portable, boring infrastructure:

- BudBot backend/API;
- PostgreSQL;
- admin frontend;
- customer widget assets;
- optional reverse proxy;
- optional Redis only if a real V1 requirement justifies it.

Do not make Redis mandatory merely because it is common in SaaS stacks.

## Docker

The expected V1 self-hosting experience is Docker-first.

Target operator workflow:

```bash
cp .env.example .env
docker compose up -d
```

followed by documented initialization/migrations.

The production compose stack should include health checks and persistent database storage.

A separate development compose file may expose development conveniences.

## No mandatory proprietary cloud dependencies

Core BudBot must not require:

- AWS Lambda;
- Firebase;
- Supabase-specific APIs;
- Cloudflare Workers;
- proprietary hosted queues;
- proprietary hosted authentication;
- proprietary vector databases.

Such services may be supported later as optional adapters.

## Database

PostgreSQL is the canonical production datastore.

Persistent storage and backup/restore instructions must be documented.

Schema migrations are applied with Alembic.

## Networking

Document:

- required exposed ports;
- reverse-proxy expectations;
- TLS expectations;
- trusted proxy settings;
- CORS configuration;
- public widget/API endpoints;
- private/admin endpoints where applicable.

Production documentation should recommend HTTPS.

## Configuration

Runtime configuration should use environment variables and database-backed business configuration with clear precedence.

`.env.example` must contain names/placeholders only and no real secrets.

## Secrets

Self-hosted operators must have a supported method to provide:

- AI API credentials;
- maps credentials;
- future POS credentials;
- encryption keys.

Credentials must not be committed to Git.

## Local AI example

The backend can use a local OpenAI-compatible inference server without a cloud AI
account. Start the inference server separately and configure its reachable base URL,
model identifier, and verified harness/capabilities in the operator's private `.env`:

```text
BUDBOT_AI_ENABLED=true
BUDBOT_AI_PROVIDER=openai_compatible
BUDBOT_AI_BASE_URL=http://127.0.0.1:1234/v1
BUDBOT_AI_MODEL=operator-selected-model
BUDBOT_AI_HARNESS=generic_openai
BUDBOT_AI_CAPABILITY_TOOL_CALLING=true
```

Use `qwen_openai` only for a compatible endpoint serving the Qwen-style behavior.
Only set tool calling or other capability flags after validating the chosen model
and serving stack. AI remains disabled unless explicitly enabled. Example model names
are placeholders; BudBot does not download or manage models or start LM Studio.

For a backend running in a container, `127.0.0.1` points inside that container.
Use the host gateway/address reachable from that container (for example
`host.docker.internal` where supported), or place the model server and backend on a
trusted private network. Do not expose unauthenticated inference endpoints to the
public internet. Local inference can run without internet access once the model and
runtime are installed; cloud adapters require their configured network service.

The base URL is operator-trusted configuration. Public chat clients cannot choose
URLs, provider classes, harnesses, models, or credentials. No generic URL-fetching
feature exists. If future admin UI allows endpoint changes, add SSRF protections
before exposing that control.

The deterministic suite mocks provider HTTP calls. Live LM Studio/local-model smoke
tests are optional and were not a normal-suite dependency; live cloud calls also
require operator credentials and may incur cost.

## Cloud deployment

BudBot should remain deployable to ordinary container hosting.

The cloud deployment contract should assume:

- containerized backend;
- PostgreSQL;
- built frontend assets;
- external secret injection;
- HTTPS;
- persistent database.

Vendor-specific deployment guides may be added later without changing application architecture.

## Backups

Before calling self-hosting production-ready, document:

- PostgreSQL backup procedure;
- restore procedure;
- what filesystem/object data must also be preserved;
- secret/encryption-key backup implications.

A backup that cannot be restored is not considered a completed backup design.

## Upgrades

Production upgrades should follow:

```text
backup
  ↓
pull/build new version
  ↓
run migrations
  ↓
restart
  ↓
health check
```

Document rollback limitations for migrations.

## Health endpoints

V1 should expose bounded health/readiness information suitable for containers.

Health output must not disclose:

- API keys;
- database passwords;
- tenant secrets;
- sensitive customer data.

## Observability

Self-hosted operators should have usable logs.

Requirements:

- structured or consistently formatted logs;
- request/error correlation where practical;
- provider-secret redaction;
- no chat-content logging by default unless intentionally configured and documented;
- useful startup/configuration errors.

## V1 acceptance criteria

A fresh machine with Docker support should be able to:

1. clone/copy BudBot;
2. configure `.env`;
3. start PostgreSQL and BudBot via Compose;
4. apply/init migrations;
5. create a demo business;
6. create multiple locations;
7. open the admin UI;
8. open/embed the widget;
9. use a mock or configured AI provider;
10. restart containers without losing persistent business data.

The same application images should remain suitable for ordinary managed container hosting.
