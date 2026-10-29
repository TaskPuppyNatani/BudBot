"""M9B invitation migration reachability and legacy-data preservation."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


def _load_m9b_invitation_revision():
    revision_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0009_m9b_business_invitations.py"
    )
    spec = spec_from_file_location("m9b_business_invitations", revision_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_invitation_revision_is_reachable_from_the_single_head() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["0009_m9b_business_invitations"]
    revision = scripts.get_revision("0009_m9b_business_invitations")
    assert revision is not None
    assert revision.down_revision == "0008_m9b_tenant_ai"


def test_invitation_migration_preserves_existing_business_and_membership_rows() -> None:
    migration = _load_m9b_invitation_revision()
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE businesses (id CHAR(32) PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE user_accounts (id CHAR(32) PRIMARY KEY)"))
            connection.execute(text(
                "CREATE TABLE business_memberships ("
                "id CHAR(32) PRIMARY KEY, user_id CHAR(32) NOT NULL, "
                "business_id CHAR(32) NOT NULL, role VARCHAR(50) NOT NULL)"
            ))
            connection.execute(text("INSERT INTO businesses (id) VALUES ('11111111111111111111111111111111')"))
            connection.execute(text("INSERT INTO user_accounts (id) VALUES ('22222222222222222222222222222222')"))
            connection.execute(text(
                "INSERT INTO business_memberships (id, user_id, business_id, role) "
                "VALUES ('33333333333333333333333333333333', "
                "'22222222222222222222222222222222', "
                "'11111111111111111111111111111111', 'owner')"
            ))
            before = set(inspect(connection).get_table_names())
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()

            assert connection.scalar(text("SELECT count(*) FROM businesses")) == 1
            assert connection.scalar(text("SELECT count(*) FROM user_accounts")) == 1
            assert connection.scalar(text("SELECT role FROM business_memberships")) == "owner"
            assert set(inspect(connection).get_table_names()) == before | {"business_invitations"}

            table = inspect(connection)
            columns = {column["name"] for column in table.get_columns("business_invitations")}
            assert columns == {
                "id", "business_id", "recipient_email", "role", "created_by_user_id",
                "token_digest", "created_at", "expires_at", "accepted_at", "revoked_at",
            }
            unique = table.get_unique_constraints("business_invitations")
            assert any(constraint["column_names"] == ["token_digest"] for constraint in unique)
            foreign_keys = table.get_foreign_keys("business_invitations")
            assert any(
                item["constrained_columns"] == ["business_id"]
                and item["options"].get("ondelete") == "CASCADE"
                for item in foreign_keys
            )
            assert any(
                item["constrained_columns"] == ["created_by_user_id"]
                and item["options"].get("ondelete") == "SET NULL"
                for item in foreign_keys
            )
    finally:
        engine.dispose()
