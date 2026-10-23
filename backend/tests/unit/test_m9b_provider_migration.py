"""Portable new migration structure and predecessor-chain checks."""
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_provider_upgrade_downgrade_and_existing_business_preservation():
    path=Path(__file__).resolve().parents[2]/'alembic/versions/0008_m9b_tenant_ai.py'
    spec=spec_from_file_location('provider_migration',path);module=module_from_spec(spec);spec.loader.exec_module(module)
    assert module.down_revision=='0007_m9a_auth_admin'
    engine=create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE businesses (id CHAR(32) PRIMARY KEY)'))
        connection.execute(text("INSERT INTO businesses VALUES ('existing-business')"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            schema=inspect(connection)
            assert schema.get_pk_constraint('business_ai_profiles')['constrained_columns']==['business_id']
            assert schema.get_pk_constraint('provider_credentials')['constrained_columns']==['business_id']
            assert schema.get_foreign_keys('provider_credentials')[0]['referred_table']=='business_ai_profiles'
            assert {c['name'] for c in schema.get_columns('provider_credentials')}=={'business_id','version','encrypted_value','created_at','updated_at'}
            module.downgrade()
        assert connection.scalar(text('SELECT id FROM businesses'))=='existing-business'
    engine.dispose()
