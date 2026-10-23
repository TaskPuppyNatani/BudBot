"""Tenant AI profiles and separately encrypted credentials.

Revision ID: 0008_m9b_tenant_ai
Revises: 0007_m9a_auth_admin
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_m9b_tenant_ai"
down_revision = "0007_m9a_auth_admin"
branch_labels = None
depends_on = None

def timestamps():
    return [sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()) for name in ("created_at", "updated_at")]

def upgrade():
    op.create_table("business_ai_profiles",
        sa.Column("business_id", sa.Uuid(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("base_url", sa.String(2048)),
        sa.Column("tool_calling", sa.Boolean(), nullable=False),
        sa.CheckConstraint("provider IN ('openrouter','openai_compatible','openai','anthropic')", name="ck_ai_profile_provider"),
        *timestamps())
    op.create_table("provider_credentials",
        sa.Column("business_id", sa.Uuid(), sa.ForeignKey("business_ai_profiles.business_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False), *timestamps())

def downgrade():
    op.drop_table("provider_credentials")
    op.drop_table("business_ai_profiles")
