#!/usr/bin/env python3
"""Compatibility entry point for the shared demo-seed controller action."""

from pathlib import Path
import subprocess
import sys


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "launchers" / "service_controller.py"), "demo"],
        cwd=root,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
