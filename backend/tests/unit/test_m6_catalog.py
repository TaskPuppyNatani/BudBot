"""M6 catalog persistence, provider, service, command, and compliance behavior."""

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from budbot.catalog.types import (
    AvailabilityState,
    CatalogError,
    CatalogPage,
    ProductResult,
)
from budbot.providers.inventory.base import CatalogProviderContext
from budbot.commands.bootstrap import build_command_executor
from budbot.commands.types import CommandExecutionContext, CommandScope
from budbot.compliance.age_gate import AgeGateStatus
from budbot.core.exceptions import CommandError, ComplianceError, ResourceNotFound
from budbot.core.tenancy import TenantContext
from budbot.models.business import Business
from budbot.models.catalog import CatalogCategory, CatalogDeal, CatalogProduct, ProductOffering
from budbot.models.location import Location
from budbot.schemas.session import (
    AgeAttestationRequest,
    CustomerSessionCreate,
    SessionLocationUpdate,
)
from budbot.services.catalog_repository import CatalogRepository
from budbot.services.catalog_service import CatalogService
from budbot.services.session_service import SessionService
from budbot.providers.inventory.base import CatalogProviderRegistry


async def _context(
    db_session,
    *,
    business_name: str = "Cedar Shop",
    domain: str = "general_retail",
    region_code: str | None = "OR",
    selected: bool = True,
):
    business = Business(
        display_name=business_name,
        industry="retail",
        compliance_domain=domain,
    )
    db_session.add(business)
    await db_session.flush()
    location = Location(
        business_id=business.id,
        display_name=f"{business_name} Main",
        address_line_1="10 Main St",
        city="Portland",
        region="Oregon",
        region_code=region_code,
        postal_code="97201",
        country="US",
        timezone="America/Los_Angeles",
        active=True,
    )
    db_session.add(location)
    await db_session.flush()
    tenant = TenantContext(business.id)
    customer_session = await SessionService(db_session, tenant).create(
        CustomerSessionCreate(
            selected_location_id=location.id if selected else None
        )
    )
    context = CommandExecutionContext(
        session=db_session,
        tenant=tenant,
        scope=CommandScope.CUSTOMER,
        customer_session_id=customer_session.id,
    )
    return context, business, location


async def _add_product(
    db_session,
    context: CommandExecutionContext,
    location: Location,
    *,
    name: str,
    category_name: str = "Flower",
    brand: str | None = None,
    description: str | None = None,
    enabled: bool = True,
    offered: bool = True,
    availability: AvailabilityState | str = AvailabilityState.UNKNOWN,
    price_minor: int | None = None,
    currency: str | None = None,
    source_updated_at: datetime | None = None,
):
    repo = CatalogRepository(db_session, context.tenant)
    category = await repo.get_or_create_category(category_name)
    product = await repo.create_product(
        category_id=category.id,
        name=name,
        brand=brand,
        description=description,
        enabled=enabled,
        source_updated_at=source_updated_at,
    )
    await repo.set_offering(
        location_id=location.id,
        product_id=product.id,
        offered=offered,
        availability=availability,
        price_minor=price_minor,
        currency=currency,
        source_updated_at=source_updated_at,
    )
    return category, product


