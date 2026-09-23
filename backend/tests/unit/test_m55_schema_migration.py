"""M5.5 ORM/schema metadata and Alembic graph checks."""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint

from budbot.database.base import Base
from budbot.models.business import Business
from budbot.models.location import Location
from budbot.models.session import CustomerSession


def test_m55_orm_columns_and_nullable_binding_match_unresolved_states() -> None:
    business = Base.metadata.tables["businesses"]
    location = Base.metadata.tables["locations"]
    session = Base.metadata.tables["customer_sessions"]

    assert not business.c.compliance_domain.nullable
    assert str(business.c.compliance_domain.server_default.arg) == "general_retail"
    assert location.c.region_code.nullable
    assert not session.c.compliance_domain.nullable
    assert session.c.compliance_jurisdiction_code.nullable
    assert session.c.compliance_profile_id.nullable
    assert session.c.compliance_profile_version.nullable
    assert not session.c.compliance_resolution_status.nullable
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_customer_sessions_compliance_resolution_status"
        for constraint in session.constraints
    )
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_customer_sessions_compliance_profile_pair"
        for constraint in session.constraints
    )
    assert "industry" in business.c
    assert Business.__table__.c.compliance_domain is business.c.compliance_domain
    assert Location.__table__.c.region_code is location.c.region_code
    assert CustomerSession.__table__.c.compliance_profile_id is session.c.compliance_profile_id


def test_region_codes_normalize_but_do_not_guess_from_display_region() -> None:
    location = Location(
        country="us",
        region_code=" nm ",
        display_name="Albuquerque",
        address_line_1="1 Main St",
        city="Albuquerque",
        region="New Mexico",
        postal_code="87101",
        timezone="America/Denver",
    )
    assert location.country == "US"
    assert location.region_code == "NM"
    assert location.region == "New Mexico"
    assert Location(
        country="US",
        display_name="Legacy",
        address_line_1="1 Main St",
        city="Somewhere",
        region="Oregon",
        postal_code="00000",
        timezone="America/Los_Angeles",
    ).region_code is None
    with pytest.raises(ValueError, match="two-letter"):
        Location(
            country="US",
            region_code="New Mexico",
            display_name="Bad",
            address_line_1="1 Main St",
            city="Somewhere",
            region="New Mexico",
            postal_code="00000",
            timezone="America/Denver",
        )


def test_alembic_has_exactly_one_m55_head() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == [
        "0005_m55_jurisdictional_compliance"
    ]
