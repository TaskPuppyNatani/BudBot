"""Owner catalog writes and public deterministic product/FAQ search."""

import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from budbot.models.business import Business
from budbot.models.catalog import CatalogProduct, ProductOffering, CatalogDeal
from budbot.models.location import Location
from budbot.models.knowledge import FAQEntry
from budbot.models.user import BusinessMembership
from budbot.core.tenancy import TenantContext
from budbot.services.catalog_repository import CatalogRepository


@pytest.fixture
async def catalog(m2_client, db_session):
    me = (await m2_client.get("/api/v1/auth/me")).json()
    m2_client.headers["X-CSRF-Token"] = me["csrf_token"]
    bid = me["businesses"][0]["business_id"]
    foreign = Business(display_name="Other store", industry="general_retail")
    db_session.add(foreign); await db_session.flush()
    locations = [Location(business_id=tenant, display_name=name, address_line_1="10 Main",
        city="Portland", region="Oregon", region_code="OR", postal_code="97201",
        country="US", timezone="America/Los_Angeles")
        for tenant, name in [(UUID(bid), "Main"), (UUID(bid), "East"), (foreign.id, "Foreign")]]
    db_session.add_all(locations); await db_session.commit()
    return SimpleNamespace(client=m2_client, db=db_session, bid=bid, foreign=str(foreign.id),
        base=f"/api/v1/businesses/{bid}", locations=[str(row.id) for row in locations])


def product(f, **overrides):
    return {"name": "Cedar tea", "category": "Drinks", "brand": "Local brand", "description": "private-description-marker",
        "offerings": [{"location_id": f.locations[0], "availability": "available", "price": "12.50", "currency": "USD"}], **overrides}


async def create(f, **values):
    response = await f.client.post(f.base + "/catalog/products", json=product(f, **values))
    assert response.status_code == 201, response.text
    return response.json()


async def command(f, text, location=None):
    headers = {"X-BudBot-Business-ID": f.bid}
    session = await f.client.post("/api/v1/sessions", headers=headers, json={"selected_location_id": location or f.locations[0]})
    assert session.status_code == 201, session.text
    return await f.client.post("/api/v1/commands/execute", headers=headers, json={"session_id": session.json()["id"], "input": text})


async def test_catalog_crud_visibility_location_prices_deals_and_safe_audit(catalog):
    f = catalog
    row = await create(f)
    sibling = await create(f, name="Keep tea")
    assert row["offerings"][0]["price"] == "12.50"
    assert "Cedar tea" in (await command(f, "/products")).json()["output"]
    assert "Cedar tea" not in (await command(f, "/products", f.locations[1])).json()["output"]
    changed = await f.client.put(f.base + f"/catalog/products/{row['id']}", json=product(f, name="Changed tea", category="Warm drinks", offerings=[{
        "location_id": f.locations[1], "price": "150", "currency": "JPY", "availability": "available"}]))
    assert changed.status_code == 200, changed.text
    assert changed.json()["category"] == "Warm drinks"
    assert "Changed tea" not in (await command(f, "/products")).json()["output"]
    assert "JPY 150" in (await command(f, "/products", f.locations[1])).json()["output"]
    hidden = await f.client.patch(f.base + f"/catalog/products/{row['id']}", json={"enabled": False})
    assert hidden.status_code == 200 and not hidden.json()["enabled"]
    assert "Changed tea" not in (await command(f, "/products", f.locations[1])).json()["output"]
    assert await f.db.get(CatalogProduct, UUID(row["id"])) is not None  # Honest reversible removal.
    await f.client.patch(f.base + f"/catalog/products/{row['id']}", json={"enabled": True})
    assert "Changed tea" in (await command(f, "/products", f.locations[1])).json()["output"]
    deal = await f.client.post(f.base + "/catalog/deals", json={"title": "Tea deal", "description": "Configured terms", "location_id": f.locations[1]})
    assert deal.status_code == 201, deal.text
    assert "Tea deal" not in (await command(f, "/deals")).json()["output"]
    assert "Tea deal" in (await command(f, "/deals", f.locations[1])).json()["output"]
    updated = await f.client.put(f.base + f"/catalog/deals/{deal.json()['id']}", json={"title": "Updated deal", "description": "Terms", "location_id": None})
    assert updated.status_code == 200
    await f.client.patch(f.base + f"/catalog/deals/{deal.json()['id']}", json={"enabled": False})
    assert "Updated deal" not in (await command(f, "/deals")).json()["output"]
    listing = (await f.client.get(f.base + "/catalog")).json()
    assert len(listing["products"]) == 2
    assert next(p for p in listing["products"] if p["id"] == sibling["id"]) == sibling
    audit = (await f.client.get(f.base + "/audit")).json()["items"]
    assert {a["event_type"] for a in audit} >= {"admin.catalog.product.created", "admin.catalog.product.updated", "admin.catalog.product.hidden", "admin.catalog.product.restored", "admin.catalog.deal.created", "admin.catalog.deal.updated", "admin.catalog.deal.hidden"}
    assert "private-description-marker" not in json.dumps(audit)
    assert all(set(a["details"]) <= {"enabled", "changed_fields"} for a in audit)