async def test_local_provider_commands_are_location_scoped_factual_and_searchable(
    db_session,
) -> None:
    context, business, first_location = await _context(db_session)
    second_location = Location(
        business_id=business.id,
        display_name="Cedar Shop East",
        address_line_1="20 Main St",
        city="Portland",
        region="Oregon",
        region_code="OR",
        postal_code="97202",
        country="US",
        timezone="America/Los_Angeles",
        active=True,
    )
    db_session.add(second_location)
    await db_session.flush()
    category, blue_dream = await _add_product(
        db_session,
        context,
        first_location,
        name="Blue Dream",
        brand="Cedar Farms",
        description="Citrus aroma, batch details from the grower.",
        availability=AvailabilityState.UNKNOWN,
        source_updated_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    _other_category, mint = await _add_product(
        db_session,
        context,
        first_location,
        name="Electric Mint",
        category_name="Edibles",
        availability=AvailabilityState.AVAILABLE,
        price_minor=1299,
        currency="USD",
    )
    await CatalogRepository(db_session, context.tenant).set_offering(
        location_id=second_location.id,
        product_id=blue_dream.id,
        availability=AvailabilityState.UNAVAILABLE,
        price_minor=1500,
        currency="USD",
    )
    await _add_product(
        db_session,
        context,
        first_location,
        name="Hidden Product",
        enabled=False,
    )
    _hidden_category, _unoffered = await _add_product(
        db_session,
        context,
        first_location,
        name="Not Offered",
        offered=False,
        category_name="Unlisted",
    )
    disabled_category = await CatalogRepository(
        db_session, context.tenant
    ).create_category("Disabled Category", enabled=False)
    disabled_category_product = await CatalogRepository(
        db_session, context.tenant
    ).create_product(category_id=disabled_category.id, name="Hidden Category Product")
    await CatalogRepository(db_session, context.tenant).set_offering(
        location_id=first_location.id,
        product_id=disabled_category_product.id,
    )

    executor = build_command_executor()
    listed = await executor.execute("/products", context)
    assert "Products at Cedar Shop Main:" in listed.output
    assert "Blue Dream" in listed.output and "Electric Mint" in listed.output
    assert "Hidden Product" not in listed.output
    assert "Not Offered" not in listed.output
    assert "Hidden Category Product" not in listed.output
    assert "Price: not listed" in listed.output
    assert "Availability: not reported" in listed.output
    assert "USD 12.99" in listed.output

    filtered = await executor.execute("/products flower", context)
    assert "Blue Dream" in filtered.output
    assert "Electric Mint" not in filtered.output
    assert (await executor.execute("/search blue DREAM citrus", context)).output.count(
        "Blue Dream"
    ) == 1
    assert (await executor.execute("/search Cedar Farms batch details", context)).output.count(
        "Blue Dream"
    ) == 1
    assert (await executor.execute("/search absent item", context)).output == (
        "No catalog matches for absent item at Cedar Shop Main."
    )
    with pytest.raises(CommandError) as empty_search:
        await executor.execute("/search   ", context)
    assert empty_search.value.code == "CATALOG_QUERY_REQUIRED"

    categories = await executor.execute("/categories", context)
    assert categories.output.splitlines() == [
        "Categories at Cedar Shop Main:",
        "- Edibles",
        "- Flower",
    ]
    assert "Unlisted" not in categories.output
    assert "Disabled Category" not in categories.output

    # Search input remains a bound literal pattern; SQL wildcard and syntax
    # characters cannot broaden it to unrelated products.
    special_category, special_product = await _add_product(
        db_session,
        context,
        first_location,
        name="100%_Mix",
        category_name="Special",
    )
    special = await executor.execute("/search 100%_Mix", context)
    assert "100%_Mix" in special.output
    literal_name = "20% Blue_Dream! \\O'Neil"
    await _add_product(
        db_session,
        context,
        first_location,
        name=literal_name,
        category_name="Literal Search Category",
    )
    literal = await executor.execute(f"/search {literal_name}", context)
    assert literal.output.count(literal_name) == 1
    category_only = await _add_product(
        db_session,
        context,
        first_location,
        name="Unique Menu Item",
        category_name="Apricot Category",
    )
    category_match = await executor.execute("/search Apricot", context)
    assert "Unique Menu Item" in category_match.output
    assert "Blue Dream" not in category_match.output
    injection = await executor.execute("/search %_' OR 1=1 --", context)
    assert "Blue Dream" not in injection.output
    assert "Electric Mint" not in injection.output

    await SessionService(db_session, context.tenant).set_location(
        context.customer_session_id,
        SessionLocationUpdate(selected_location_id=second_location.id),
    )
    east = await executor.execute("/products", context)
    assert "Availability: unavailable" in east.output
    assert "USD 15.00" in east.output
    assert "Electric Mint" not in east.output


async def test_local_provider_returns_no_fabricated_results_and_normalizes_provenance(
    db_session,
) -> None:
    context, _business, location = await _context(db_session)
    empty = await CatalogService(db_session, context.tenant).list_products(location.id)
    assert empty.items == ()
    result = await _add_product(
        db_session,
        context,
        location,
        name="Fact Product",
        source_updated_at=datetime(2026, 9, 20, 12, tzinfo=UTC),
    )
    listed = await CatalogService(db_session, context.tenant).list_products(location.id)
    assert listed.items[0].id == result[1].id
    assert listed.items[0].product_source == "local"
    assert listed.items[0].product_source_updated_at == datetime(2026, 9, 20, 12, tzinfo=UTC)
    assert listed.items[0].availability is AvailabilityState.UNKNOWN

    with pytest.raises(CommandError) as unknown_provider:
        await CatalogService(
            db_session, context.tenant, provider_key="not_registered"
        ).list_products(location.id)
    assert unknown_provider.value.code == "CATALOG_PROVIDER_UNKNOWN"
    assert unknown_provider.value.status_code == 503


async def test_provider_context_is_neutral_for_remote_style_implementations(
    db_session,
) -> None:
    context, _business, location = await _context(db_session)
    assert [field.name for field in fields(CatalogProviderContext)] == [
        "business_id",
        "location_id",
        "as_of",
        "result_limit",
    ]

    class RemoteStyleProvider:
        def __init__(self):
            self.received_context = None

        async def list_products(self, provider_context, *, category):
            assert not hasattr(provider_context, "session")
            self.received_context = provider_context
            return CatalogPage(())

        async def search_products(self, provider_context, *, query):
            assert not hasattr(provider_context, "session")
            return CatalogPage(())

        async def list_categories(self, provider_context):
            assert not hasattr(provider_context, "session")
            return CatalogPage(())

        async def list_deals(self, provider_context):
            assert not hasattr(provider_context, "session")
            return CatalogPage(())

    provider = RemoteStyleProvider()
    registry = CatalogProviderRegistry({"remote": provider})
    result = await CatalogService(
        db_session,
        context.tenant,
        provider_key="remote",
        providers=registry,
    ).list_products(location.id)

    assert result.items == ()
    assert provider.received_context.business_id == context.tenant.business_id
    assert provider.received_context.location_id == location.id


def test_search_expression_compiles_with_portable_postgresql_escape() -> None:
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from budbot.services.catalog_repository import _literal_search_expression

    compiled = select(CatalogProduct.name).where(
        _literal_search_expression(CatalogProduct.name, "O'Neil!")
    ).compile(dialect=postgresql.dialect())

    assert "ESCAPE '!'" in str(compiled)
    assert "O'Neil" not in str(compiled)
    assert list(compiled.params.values()) == ["%o'neil!!%"]


async def test_catalog_database_constraints_and_repository_reject_cross_tenant_links(
    db_session,
) -> None:
    context_a, business_a, location_a = await _context(db_session)
    context_b, business_b, location_b = await _context(
        db_session, business_name="Other Shop"
    )
    category_a, product_a = await _add_product(
        db_session, context_a, location_a, name="Tenant A Product"
    )
    _category_b, product_b = await _add_product(
        db_session, context_b, location_b, name="Tenant B Product"
    )
    repository_b = CatalogRepository(db_session, context_b.tenant)
    repository_a = CatalogRepository(db_session, context_a.tenant)

    with pytest.raises(ResourceNotFound):
        await repository_b.products.get(product_a.id, resource_name="catalog product")
    with pytest.raises(ResourceNotFound):
        await repository_a.products.get(product_b.id, resource_name="catalog product")
    with pytest.raises(ResourceNotFound):
        await repository_b.create_product(category_id=category_a.id, name="Cross tenant")
    with pytest.raises(ResourceNotFound):
        await repository_b.set_offering(
            location_id=location_b.id, product_id=product_a.id
        )
    with pytest.raises(ResourceNotFound):
        await repository_b.create_deal(
            title="Cross tenant product", description="Configured text.", product_id=product_a.id
        )
    with pytest.raises(ResourceNotFound):
        await repository_b.create_deal(
            title="Cross tenant category", description="Configured text.", category_id=category_a.id
        )

    # Composite foreign keys protect tenant integrity even when an ORM caller
    # bypasses the repository helpers.
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                ProductOffering(
                    business_id=business_b.id,
                    location_id=location_b.id,
                    product_id=product_a.id,
                    availability="unknown",
                    offered=True,
                )
            )
            await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                CatalogProduct(
                    business_id=business_b.id,
                    category_id=category_a.id,
                    name="Cross tenant category product",
                )
            )
            await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                CatalogDeal(
                    business_id=business_b.id,
                    location_id=location_b.id,
                    category_id=category_a.id,
                    title="Cross tenant category deal",
                    description="Configured text.",
                )
            )
            await db_session.flush()


