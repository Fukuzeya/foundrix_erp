"""Asset management and deferred revenue/expense models.

Tracks fixed assets with automatic depreciation schedule generation.
Also handles deferred revenue and expense recognition.
"""

import uuid
from datetime import date

from sqlalchemy import (
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class AssetGroup(UUIDMixin, TimestampMixin, Base):
    """Asset group / depreciation profile."""

    __tablename__ = "asset_groups"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="One of: asset, expense, revenue.",
    )
    method: Mapped[str] = mapped_column(
        String(20), server_default=text("'linear'"),
        doc="linear/degressive.",
    )
    method_number: Mapped[int] = mapped_column(
        Integer, server_default=text("60"),
        doc="Number of depreciation entries.",
    )
    method_period: Mapped[str] = mapped_column(
        String(20), server_default=text("'1'"),
        doc="Period between entries in months (1/3/6/12).",
    )
    method_progress_factor: Mapped[float] = mapped_column(
        Float, server_default=text("0.3"),
        doc="Degressive factor.",
    )
    prorata_computation_type: Mapped[str] = mapped_column(
        String(30), server_default=text("'daily_computation'"),
        doc="daily_computation/constant_periods.",
    )

    # ── Accounts ──────────────────────────────────────────────────────
    account_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True,
    )
    account_depreciation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True,
    )
    account_expense_depreciation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True,
    )
    journal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journals.id", ondelete="SET NULL"), nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    def __repr__(self) -> str:
        return f"<AssetGroup name={self.name!r} type={self.asset_type}>"


class Asset(UUIDMixin, TimestampMixin, Base):
    """A fixed asset with depreciation tracking."""

    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_state", "state"),
        Index("ix_assets_asset_type", "asset_type"),
    )

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    asset_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="asset/expense/revenue.",
    )
    state: Mapped[str] = mapped_column(
        String(20), server_default=text("'draft'"),
        doc="draft/open/paused/close/cancelled.",
    )
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    first_depreciation_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ── Values ────────────────────────────────────────────────────────
    original_value: Mapped[float] = mapped_column(Float, nullable=False)
    salvage_value: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    book_value: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Current book value (original - accumulated depreciation).",
    )
    value_residual: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Remaining value to depreciate.",
    )
    already_depreciated_amount_import: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Previously depreciated amount (for imported assets).",
    )
    currency_code: Mapped[str] = mapped_column(String(3), server_default=text("'USD'"))

    # ── Method ────────────────────────────────────────────────────────
    method: Mapped[str] = mapped_column(String(20), server_default=text("'linear'"))
    method_number: Mapped[int] = mapped_column(Integer, server_default=text("60"))
    method_period: Mapped[str] = mapped_column(String(20), server_default=text("'1'"))
    method_progress_factor: Mapped[float] = mapped_column(Float, server_default=text("0.3"))
    prorata_computation_type: Mapped[str] = mapped_column(
        String(30), server_default=text("'daily_computation'"),
    )

    # ── Accounts ──────────────────────────────────────────────────────
    account_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True,
    )
    account_depreciation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True,
    )
    account_expense_depreciation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True,
    )
    journal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("journals.id", ondelete="SET NULL"), nullable=True,
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("asset_groups.id", ondelete="SET NULL"), nullable=True,
    )
    original_move_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("move_lines.id", ondelete="SET NULL"),
        nullable=True, doc="The purchase bill line that created this asset.",
    )

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    depreciation_lines: Mapped[list["AssetDepreciationLine"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin",
        order_by="AssetDepreciationLine.date",
    )

    def __repr__(self) -> str:
        return f"<Asset name={self.name!r} value={self.original_value} state={self.state}>"


class AssetDepreciationLine(UUIDMixin, Base):
    """A scheduled depreciation entry for an asset."""

    __tablename__ = "asset_depreciation_lines"
    __table_args__ = (
        Index("ix_asset_depreciation_lines_asset_id", "asset_id"),
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    depreciation_value: Mapped[float] = mapped_column(Float, nullable=False)
    cumulative_depreciation: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    remaining_value: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    move_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("moves.id", ondelete="SET NULL"),
        nullable=True, doc="Posted depreciation journal entry.",
    )
    state: Mapped[str] = mapped_column(
        String(20), server_default=text("'draft'"),
        doc="draft/posted.",
    )
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    def __repr__(self) -> str:
        return f"<AssetDepreciationLine date={self.date} amount={self.depreciation_value}>"
