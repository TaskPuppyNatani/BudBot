# BudBot Self-Hosting and Deployment Contract

Status: V1 deployment contract; production guide incomplete
Last updated: 2026-11-01

## Current deployment status

The available and manually exercised deployment workflow is local development
through the Docker Compose/Control Center tooling described in README.md. The
Compose configuration targets development and binds its published ports to
loopback. It is not a production deployment template. A production Compose and
HTTPS/reverse-proxy recipe, managed-container verification, and backup/restore
rehearsal are not complete; BudBot is not yet fully pilot-ready or
production-ready.

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

The local development workflow is Docker-first. Configure a private `.env`, then
use the supported foreground or desktop launcher documented in README.md:

```bash
./scripts/dev.sh
# or
./scripts/start_budbot.sh
```

These commands start the development stack; they are not production deployment
instructions.

### First owner account

Apply Alembic migrations before initializing an owner. The development Compose
backend runs `alembic upgrade head` before serving; in another deployment, run
that migration before owner setup. There is no default password and no public
owner-registration endpoint.

For the local Control Center workflow, start BudBot once so its local demo business
is created, then initialize the first owner and select that business:

```bash
docker compose -f docker-compose.dev.yml --project-name budbot exec backend python -m budbot.admin setup-owner
```

The command lists active businesses and prompts for exactly one tenant, owner
email/display name, and a new password twice using hidden terminal input. It
persists only the Argon2id password hash and grants membership only in the
selected business. On a genuinely empty installation, it prompts for a first
business name and creates that business. A database singleton guard makes a
second or concurrent setup attempt fail without replacing the first owner.

Production deployments must set `BUDBOT_ADMIN_LOGIN_RATE_LIMIT_KEY` to a unique
secret of at least 32 bytes. Generate one with `openssl rand -hex 32`, keep it
outside Git, and use the same value across backend instances. Production startup
rejects a missing or too-short key. Do not pass owner passwords as command-line
arguments or store them in Compose environment variables.

A future production deployment needs health checks and persistent database
storage. This repository does not yet include a production Compose stack.

### Team invitations

Owners can add people from Admin → Team. BudBot creates a one-time link that the
owner copies and shares privately; BudBot does not send email. The link expires
after seven days by default. A recipient with an existing BudBot account signs
in as that account to accept. A new recipient chooses their own name and
password. Do not share invitation links over an untrusted connection. A link
using `localhost` works only on the BudBot computer; use an address the
recipient can reach (HTTPS when sharing between devices).

The project's Compose workflow includes development conveniences and must not be
exposed directly as a production service.

## Web administration

The Admin dashboard is served at `/admin/` on the backend origin.
After owner setup, open `http://127.0.0.1:8000/admin/` for the local development
stack. Production requires HTTPS for the Secure session cookie, but a production
HTTPS/reverse-proxy recipe has not been verified or documented. Sign in in the
browser; Control Center does not transfer its credentials. No frontend build or
package installation is required.

The Docker image includes `frontend/admin/public`; development Compose mounts
that directory read-only. Persist `BUDBOT_LOCAL_ASSETS_DIR` in the deployment
(the development stack already uses its existing named volume). Ensure the
runtime service user can write this application-owned image directory. The
normal branding endpoint is authenticated; public image delivery is restricted
to currently published logo/avatar references, not the directory contents.

See `frontend/admin/README.md` for current Admin behavior and historical
acceptance scenarios.

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

PostgreSQL is the canonical datastore for production deployments.

Persistent storage is used by the development stack. Production backup/restore
instructions remain a readiness requirement, not a completed recovery procedure.

Schema migrations are applied with Alembic.

## Networking

Before production readiness, document and verify:

- required exposed ports;
- reverse-proxy expectations;
- TLS expectations;
- trusted proxy settings;
- CORS configuration;
- public widget/API endpoints;
- private/admin endpoints where applicable.

HTTPS is required for production Admin sessions. A reverse-proxy/TLS recipe is
still required and has not been verified.

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

Tenant AI provider credentials are encrypted by the application with
`BUDBOT_PROVIDER_ROOT_KEY`, which remains private deployment configuration and
outside the database. Keep a durable backup of that key; do not regenerate it for
an installation with encrypted credentials. See docs/configuration.md.

## Local AI example

For normal tenant setup, configure a local OpenAI-compatible provider in Admin.
The environment example below is the legacy process-level fallback, which must
be explicitly bound to one trusted business. A local compatible inference server
does not require a cloud AI account. Start it separately and configure its
reachable base URL, model identifier and verified harness/capabilities in the
operator's private `.env` only when using that legacy fallback:

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
URLs, provider classes, harnesses, models or credentials. Tenant Admin settings
accept only compatible endpoints on the deployment's exact allowlist; tenants
cannot add network destinations. Restrict the allowlist to operator-controlled
services and apply network egress rules against untrusted DNS or rebinding.

The deterministic suite mocks provider HTTP calls. Live LM Studio/local-model smoke
tests are optional and were not a normal-suite dependency; live cloud calls also
require operator credentials and may incur cost.

## Cloud deployment

Deployment to ordinary managed containers has not been verified. Future hosted
deployment work should preserve the self-hosted architecture and use:

The cloud deployment contract should assume:

- containerized backend;
- PostgreSQL;
- built frontend assets;
- external secret injection;
- HTTPS;
- persistent database.

Vendor-specific deployment guides may be added later without changing application
architecture.

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

These are target criteria, not evidence that production deployment or recovery is
complete. The local development workflow is available; the production and managed
hosting portions remain release work.

A fresh machine with Docker support should be able to:

1. clone/copy BudBot;
2. configure `.env`;
3. start PostgreSQL and BudBot via Compose;
4. apply migrations and initialize the first owner with the local CLI;
5. create or select one business for that owner;
6. create multiple locations;
7. open the admin UI;
8. open/embed the widget;
9. use a mock or configured AI provider;
10. restart containers without losing persistent business data.

The same application images should remain suitable for ordinary managed container hosting.