async def test_catalog_deals_are_active_location_scoped_and_timezone_safe(db_session) -> None:
    context, business, location = await _context(db_session)
    other_location = Location(
        business_id=business.id,
        display_name="Cedar Other",
        address_line_1="20 Main St",
        city="Portland",
        region="Oregon",
        region_code="OR",
        postal_code="97202",
        country="US",
        timezone="America/Los_Angeles",
        active=True,
    )
    db_session.add(other_location)
    await db_session.flush()
    now = datetime(2026, 9, 23, 18, 0, tzinfo=UTC)
    repo = CatalogRepository(db_session, context.tenant)
    await repo.create_deal(
        title="Current", description="Configured factual terms.", starts_at=now,
        ends_at=now + timedelta(hours=1),
    )
    await repo.create_deal(
        title="Expired", description="Old configured terms.", ends_at=now
    )
    await repo.create_deal(
        title="Future", description="Future configured terms.", starts_at=now + timedelta(seconds=1)
    )
    await repo.create_deal(
        title="Disabled", description="Disabled configured terms.", enabled=False
    )
    await repo.create_deal(
        title="Other Location", description="Different location terms.",
        location_id=other_location.id,
    )
    result = await CatalogService(
        db_session, context.tenant, clock=lambda: now
    ).list_deals(location.id)
    assert [deal.title for deal in result.items] == ["Current"]
    assert result.items[0].description == "Configured factual terms."
    other_result = await CatalogService(
        db_session, context.tenant, clock=lambda: now
    ).list_deals(other_location.id)
    assert [deal.title for deal in other_result.items] == ["Current", "Other Location"]


