#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if ! command -v python3 >/dev/null 2>&1; then
    echo "BudBot requires Python 3 to run its shared service controller." >&2
    exit 1
fi
case "${1:-}" in
    '') exec python3 "$repository_root/launchers/service_controller.py" launch ;;
    --install-desktop) exec python3 "$repository_root/launchers/service_controller.py" install-desktop ;;
    *)
        # Preserve the existing optional preview-URL output-file interface.
        exec python3 "$repository_root/launchers/service_controller.py" start "$1"
        ;;
esac
