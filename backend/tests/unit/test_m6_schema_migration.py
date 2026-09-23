"""M6 catalog ORM constraints and Alembic revision metadata."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint

from budbot.database.base import Base
from budbot.models.catalog import CatalogCategory, CatalogDeal, CatalogProduct, ProductOffering


def test_m6_catalog_models_have_tenant_integrity_and_canonical_money_columns() -> None:
    categories = CatalogCategory.__table__
    products = CatalogProduct.__table__
    offerings = ProductOffering.__table__
    deals = CatalogDeal.__table__

    assert products.c.business_id is not None
    assert isinstance(offerings.c.price_minor.type, BigInteger)
    assert "currency" in offerings.c
    assert offerings.c.availability.server_default.arg == "unknown"
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_catalog_products_category_tenant"
        for constraint in products.constraints
    )
    assert {
        constraint.name
        for constraint in offerings.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    } >= {
        "fk_product_offerings_location_tenant",
        "fk_product_offerings_product_tenant",
    }
    assert {
        constraint.name
        for constraint in deals.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    } >= {
        "fk_catalog_deals_location_tenant",
        "fk_catalog_deals_product_tenant",
        "fk_catalog_deals_category_tenant",
    }
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_product_offerings_price_currency"
        for constraint in offerings.constraints
    )
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_catalog_deals_valid_window"
        for constraint in deals.constraints
    )
    assert {"catalog_categories", "catalog_products", "product_offerings", "catalog_deals"} <= set(
        Base.metadata.tables
    )
    assert not Base.metadata.tables["businesses"].c.products_enabled.nullable
    assert not Base.metadata.tables["businesses"].c.promotions_enabled.nullable


def test_m6_revision_follows_m55_with_one_alembic_head() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["0006_m6_provider_neutral_catalog"]
    revision = scripts.get_revision("0006_m6_provider_neutral_catalog")
    assert revision is not None
    assert revision.down_revision == "0005_m55_jurisdictional_compliance"
