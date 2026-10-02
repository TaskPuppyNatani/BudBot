"""Customer-session-scoped identity and presentation data for the widget."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from budbot.compliance.age_gate import AgeGateStatus
from budbot.compliance.resolver import ComplianceResolver
from budbot.core.exceptions import ComplianceError
from budbot.core.tenancy import TenantContext
from budbot.schemas.widget import (
    WidgetAssistantRead,
    WidgetBootstrapRead,
    WidgetBusinessRead,
    WidgetComplianceRead,
    WidgetLocationRead,
)
from budbot.services.assistant_service import AssistantService
from budbot.services.business_service import BusinessService
from budbot.services.location_service import LocationService
from budbot.services.session_service import SessionService


class WidgetService:
    """Project presentation fields after existing customer session validation."""

    def __init__(self, session: AsyncSession, tenant: TenantContext) -> None:
        self.session = session
        self.tenant = tenant

    async def get(self, session_id: UUID) -> WidgetBootstrapRead:
        # Reuse the customer session's tenant, active-business and compliance
        # binding checks. A business UUID alone grants no session data access.
        customer = await SessionService(self.session, self.tenant).get(session_id)
        if customer.age_gate_status == AgeGateStatus.EXPIRED:
            raise ComplianceError(
                "SESSION_EXPIRED",
                "the customer session has expired; create a new session",
                status_code=410,
            )
        business = await BusinessService(self.session).get_for_customer(
            self.tenant, self.tenant.business_id
        )
        assistants = AssistantService(self.session, self.tenant)
        if customer.selected_location_id is None:
            assistant = await assistants.get(business.id)
            primary_color = (
                assistant.primary_color_override or business.primary_brand_color
            )
        else:
            assistant = await assistants.resolve(
                business.id, customer.selected_location_id
            )
            primary_color = assistant.primary_color
        locations = await LocationService(self.session, self.tenant).list_locations()
        resolution = await ComplianceResolver().resolve_session(
            self.session, business, customer
        )
        profile = resolution.profile
        return WidgetBootstrapRead(
            business=WidgetBusinessRead(
                display_name=business.display_name,
                logo_reference=business.logo_reference,
                primary_brand_color=business.primary_brand_color,
            ),
            assistant=WidgetAssistantRead(
                display_name=assistant.display_name,
                greeting=assistant.greeting,
                avatar_reference=assistant.avatar_reference,
                primary_color=primary_color,
            ),
            locations=[
                WidgetLocationRead(id=item.id, display_name=item.display_name)
                for item in locations
            ],
            compliance=WidgetComplianceRead(
                requires_age_gate=(
                    profile.requires_age_gate
                    if profile else business.compliance_domain == "cannabis"
                ),
                website_attestation_notice=(
                    profile.website_attestation_notice
                    if profile else
                    "Select a supported location before completing age confirmation."
                ),
            ),
        )
