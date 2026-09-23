"""Import domain models so SQLAlchemy and Alembic receive complete metadata."""
from budbot.models.knowledge import FAQEntry
from budbot.models.catalog import (
    CatalogCategory,
    CatalogDeal,
    CatalogProduct,
    ProductOffering,
)

from budbot.models.assistant import AssistantConfiguration, LocationAssistantOverride
from budbot.models.business import Business
from budbot.models.location import Location, LocationHours
from budbot.models.session import CustomerSession
from budbot.models.user import BusinessMembership, UserAccount

__all__ = [
    "AssistantConfiguration",
    "Business",
    "BusinessMembership",
    "CatalogCategory",
    "CatalogDeal",
    "CatalogProduct",
    "CustomerSession",
    "FAQEntry",
    "Location",
    "LocationAssistantOverride",
    "LocationHours",
    "ProductOffering",
    "UserAccount",
]
