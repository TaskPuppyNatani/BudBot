# BudBot

BudBot is a white-label, multi-tenant local-business assistant platform. The
current implementation includes **M1: Project Foundation**, **M2: Tenant +
Multi-Location Domain**, and **M3: Customer Sessions + Compliance Foundation**:
a FastAPI service, asynchronous PostgreSQL access, Alembic migrations,
tenant-scoped businesses and locations, normalized weekly hours, configurable
assistant identity, persistent customer sessions, versioned compliance
profiles, and server-side Oregon website age gating.

Authentication, slash commands, AI providers, the admin frontend, product
catalog, and the widget are not implemented yet.

## Requirements

- Docker with Docker Compose (recommended), or Python 3.12 and
  [uv](https://docs.astral.sh/uv/)

## Docker development

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
