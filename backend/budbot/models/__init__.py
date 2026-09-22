"""Import M2 models so SQLAlchemy and Alembic receive complete metadata."""

from budbot.models.assistant import AssistantConfiguration, LocationAssistantOverride
from budbot.models.business import Business
from budbot.models.location import Location, LocationHours
from budbot.models.session import CustomerSession
from budbot.models.user import BusinessMembership, UserAccount

__all__ = [
    "AssistantConfiguration",
    "Business",
    "BusinessMembership",
    "CustomerSession",
    "Location",
    "LocationAssistantOverride",
    "LocationHours",
    "UserAccount",
]
