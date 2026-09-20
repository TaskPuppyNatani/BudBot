"""Declarative metadata for future Alembic-managed domain models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base for SQLAlchemy models introduced by later milestones."""
