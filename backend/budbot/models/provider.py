"""One safe provider profile and separate encrypted credential per tenant."""
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID
from budbot.database.base import Base, TimestampMixin

class BusinessAIProfile(TimestampMixin, Base):
    __tablename__ = "business_ai_profiles"
    __table_args__ = (CheckConstraint("provider IN ('openrouter','openai_compatible','openai','anthropic')", name="ck_ai_profile_provider"),)
    business_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(2048))
    tool_calling: Mapped[bool] = mapped_column(Boolean, nullable=False)

class ProviderCredential(TimestampMixin, Base):
    __tablename__ = "provider_credentials"
    business_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("business_ai_profiles.business_id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