async def test_product_linked_deals_only_appear_where_the_product_is_visible(
    db_session,
) -> None:
    context, business, first_location = await _context(db_session)
    second_location = Location(
        business_id=business.id,
        display_name="Cedar Other",
        address_line_1="20 Main St",
        city="Portland",
        region="Oregon",
        region_code="OR",
        postal_code="97202",
        country="US",
        timezone="America/Los_Angeles",
        active=True,
    )
    db_session.add(second_location)
    await db_session.flush()
    category, product = await _add_product(
        db_session, context, first_location, name="Only Here"
    )
    repo = CatalogRepository(db_session, context.tenant)
    await repo.create_deal(
        title="Product deal",
        description="Configured terms for Only Here.",
        product_id=product.id,
    )
    await repo.create_deal(
        title="Category deal",
        description="Configured terms for the Flower category.",
        category_id=category.id,
    )
    service = CatalogService(db_session, context.tenant)
    assert [deal.title for deal in (await service.list_deals(first_location.id)).items] == [
        "Category deal", "Product deal"
    ]
    assert (await service.list_deals(second_location.id)).items == ()

    product.enabled = False
    await db_session.flush()
    assert (await service.list_deals(first_location.id)).items == ()


async def test_service_bounds_provider_pages_and_normalizes_provider_failures(
    db_session,
) -> None:
    context, _business, location = await _context(db_session)

    class OversizedProvider:
        async def list_products(self, _context, *, category):
            items = tuple(
                ProductResult(
                    id=uuid4(),
                    name=f"Product {index:03d}",
                    brand=None,
                    category="General",
                    description=None,
                    availability=AvailabilityState.UNKNOWN,
                    price_minor=None,
                    currency=None,
                    quantity=None,
                    product_source="external",
                    product_source_updated_at=None,
                    offering_source="external",
                    offering_source_updated_at=None,
                )
                for index in range(100, 0, -1)
            )
            return CatalogPage(items)

        async def search_products(self, _context, *, query):
            return CatalogPage(())

        async def list_categories(self, _context):
            return CatalogPage(())

        async def list_deals(self, _context):
            return CatalogPage(())

    oversized_registry = CatalogProviderRegistry({"oversized": OversizedProvider()})
    bounded = await CatalogService(
        db_session,
        context.tenant,
        provider_key="oversized",
        providers=oversized_registry,
        result_limit=3,
    ).list_products(location.id)
    assert [product.name for product in bounded.items] == [
        "Product 097", "Product 098", "Product 099"
    ]
    assert bounded.has_more is True
    assert len(bounded.items) == 3

    class BrokenProvider(OversizedProvider):
        def __init__(self, error):
            self.error = error

        async def list_products(self, _context, *, category):
            raise self.error

    for error in (
        CatalogError("PRIVATE_PROVIDER_DETAIL"),
        RuntimeError("credential=do-not-expose"),
    ):
        registry = CatalogProviderRegistry({"broken": BrokenProvider(error)})
        with pytest.raises(CommandError) as unavailable:
            await CatalogService(
                db_session, context.tenant, provider_key="broken", providers=registry
            ).list_products(location.id)
        assert unavailable.value.code == "CATALOG_PROVIDER_UNAVAILABLE"
        assert unavailable.value.detail == "catalog data is temporarily unavailable"
        assert "credential" not in unavailable.value.detail


