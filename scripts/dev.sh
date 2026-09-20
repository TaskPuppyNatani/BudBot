#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_root"

if ! command -v docker >/dev/null 2>&1; then
    echo "error: Docker is required to run the development stack" >&2
    exit 1
fi

docker compose -f docker-compose.dev.yml up --build
