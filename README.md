# BudBot

BudBot is a white-label, multi-tenant local-business assistant platform. The
current V1 implementation includes tenant-scoped businesses and multiple
locations; business defaults and location overrides; authenticated Admin for
business settings, branding, assistant details, hours, FAQs, audit history,
Team access and invitations; and an embeddable customer widget with location
selection, customer sessions, age gating, compliance checks and customer
commands.

Owners can configure OpenAI-compatible providers (including LM Studio and
OpenRouter), OpenAI and Anthropic, with encrypted per-business credentials,
provider diagnostics, and a local catalog for products, location offerings,
prices, availability and supported deals. Customer product commands and
`/search` use that catalog and eligible public business knowledge.

The catalog is locally managed; it does not synchronize live POS inventory.
Payment details are displayed as business information; BudBot does not process
payments. POS integrations, live inventory sync, ordering, transaction
processing, browser geolocation, advanced analytics, billing, SSO, social login
and enterprise deployment automation are deferred. The Docker/Control Center
workflow supports local development. Production-shaped Compose and
HTTPS/reverse-proxy guidance, managed-container verification and a backup/
restore rehearsal remain unfinished; BudBot is not yet fully pilot-ready or
production-ready.

## Requirements

- Docker with Docker Compose (recommended), or Python 3.12 and
  [uv](https://docs.astral.sh/uv/)

## Docker development

### One-command local launch

With Python 3, Docker Engine/Compose V2, and your existing private `.env` configured:

```bash
./scripts/start_budbot.sh
```

The shared launcher checks Docker, builds/starts the existing `budbot` development
stack if needed, waits up to 15 minutes for database/backend readiness and the
Admin page, then opens <http://localhost:8000/admin/>. Compose retains its existing
Alembic-before-server startup path. A healthy running stack is reused without
rebuilding or creating demo data. First-owner setup remains the explicit local
workflow in [self-hosting](docs/self-hosting.md#first-owner-account).

Missing configuration produces setup instructions; this launch command never
creates or rewrites `.env`. Startup failures show recovery guidance without
printing Docker output or configuration values. Builds have a 30-minute bound.
Ctrl+C cancels the launcher; detached services may remain running. Reconnect by
launching again, or stop safely with `./scripts/stop_budbot.sh`. Data volumes stay
in place. The existing Control Center remains available for its Start/Stop/Restart
and branding workflows; its lifecycle and window handling are unchanged.

After startup, a read-only diagnostic inside the backend container checks TCP
reachability for enabled tenant OpenAI-compatible endpoints on the deployment
allowlist. Unavailable optional AI produces a warning while BudBot stays usable.
The probe sends no API credentials or inference requests, does not start LM Studio,
and does not validate the configured model or authentication. No provider keys
are read or decrypted. Diagnostic failures also remain warnings.

Optional Linux application-menu installation (no root):

```bash
./scripts/start_budbot.sh --install-desktop
```

Find **BudBot** in the application menu. The entry is generated for this checkout
under `${XDG_DATA_HOME:-~/.local/share}/applications/budbot.desktop`; reinstall it
after moving the checkout. It shows terminal progress and keeps warnings/errors
visible until Enter is pressed. A successful launch opens the Admin page and exits
the launcher without stopping services. Browser sessions still require owner sign-in.

### Local web shutdown (Linux development only)

Launching with `./scripts/start_budbot.sh` also detaches a small host controller.
The terminal launcher still exits normally. An authenticated **owner** can open
**System** in Admin and choose **Shut down BudBot**. Confirmation explicitly covers
all businesses in this local stack. The page reports shutdown, or an uncertain
connection result if the backend disappears before acknowledging; it does not
poll a backend that is shutting down. Rejected requests leave recovery controls.

The host runs exactly `docker compose --project-name budbot -f docker-compose.dev.yml down`
(using this checkout's absolute Compose path). No volume/image deletion flags are
used, so database data and uploaded assets survive. The controller ignores repeated
shutdown requests while stopping and exits after successful shutdown. Relaunch
with the same start command, then verify your saved data in Admin. A failed Docker
shutdown leaves the controller available for a retry after checking Docker.

IPC uses a private `backend/.budbot-runtime/control.sock`, visible through the
existing development source bind mount. The directory is mode 0700 and socket
0600; this relies on the launching OS user's existing Docker authority. Runtime
files are excluded from Git and Docker builds. No TCP management listener, Docker
socket mount, shared browser token, or arbitrary command API is added. Only fixed
status/shutdown messages are accepted. Backend requests require an active owner
membership, CSRF for mutation, and a loopback Host with same Origin when supplied.
The gateway routes are omitted in production. Without the local controller, the
System control is hidden. Other platforms retain the existing Stop command and
Control Center. Private `.env` and provider credentials are not changed.

For initial configuration and the original foreground development command:

```bash
cp .env.example .env
./scripts/dev.sh
```

The development stack exposes:

- API: <http://localhost:8000>
- liveness: <http://localhost:8000/health>
- readiness: <http://localhost:8000/ready>
- PostgreSQL: `localhost:5432`

The backend waits for PostgreSQL, applies Alembic migrations, and starts with
reload enabled. PostgreSQL data is stored in the named
`budbot_postgres_data` volume and survives ordinary container restarts.

Stop the stack without deleting data:

```bash
docker compose -f docker-compose.dev.yml down
```

## Local backend development

Start PostgreSQL (for example, only the Compose database), then install and
run the backend:

```bash
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d db
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn budbot.main:app --reload
```

Configuration uses `BUDBOT_`-prefixed environment variables. A validated
`BUDBOT_DATABASE_URL` using `postgresql+asyncpg://` is required. See
`.env.example` for runtime settings, including the bounded customer-session
TTL (`BUDBOT_CUSTOMER_SESSION_TTL_SECONDS`, 24 hours by default).

## Tests

The default suite is deterministic and does not call paid or external
services:

```bash
./scripts/test.sh
```

## Migrations

Apply migrations to the configured database with:

```bash
./scripts/migrate.sh
```

Alembic owns production schema changes. The M1 baseline revision intentionally
contains no domain tables; M2 adds the tenant and multi-location schema; M3
adds compliance-profile fields and customer sessions.

## M2/M3 development API

M2 provides development APIs under `/api/v1`. Business creation is an explicit
pre-authentication bootstrap route. All business reads/updates and tenant-owned
location or assistant routes require this temporary header:

```text
X-BudBot-Business-ID: <business UUID>
```

This header selects tenant context but does **not** authenticate the caller. Do
not expose these M2 routes as production-authorized administration endpoints.
Future authentication will replace the header dependency while retaining the
same tenant-scoped services.

Identifiers are application-generated UUIDs. Assistant display names are
ordinary mutable configuration and are never used as identifiers. Location
assistant overrides use nullable fields: an unset/null override inherits the
business assistant value; a non-null override wins.

M3 adds these bounded session routes:

- `POST /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}`
- `GET /api/v1/sessions/{session_id}/age-gate`
- `PATCH /api/v1/sessions/{session_id}/location`
- `POST /api/v1/sessions/{session_id}/age-attestation`
- `GET/PATCH /api/v1/businesses/{business_id}/compliance-profile`

For `oregon_cannabis`, the age-attestation route accepts only a boolean 21+
website/session attestation. It is not legal proof of age, retailer/POS ID
verification, or purchase authorization. OMMP verification and transaction
workflows are out of scope.
