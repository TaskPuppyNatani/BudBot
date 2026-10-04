"""Bounded image and branding inputs shared by authenticated editors."""

from pydantic import Field, model_validator
from budbot.schemas.common import DomainSchema, HexColor, Name, ShortText
from budbot.services.local_asset_service import MAX_IMAGE_BYTES

MAX_ENCODED_IMAGE_CHARS = ((MAX_IMAGE_BYTES + 2) // 3) * 4


class EncodedImage(DomainSchema):
    content_base64: str = Field(min_length=4, max_length=MAX_ENCODED_IMAGE_CHARS)


class BrandingUpdate(DomainSchema):
    display_name: Name | None = None
    assistant_display_name: Name | None = None
    greeting: ShortText | None = None
    primary_brand_color: HexColor | None = None
    business_logo: EncodedImage | None = None
    assistant_avatar: EncodedImage | None = None
    remove_business_logo: bool = False
    remove_assistant_avatar: bool = False

    @model_validator(mode="after")
    def validate_asset_actions(self) -> "BrandingUpdate":
        if self.business_logo is not None and self.remove_business_logo:
            raise ValueError("Choose a business logo or remove it, not both.")
        if self.assistant_avatar is not None and self.remove_assistant_avatar:
            raise ValueError("Choose an assistant avatar or remove it, not both.")
        for field in ("display_name", "assistant_display_name", "greeting"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        if not self.model_fields_set:
            raise ValueError("At least one branding change must be supplied.")
        return self
