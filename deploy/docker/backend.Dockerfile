FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend

COPY README.md /app/README.md
COPY backend/pyproject.toml ./pyproject.toml
COPY backend/budbot ./budbot
COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic

RUN pip install --no-cache-dir .

FROM base AS development

RUN pip install --no-cache-dir ".[dev]"

EXPOSE 8000

CMD ["uvicorn", "budbot.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS runtime

RUN addgroup --system budbot && adduser --system --ingroup budbot budbot
USER budbot

EXPOSE 8000

CMD ["uvicorn", "budbot.main:app", "--host", "0.0.0.0", "--port", "8000"]
