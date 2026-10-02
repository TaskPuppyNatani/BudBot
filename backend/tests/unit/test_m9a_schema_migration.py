"""M9A Alembic metadata and legacy-data preservation coverage."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


def _load_m9a_revision():
    revision_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0007_m9a_auth_admin.py"
    )
    spec = spec_from_file_location("m9a_auth_migration", revision_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_m9a_is_the_single_head_after_m6() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["0007_m9a_auth_admin"]
    revision = scripts.get_revision("0007_m9a_auth_admin")
    assert revision is not None
    assert revision.down_revision == "0006_m6_provider_neutral_catalog"


def test_m9a_upgrade_preserves_existing_accounts_businesses_and_memberships() -> None:
    migration = _load_m9a_revision()
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE businesses ("
                    "id CHAR(32) PRIMARY KEY, display_name VARCHAR(200) NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE user_accounts ("
                    "id CHAR(32) PRIMARY KEY, email VARCHAR(320) NOT NULL UNIQUE, "
                    "display_name VARCHAR(200), active BOOLEAN NOT NULL, "
                    "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE business_memberships ("
                    "id CHAR(32) PRIMARY KEY, user_id CHAR(32) NOT NULL, "
                    "business_id CHAR(32) NOT NULL, role VARCHAR(50) NOT NULL, "
                    "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO businesses (id, display_name) VALUES "
                    "('business-1', 'Existing Business')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO user_accounts "
                    "(id, email, display_name, active, created_at, updated_at) "
                    "VALUES ('user-1', 'legacy@example.test', 'Legacy User', 1, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO business_memberships "
                    "(id, user_id, business_id, role, created_at, updated_at) "
                    "VALUES ('membership-1', 'user-1', 'business-1', 'viewer', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()

            assert connection.scalar(
                text("SELECT email FROM user_accounts WHERE id='user-1'")
            ) == "legacy@example.test"
            assert connection.scalar(
                text("SELECT display_name FROM businesses WHERE id='business-1'")
            ) == "Existing Business"
            assert connection.scalar(
                text("SELECT role FROM business_memberships WHERE id='membership-1'")
            ) == "viewer"
            assert connection.scalar(
                text("SELECT password_hash FROM user_accounts WHERE id='user-1'")
            ) is None
            assert connection.scalar(
                text("SELECT initialized_at FROM auth_setup_state WHERE id=1")
            ) is None
            tables = set(inspect(connection).get_table_names())
            assert {
                "admin_sessions",
                "auth_setup_state",
                "admin_login_rate_limits",
                "audit_events",
            } <= tables
    finally:
        engine.dispose()
