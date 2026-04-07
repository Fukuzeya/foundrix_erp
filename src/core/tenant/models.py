"""Public schema models for tenant management and module activation."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class Tenant(UUIDMixin, TimestampMixin, Base):
    """Represents a single tenant (company) in the platform.

    Each tenant gets an isolated PostgreSQL schema named ``tenant_{slug}``.
    """

    __tablename__ = "tenants"
    __table_args__ = {"schema": "public"}

    slug: Mapped[str] = mapped_column(
        String(63),
        unique=True,
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    subscription_tier: Mapped[str] = mapped_column(
        String(50),
        server_default=text("'free'"),
    )

    # Relationships
    modules: Mapped[list["TenantModule"]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Tenant slug={self.slug!r} active={self.is_active}>"


class TenantModule(UUIDMixin, Base):
    """Tracks which modules are activated for a given tenant."""

    __tablename__ = "tenant_modules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "module_name", name="uq_tenant_modules_tenant_module"),
        {"schema": "public"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public.tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    module_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    activated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    # Relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="modules")

    def __repr__(self) -> str:
        return f"<TenantModule tenant={self.tenant_id} module={self.module_name!r} active={self.is_active}>"