@pytest.mark.parametrize("role,allowed", [("owner", True), ("admin", True), ("manager", False), ("viewer", False)])
async def test_catalog_existing_business_permission_policy(catalog, role, allowed):
    f = catalog
    membership = await f.db.scalar(select(BusinessMembership).where(BusinessMembership.business_id == UUID(f.bid)))
    membership.role = role; await f.db.commit()
    assert (await f.client.get(f.base + "/catalog")).status_code == 200
    response = await f.client.post(f.base + "/catalog/products", json=product(f))
    assert response.status_code == (201 if allowed else 403)


async def test_catalog_auth_csrf_and_tenant_boundaries(catalog):
    f = catalog; row = await create(f)
    foreign_base = f"/api/v1/businesses/{f.foreign}/catalog"
    assert (await f.client.get(foreign_base)).status_code == 404
    assert (await f.client.post(foreign_base + "/products", json=product(f))).status_code == 404
    for path in (f"/catalog/products/{row['id']}", f"/catalog/deals/{row['id']}"):
        assert (await f.client.patch(f"/api/v1/businesses/{f.foreign}" + path, json={"enabled": False})).status_code == 404
    before = (await f.client.get(f.base + "/catalog")).json()
    assert (await f.client.put(f.base + f"/catalog/products/{row['id']}", json=product(f, name="Must rollback", offerings=[{"location_id": f.locations[2]}]))).status_code == 404
    assert (await f.client.post(f.base + "/catalog/deals", json={"title": "No", "description": "No", "location_id": f.locations[2]})).status_code == 404
    assert (await f.client.get(f.base + "/catalog")).json() == before
    csrf = f.client.headers.pop("X-CSRF-Token")
    assert (await f.client.patch(f.base + f"/catalog/products/{row['id']}", json={"enabled": False})).status_code == 403
    assert (await f.client.post(f.base + "/catalog/deals", json={"title": "No", "description": "No"})).status_code == 403
    f.client.headers["X-CSRF-Token"] = csrf
    f.client.cookies.clear()
    assert (await f.client.get(f.base + "/catalog", headers={"X-BudBot-Business-ID": f.bid})).status_code == 401
    assert (await f.client.post(f.base + "/catalog/products", json=product(f))).status_code == 401


async def test_member_of_two_businesses_cannot_move_foreign_catalog_records(catalog):
    f = catalog
    me = (await f.client.get("/api/v1/auth/me")).json()
    f.client.headers["X-CSRF-Token"] = me["csrf_token"]
    f.db.add(BusinessMembership(user_id=UUID(me["user"]["id"]), business_id=UUID(f.foreign), role="owner"))
    repo = CatalogRepository(f.db, TenantContext(UUID(f.foreign)))
    category = await repo.create_category("Foreign category")
    foreign_product = await repo.create_product(category_id=category.id, name="Foreign tea")
    foreign_deal = await repo.create_deal(title="Foreign deal", description="Foreign terms")
    await f.db.commit()
    product_id, deal_id = str(foreign_product.id), str(foreign_deal.id)
    assert (await f.client.get(f"/api/v1/businesses/{f.foreign}/catalog")).status_code == 200
    assert (await f.client.put(f.base + f"/catalog/products/{product_id}", json=product(f))).status_code == 404
    assert (await f.client.patch(f.base + f"/catalog/products/{product_id}", json={"enabled": False})).status_code == 404
    assert (await f.client.put(f.base + f"/catalog/deals/{deal_id}", json={"title": "Stolen", "description": "No"})).status_code == 404
    assert (await f.client.patch(f.base + f"/catalog/deals/{deal_id}", json={"enabled": False})).status_code == 404
    assert (await f.client.get(f.base + "/catalog")).json()["products"] == []


@pytest.mark.parametrize("override", [{"name": " "}, {"category": ""}, {"offerings": [{"location_id": "bad"}]},
    {"offerings": [{"location_id": "00000000-0000-0000-0000-000000000000", "price": "1.001", "currency": "USD"}]},
    {"offerings": [{"location_id": "00000000-0000-0000-0000-000000000000", "price": "-1", "currency": "USD"}]},
    {"offerings": [{"location_id": "00000000-0000-0000-0000-000000000000", "price": "10", "currency": "BAD"}]}])
async def test_catalog_validation_has_no_partial_writes(catalog, override):
    f = catalog
    response = await f.client.post(f.base + "/catalog/products", json=product(f, **override))
    assert response.status_code == 422
    assert (await f.client.get(f.base + "/catalog")).json()["products"] == []


