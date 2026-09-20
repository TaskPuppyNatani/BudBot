#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_root/backend"

if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv is required; install it from https://docs.astral.sh/uv/" >&2
    exit 1
fi

uv run --extra dev pytest "$@"
