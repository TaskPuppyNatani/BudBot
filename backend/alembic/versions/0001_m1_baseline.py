"""Establish the M1 migration baseline.

Revision ID: 0001_m1_baseline
Revises:
Create Date: 2026-09-19
"""

from collections.abc import Sequence

revision: str = "0001_m1_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """M1 intentionally defines no domain tables."""


def downgrade() -> None:
    """M1 intentionally defines no domain tables."""
