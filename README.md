# BudBot

BudBot is a white-label, multi-tenant local-business assistant platform. The
current implementation is **M1: Project Foundation** only: a FastAPI service,
typed runtime configuration, asynchronous PostgreSQL connectivity, Alembic,
health/readiness endpoints, tests, and a Docker development stack.

No tenant, user, location, compliance, command, provider, admin, or widget
behavior is implemented in M1.

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
`.env.example` for all M1 settings.

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
contains no domain tables; those begin in later milestones.
