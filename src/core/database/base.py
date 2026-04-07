"""SQLAlchemy declarative base, naming conventions, and shared mixins."""

import uuid
from datetime import datetime

from sqlalchemy import MetaData, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# Alembic-friendly naming conventions so that constraints get deterministic names.
# This avoids issues when auto-generating migrations across databases.
naming_convention: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models in Foundrix."""

    metadata = MetaData(naming_convention=naming_convention)


class UUIDMixin:
    """Mixin that provides a UUID primary key with a server-side default."""

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """Mixin that adds created_at and updated_at columns with server defaults."""

    created_at: Mapped[datetime] = mapped_column(
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("now()"),
        onupdate=text("now()"),
    )