async def test_search_combines_public_effective_faqs_and_visible_products(catalog):
    f = catalog
    await create(f)
    f.db.add(FAQEntry(business_id=UUID(f.foreign), question="Tea foreign?", answer="Foreign secret marker"))
    await f.db.commit()
    for values in [
        {"question": "Tea parking?", "answer": "Business fallback"},
        {"question": "Tea parking?", "answer": "Local public answer", "location_id": f.locations[0]},
        {"question": "Tea private?", "answer": "Private marker", "is_public": False},
        {"question": "Tea disabled?", "answer": "Disabled marker", "enabled": False},
        {"question": "Tea east?", "answer": "East marker", "location_id": f.locations[1]},
    ]:
        response = await f.client.post(f.base + "/faqs", json=values)
        assert response.status_code == 201, response.text
    response = await command(f, "/search tea")
    assert response.status_code == 200, response.text
    output = response.json()["output"]
    assert "Products" in output and "Cedar tea" in output and "Store information" in output
    assert output.count("Tea parking?") == 1 and "Local public answer" in output
    assert all(marker not in output for marker in ["Business fallback", "Private marker", "Disabled marker", "East marker", "Foreign secret marker", f.bid])
    east = (await command(f, "/search tea", f.locations[1])).json()["output"]
    assert "Cedar tea" not in east and "Business fallback" in east and "East marker" in east
    await f.client.patch(f.base, json={"faq_enabled": False})
    assert "Store information" not in (await command(f, "/search tea")).json()["output"]


@pytest.mark.parametrize("values", [{"enabled": False}, {"offerings": []}, {"offerings": [{"availability": "unavailable"}]}])
async def test_customer_products_and_search_exclude_hidden_not_offered_and_unavailable(catalog, values):
    f = catalog
    if values.get("offerings"):
        values["offerings"][0]["location_id"] = f.locations[0]
    await create(f, **values)
    assert "Cedar tea" not in (await command(f, "/products")).json()["output"]
    assert "Cedar tea" not in (await command(f, "/search tea")).json()["output"]


async def test_search_still_enforces_customer_compliance(catalog):
    f = catalog
    await create(f)
    (await f.db.get(Business, UUID(f.bid))).compliance_domain = "cannabis"
    await f.db.commit()
    response = await command(f, "/search tea")
    assert response.status_code == 403 and response.json()["code"] == "AGE_VERIFICATION_REQUIRED"


@pytest.mark.parametrize("role,expected", [("owner", 204), ("admin", 204), ("manager", 403), ("viewer", 403)])
async def test_permanent_delete_role_policy(catalog, role, expected):
    f = catalog; row = await create(f)
    membership = await f.db.scalar(select(BusinessMembership).where(BusinessMembership.business_id == UUID(f.bid)))
    membership.role = role; await f.db.commit()
    assert (await f.client.delete(f.base + f"/catalog/products/{row['id']}")).status_code == expected


async def test_permanent_delete_cascades_only_target_and_publishes_safe_audit(catalog):
    f = catalog; row = await create(f); sibling = await create(f, name="Keep tea")
    repo = CatalogRepository(f.db, TenantContext(UUID(f.bid)))
    linked = await repo.create_deal(title="Linked", description="Do not audit this", product_id=UUID(row["id"]))
    unrelated = await repo.create_deal(title="Keep deal", description="Keep")
    linked_id, unrelated_id = linked.id, unrelated.id
    await f.db.commit()
    assert (await f.client.delete(f.base + f"/catalog/products/{row['id']}")).status_code == 204
    listing = (await f.client.get(f.base + "/catalog")).json()
    assert [p["id"] for p in listing["products"]] == [sibling["id"]]
    assert await f.db.scalar(select(CatalogProduct).where(CatalogProduct.id == UUID(row["id"]))) is None
    assert await f.db.scalar(select(ProductOffering).where(ProductOffering.product_id == UUID(row["id"]))) is None
    assert await f.db.scalar(select(CatalogDeal).where(CatalogDeal.id == linked_id)) is None
    assert await f.db.scalar(select(CatalogDeal).where(CatalogDeal.id == unrelated_id)) is not None
    for text in ("/products", "/search tea"):
        output = (await command(f, text)).json()["output"]
        assert "Cedar tea" not in output and "Keep tea" in output
    audit = (await f.client.get(f.base + "/audit")).json()["items"]
    event = next(e for e in audit if e["event_type"] == "admin.catalog.product.deleted")
    assert event["resource_id"] == row["id"] and event["details"] == {}
    assert "Do not audit this" not in json.dumps(audit)
    assert (await f.client.delete(f.base + f"/catalog/products/{row['id']}")).status_code == 404


async def test_permanent_delete_csrf_auth_and_foreign_product_protection(catalog):
    f = catalog; row = await create(f)
    repo = CatalogRepository(f.db, TenantContext(UUID(f.foreign)))
    category = await repo.create_category("Foreign")
    foreign = await repo.create_product(category_id=category.id, name="Foreign")
    foreign_id = str(foreign.id); await f.db.commit()
    assert (await f.client.delete(f.base + f"/catalog/products/{foreign_id}")).status_code == 404
    csrf = f.client.headers.pop("X-CSRF-Token")
    assert (await f.client.delete(f.base + f"/catalog/products/{row['id']}")).status_code == 403
    f.client.headers["X-CSRF-Token"] = csrf
    assert len((await f.client.get(f.base + "/catalog")).json()["products"]) == 1
    f.client.cookies.clear()
    assert (await f.client.delete(f.base + f"/catalog/products/{row['id']}", headers={"X-BudBot-Business-ID": f.bid})).status_code == 401
