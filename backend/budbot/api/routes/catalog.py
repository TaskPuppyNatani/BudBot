"""Tenant-authorized catalog administration, separate from customer commands."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from budbot.api.dependencies import AdminAccess, get_session, require_business_permission
from budbot.schemas.catalog import CatalogRead, DealInput, DealRead, ProductInput, ProductRead, VisibilityInput
from budbot.services.catalog_admin_service import CatalogAdminService

router = APIRouter(prefix="/api/v1/businesses/{business_id}/catalog", tags=["catalog"])
Session = Annotated[AsyncSession, Depends(get_session)]
ReadAccess = Annotated[AdminAccess, Depends(require_business_permission("business.read"))]
WriteAccess = Annotated[AdminAccess, Depends(require_business_permission("business.write", csrf=True))]


@router.get("", response_model=CatalogRead)
async def list_catalog(business_id: UUID, session: Session, access: ReadAccess):
    return await CatalogAdminService(session, access.tenant).list_catalog()


@router.post("/products", response_model=ProductRead, status_code=201)
async def create_product(business_id: UUID, payload: ProductInput, session: Session, access: WriteAccess):
    return await CatalogAdminService(session, access.tenant).save_product(payload, access.user_id)


@router.put("/products/{product_id}", response_model=ProductRead)
async def update_product(business_id: UUID, product_id: UUID, payload: ProductInput, session: Session, access: WriteAccess):
    return await CatalogAdminService(session, access.tenant).save_product(payload, access.user_id, product_id)


@router.patch("/products/{product_id}", response_model=ProductRead)
async def product_visibility(business_id: UUID, product_id: UUID, payload: VisibilityInput, session: Session, access: WriteAccess):
    return await CatalogAdminService(session, access.tenant).set_visibility("product", product_id, payload.enabled, access.user_id)


@router.delete("/products/{product_id}", status_code=204)
async def delete_product(business_id: UUID, product_id: UUID, session: Session, access: WriteAccess):
    await CatalogAdminService(session, access.tenant).delete_product(product_id, access.user_id)


@router.post("/deals", response_model=DealRead, status_code=201)
async def create_deal(business_id: UUID, payload: DealInput, session: Session, access: WriteAccess):
    return await CatalogAdminService(session, access.tenant).save_deal(payload, access.user_id)


@router.put("/deals/{deal_id}", response_model=DealRead)
async def update_deal(business_id: UUID, deal_id: UUID, payload: DealInput, session: Session, access: WriteAccess):
    return await CatalogAdminService(session, access.tenant).save_deal(payload, access.user_id, deal_id)


@router.patch("/deals/{deal_id}", response_model=DealRead)
async def deal_visibility(business_id: UUID, deal_id: UUID, payload: VisibilityInput, session: Session, access: WriteAccess):
    return await CatalogAdminService(session, access.tenant).set_visibility("deal", deal_id, payload.enabled, access.user_id)