async def test_catalog_commands_require_locations_and_inactive_location_is_rejected(
    db_session,
) -> None:
    context, business, location = await _context(db_session, selected=False)
    with pytest.raises(CommandError) as required:
        await build_command_executor().execute("/products", context)
    assert required.value.code == "CATALOG_LOCATION_REQUIRED"

    context, business, location = await _context(db_session)
    location.active = False
    await db_session.flush()
    with pytest.raises(CommandError) as inactive:
        await build_command_executor().execute("/products", context)
    assert inactive.value.code == "LOCATION_INACTIVE"


async def test_catalog_commands_use_m55_compliance_for_general_or_nm_and_fail_closed(
    db_session,
) -> None:
    executor = build_command_executor()

    general, _business, general_location = await _context(db_session)
    await _add_product(db_session, general, general_location, name="Retail Item")
    await CatalogRepository(db_session, general.tenant).create_deal(
        title="Retail Deal", description="Configured retail promotion."
    )
    assert "Retail Item" in (await executor.execute("/products", general)).output
    assert "Retail Item" in (await executor.execute("/search Retail", general)).output
    assert "Flower" in (await executor.execute("/categories", general)).output
    assert "Retail Deal" in (await executor.execute("/deals", general)).output

    for region in ("OR", "NM"):
        context, _business, location = await _context(
            db_session,
            business_name=f"Cannabis {region}",
            domain="cannabis",
            region_code=region,
        )
        await _add_product(db_session, context, location, name=f"{region} Product")
        await CatalogRepository(db_session, context.tenant).create_deal(
            title=f"{region} Deal", description="Configured regulated promotion."
        )
        for command in (
            "/products",
            f"/search {region} Product",
            "/categories",
            "/deals",
        ):
            with pytest.raises(ComplianceError) as age_required:
                await executor.execute(command, context)
            assert age_required.value.code == "AGE_VERIFICATION_REQUIRED"
        metadata = await executor.metadata(context)
        assert "categories" not in {item.name for item in metadata}
        await SessionService(context.session, context.tenant).attest(
            context.customer_session_id,
            AgeAttestationRequest(confirmed_21_or_older=True),
        )
        assert f"{region} Product" in (
            await executor.execute("/products", context)
        ).output
        assert f"{region} Product" in (
            await executor.execute(f"/search {region} Product", context)
        ).output
        assert "- Flower" in (await executor.execute("/categories", context)).output
        assert f"{region} Deal" in (await executor.execute("/deals", context)).output

    no_location, _business, _location = await _context(
        db_session,
        business_name="Cannabis No Location",
        domain="cannabis",
        selected=False,
    )
    with pytest.raises(ComplianceError) as location_required:
        await executor.execute("/products", no_location)
    assert location_required.value.code == "COMPLIANCE_LOCATION_REQUIRED"

    unsupported, _business, _location = await _context(
        db_session,
        business_name="Cannabis Unsupported",
        domain="cannabis",
        region_code="TX",
    )
    with pytest.raises(ComplianceError) as unavailable:
        await executor.execute("/products", unsupported)
    assert unavailable.value.code == "COMPLIANCE_PROFILE_UNAVAILABLE"


