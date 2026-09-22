"""M3 ORM metadata and privacy-boundary checks."""

from sqlalchemy import CheckConstraint

from budbot.database.base import Base
from budbot.models.business import Business
from budbot.models.session import CustomerSession


def test_customer_session_metadata_contains_required_columns_and_constraints() -> None:
    table = Base.metadata.tables["customer_sessions"]
    assert {
        "id",
        "business_id",
        "selected_location_id",
        "compliance_profile_id",
        "compliance_profile_version",
        "age_gate_status",
        "age_attested_at",
        "expires_at",
        "created_at",
        "updated_at",
    } <= set(table.c.keys())
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_customer_sessions_age_gate_status"
        for constraint in table.constraints
    )
    assert "date_of_birth" not in table.columns
    assert "government_id" not in table.columns


def test_business_compliance_defaults_are_explicit() -> None:
    business = Business(display_name="Retail", industry="general_retail")
    assert business.compliance_profile_id is None
    assert business.compliance_profile_version is None
    # SQLAlchemy applies the client defaults at INSERT/flush time; the schema
    # also carries server defaults for safe M2-row backfill and direct SQL.
    assert str(Business.__table__.c.compliance_profile_id.server_default.arg) == (
        "general_retail"
    )
    assert str(
        Business.__table__.c.compliance_profile_version.server_default.arg
    ) == "1.0"


def test_customer_session_uses_uuid_primary_key() -> None:
    assert CustomerSession.__table__.c.id.type.python_type is not int
