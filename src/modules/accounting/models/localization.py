"""Fiscal Localization Package models.

Localization packages pre-configure databases with country-specific accounting
setups including charts of accounts, tax definitions, fiscal positions, and
formatting preferences. Each package targets a specific country (ISO 3166-1)
and can be installed once per company to bootstrap the accounting module.

Install logs track every installation attempt, recording how many entities
were created and whether the process completed successfully.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class LocalizationPackage(UUIDMixin, TimestampMixin, Base):
    """A country-specific fiscal localization package.

    Contains template data for chart of accounts, taxes, and fiscal positions
    following the accounting standards and tax regulations of a specific country.
    Also stores locale-specific formatting preferences (date format, number
    separators) and fiscal year conventions.
    """

    __tablename__ = "localization_packages"
    __table_args__ = (
        UniqueConstraint("country_code", name="uq_localization_packages_country_code"),
        Index("ix_localization_packages_country_code", "country_code"),
        Index("ix_localization_packages_is_active", "is_active"),
    )

    country_code: Mapped[str] = mapped_column(
        String(2), nullable=False,
        doc="ISO 3166-1 alpha-2 country code.",
    )
    country_name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        doc="Human-readable country name.",
    )
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False,
        doc="ISO 4217 default currency code for this country.",
    )
    version: Mapped[str] = mapped_column(
        String(20), server_default=text("'1.0'"),
        doc="Package version for tracking template updates.",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Template data (JSON blobs) ────────────────────────────────────
    chart_template_data: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        doc="Pre-defined chart of accounts entries.",
    )
    tax_template_data: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        doc="Pre-defined tax definitions.",
    )
    fiscal_position_data: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        doc="Pre-defined fiscal position mappings.",
    )

    # ── Legal / reporting ─────────────────────────────────────────────
    legal_statement_types: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(50)), nullable=True,
        doc="Legal statement types required in this jurisdiction.",
    )

    # ── Locale formatting ─────────────────────────────────────────────
    date_format: Mapped[str] = mapped_column(
        String(20), server_default=text("'%Y-%m-%d'"),
    )
    decimal_separator: Mapped[str] = mapped_column(
        String(1), server_default=text("'.'"),
    )
    thousands_separator: Mapped[str] = mapped_column(
        String(1), server_default=text("','"),
    )

    # ── Fiscal year defaults ──────────────────────────────────────────
    fiscal_year_start_month: Mapped[int] = mapped_column(
        Integer, server_default=text("1"),
        doc="Month (1-12) when the fiscal year starts.",
    )
    fiscal_year_start_day: Mapped[int] = mapped_column(
        Integer, server_default=text("1"),
        doc="Day of month when the fiscal year starts.",
    )

    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    # ── Relationships ─────────────────────────────────────────────────
    install_logs: Mapped[list["LocalizationInstallLog"]] = relationship(
        back_populates="package",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<LocalizationPackage country={self.country_code!r} "
            f"name={self.country_name!r} v{self.version}>"
        )


class LocalizationInstallLog(UUIDMixin, TimestampMixin, Base):
    """Tracks each installation of a localization package.

    Records how many accounts, taxes, and fiscal positions were created,
    as well as the overall status and any error messages.
    """

    __tablename__ = "localization_install_logs"
    __table_args__ = (
        Index("ix_localization_install_logs_package_id", "package_id"),
        Index("ix_localization_install_logs_company_id", "company_id"),
    )

    package_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("localization_packages.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    installed_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(),
    )
    accounts_created: Mapped[int] = mapped_column(
        Integer, server_default=text("0"),
    )
    taxes_created: Mapped[int] = mapped_column(
        Integer, server_default=text("0"),
    )
    fiscal_positions_created: Mapped[int] = mapped_column(
        Integer, server_default=text("0"),
    )
    status: Mapped[str] = mapped_column(
        String(20), server_default=text("'completed'"),
        doc="One of: completed, partial, failed.",
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    installed_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    # ── Relationships ─────────────────────────────────────────────────
    package: Mapped["LocalizationPackage"] = relationship(
        back_populates="install_logs",
    )

    def __repr__(self) -> str:
        return (
            f"<LocalizationInstallLog package={self.package_id} "
            f"status={self.status!r}>"
        )