async def test_catalog_flags_filter_help_metadata_and_execution(db_session) -> None:
    context, business, location = await _context(db_session)
    executor = build_command_executor()
    expected = {"products", "search", "categories", "deals"}
    assert expected <= {item.name for item in await executor.metadata(context)}

    business.products_enabled = False
    business.promotions_enabled = False
    await db_session.flush()
    assert expected.isdisjoint({item.name for item in await executor.metadata(context)})
    for command in ("/products", "/search item", "/categories", "/deals"):
        with pytest.raises(CommandError) as disabled:
            await executor.execute(command, context)
        assert disabled.value.code == "COMMAND_UNAVAILABLE"


async def test_catalog_stale_binding_keeps_m55_safe_public_recovery(db_session) -> None:
    context, _business, location = await _context(
        db_session, domain="cannabis", region_code="OR"
    )
    location.region_code = "NM"
    await db_session.flush()
    with pytest.raises(ComplianceError) as stale:
        await build_command_executor().execute("/products", context)
    assert stale.value.code == "COMPLIANCE_PROFILE_MISMATCH"
    recovered = await build_command_executor().execute("/locations", context)
    assert "Cedar Shop Main" in recovered.output


async def test_catalog_results_are_bounded_and_report_overflow(db_session) -> None:
    context, _business, location = await _context(db_session)
    for index in range(27):
        await _add_product(
            db_session,
            context,
            location,
            name=f"Product {index:02d}",
        )
    result = await CatalogService(db_session, context.tenant, result_limit=5).list_products(
        location.id
    )
    assert len(result.items) == 5
    assert result.has_more is True
    exact_limit = await CatalogService(
        db_session, context.tenant, result_limit=27
    ).list_products(location.id)
    assert len(exact_limit.items) == 27
    assert exact_limit.has_more is False
    command = await build_command_executor().execute("/products", context)
    assert "More results are available" in command.output
    assert command.output.count("  Price:") == 25


async def test_generic_catalog_capabilities_are_not_safe_public() -> None:
    from budbot.compliance.types import SAFE_PUBLIC_CAPABILITIES, ComplianceCapability

    assert ComplianceCapability.CATALOG_PRODUCTS not in SAFE_PUBLIC_CAPABILITIES
    assert ComplianceCapability.CATALOG_SEARCH not in SAFE_PUBLIC_CAPABILITIES
    assert ComplianceCapability.CATALOG_DEALS not in SAFE_PUBLIC_CAPABILITIES


def test_currency_rendering_uses_minor_unit_scales_without_float() -> None:
    from budbot.commands.customer.catalog import format_minor_units

    assert format_minor_units(1299, "usd") == "USD 12.99"
    assert format_minor_units(1000, "jpy") == "JPY 1,000"
    assert format_minor_units(1234, "kwd") == "KWD 1.234"
    with pytest.raises(ValueError, match="ISO 4217"):
        ProductOffering(currency="ZZZ")
