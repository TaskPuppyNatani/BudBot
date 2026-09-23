"""Add location-aware compliance domains and session bindings.

Revision ID: 0005_m55_jurisdictional_compliance
Revises: 0004_m5_customer_information
"""

from __future__ import annotations

from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "0005_m55_jurisdictional_compliance"
down_revision: str | None = "0004_m5_customer_information"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "businesses", sa.Column("compliance_domain", sa.String(length=32), nullable=True)
    )
    op.execute(
        "UPDATE businesses SET compliance_domain = CASE "
        "WHEN compliance_profile_id = 'oregon_cannabis' THEN 'cannabis' "
        "ELSE 'general_retail' END"
    )
    op.alter_column(
        "businesses",
        "compliance_domain",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default="general_retail",
    )
    op.create_check_constraint(
        "ck_businesses_compliance_domain",
        "businesses",
        "compliance_domain IN ('general_retail', 'cannabis')",
    )

    op.add_column("locations", sa.Column("region_code", sa.String(length=2), nullable=True))
    op.create_check_constraint(
        "ck_locations_region_code_canonical",
        "locations",
        "region_code IS NULL OR "
        "(length(region_code) = 2 AND region_code = upper(region_code))",
    )

    op.add_column(
        "customer_sessions",
        sa.Column("compliance_domain", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "customer_sessions",
        sa.Column("compliance_jurisdiction_code", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "customer_sessions",
        sa.Column(
            "compliance_resolution_status", sa.String(length=32), nullable=True
        ),
    )
    op.alter_column(
        "customer_sessions",
        "compliance_profile_id",
        existing_type=sa.String(length=100),
        nullable=True,
    )
    op.alter_column(
        "customer_sessions",
        "compliance_profile_version",
        existing_type=sa.String(length=50),
        nullable=True,
    )
    op.execute(
        "UPDATE customer_sessions AS sessions SET compliance_domain = businesses.compliance_domain "
        "FROM businesses WHERE sessions.business_id = businesses.id"
    )
    op.execute(
        "UPDATE customer_sessions SET compliance_resolution_status = 'resolved'"
    )
    # Old cannabis sessions have no canonical region code. Do not infer one from
    # the display region; remove their misleading Oregon snapshots and attestation.
    op.execute(
        "UPDATE customer_sessions SET "
        "compliance_profile_id = NULL, compliance_profile_version = NULL, "
        "compliance_resolution_status = CASE "
        "WHEN selected_location_id IS NULL THEN 'location_required' "
        "ELSE 'profile_unavailable' END, "
        "age_gate_status = CASE WHEN age_gate_status = 'EXPIRED' "
        "THEN 'EXPIRED' ELSE 'REQUIRED_UNVERIFIED' END, "
        "age_attested_at = NULL "
        "WHERE compliance_domain = 'cannabis'"
    )
    op.alter_column(
        "customer_sessions",
        "compliance_domain",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default="general_retail",
    )
    op.alter_column(
        "customer_sessions",
        "compliance_resolution_status",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default="resolved",
    )
    op.create_check_constraint(
        "ck_customer_sessions_compliance_resolution_status",
        "customer_sessions",
        "compliance_resolution_status IN "
        "('resolved', 'location_required', 'profile_unavailable', 'invalid_override')",
    )
    op.create_check_constraint(
        "ck_customer_sessions_compliance_domain",
        "customer_sessions",
        "compliance_domain IN ('general_retail', 'cannabis')",
    )
    op.create_check_constraint(
        "ck_customer_sessions_compliance_profile_pair",
        "customer_sessions",
        "(compliance_profile_id IS NULL AND compliance_profile_version IS NULL) OR "
        "(compliance_profile_id IS NOT NULL AND compliance_profile_version IS NOT NULL)",
    )


def downgrade() -> None:
    # M5 has no safe way to represent non-Oregon cannabis sessions. Refuse to
    # silently downgrade those tenants back onto one business-wide Oregon policy.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM businesses "
        "WHERE compliance_domain = 'cannabis') THEN "
        "RAISE EXCEPTION 'cannot downgrade M5.5 while cannabis tenants exist; "
        "resolve jurisdiction bindings before returning to M5'; END IF; END $$"
    )
    op.drop_constraint(
        "ck_customer_sessions_compliance_profile_pair",
        "customer_sessions",
        type_="check",
    )
    op.drop_constraint(
        "ck_customer_sessions_compliance_domain",
        "customer_sessions",
        type_="check",
    )
    op.drop_constraint(
        "ck_customer_sessions_compliance_resolution_status",
        "customer_sessions",
        type_="check",
    )
    op.alter_column(
        "customer_sessions",
        "compliance_profile_id",
        existing_type=sa.String(length=100),
        nullable=False,
    )
    op.alter_column(
        "customer_sessions",
        "compliance_profile_version",
        existing_type=sa.String(length=50),
        nullable=False,
    )
    op.drop_column("customer_sessions", "compliance_resolution_status")
    op.drop_column("customer_sessions", "compliance_jurisdiction_code")
    op.drop_column("customer_sessions", "compliance_domain")

    op.drop_constraint(
        "ck_locations_region_code_canonical", "locations", type_="check"
    )
    op.drop_column("locations", "region_code")

    op.drop_constraint("ck_businesses_compliance_domain", "businesses", type_="check")
    op.drop_column("businesses", "compliance_domain")
