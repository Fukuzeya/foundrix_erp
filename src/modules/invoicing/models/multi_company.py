"""Multi-company invoicing models — inter-company rules and transaction tracking."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class InterCompanyRule(UUIDMixin, TimestampMixin, Base):
    """Defines how invoices are mirrored or synchronized between two companies.

    Rule types:
    - invoice_mirror: Automatically create a matching invoice in the target company
    - so_to_po: Convert sales orders to purchase orders across companies
    - auto_bill: Automatically generate vendor bills from customer invoices
    """

    __tablename__ = "inter_company_rules"
    __table_args__ = (
        UniqueConstraint(
            "source_company_id",
            "target_company_id",
            "rule_type",
            name="uq_inter_company_rules_companies_type",
        ),
        Index("ix_inter_company_rules_source", "source_company_id"),
        Index("ix_inter_company_rules_target", "target_company_id"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    target_company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    rule_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="invoice_mirror/so_to_po/auto_bill",
    )
    auto_validate: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"),
    )
    source_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    target_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    account_mapping: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        doc="source_account_id -> target_account_id",
    )
    tax_mapping: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        doc="source_tax_id -> target_tax_id",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"),
    )

    def __repr__(self) -> str:
        return (
            f"<InterCompanyRule name={self.name!r} "
            f"type={self.rule_type} active={self.is_active}>"
        )


class InterCompanyTransaction(UUIDMixin, TimestampMixin, Base):
    """Tracks a single inter-company synchronization event.

    Each transaction links a source move to its mirrored target move and
    records the synchronization state so that failures can be retried.
    """

    __tablename__ = "inter_company_transactions"
    __table_args__ = (
        Index("ix_inter_company_tx_source_move", "source_move_id"),
        Index("ix_inter_company_tx_target_move", "target_move_id"),
        Index("ix_inter_company_tx_state", "state"),
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inter_company_rules.id"), nullable=False,
    )
    source_move_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    target_move_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    source_company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    target_company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    transaction_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency_code: Mapped[str] = mapped_column(
        String(3), server_default=text("'USD'"),
    )
    state: Mapped[str] = mapped_column(
        String(20), server_default=text("'pending'"),
        doc="pending/synced/failed/cancelled",
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────
    rule: Mapped["InterCompanyRule"] = relationship(lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<InterCompanyTransaction type={self.transaction_type} "
            f"state={self.state} amount={self.amount}>"
        )
