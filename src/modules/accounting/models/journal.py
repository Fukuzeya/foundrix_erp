"""Journal model — groups related accounting entries.

Each journal type has specific behavior:
- sale: Customer invoices and credit notes
- purchase: Vendor bills and refunds
- bank: Bank statement entries and reconciliation
- cash: Cash register transactions
- general: Miscellaneous entries, opening/closing entries
"""

import uuid

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class Journal(UUIDMixin, TimestampMixin, Base):
    """An accounting journal."""

    __tablename__ = "journals"
    __table_args__ = (
        UniqueConstraint("code", name="uq_journals_code"),
        Index("ix_journals_type", "journal_type"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(7), nullable=False)
    journal_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="One of: sale, purchase, bank, cash, general.",
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("10"))

    # ── Default accounts ──────────────────────────────────────────────
    default_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        doc="Default debit/credit account for journal entries.",
    )
    suspense_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        doc="Suspense account for unbalanced bank statement imports.",
    )
    profit_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        doc="Account for exchange rate profit.",
    )
    loss_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        doc="Account for exchange rate loss.",
    )

    # ── Currency ──────────────────────────────────────────────────────
    currency_code: Mapped[str | None] = mapped_column(
        String(3), nullable=True,
        doc="Journal-specific currency (if different from company).",
    )

    # ── Sequence ──────────────────────────────────────────────────────
    sequence_prefix: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        doc="Prefix for entry numbering (e.g. 'INV/', 'BILL/').",
    )
    sequence_next_number: Mapped[int] = mapped_column(
        Integer, server_default=text("1"),
        doc="Next sequence number to assign.",
    )
    use_separate_refund_sequence: Mapped[bool] = mapped_column(
        server_default=text("false"),
        doc="Use a separate numbering for credit notes.",
    )
    refund_sequence_prefix: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
    )
    refund_sequence_next_number: Mapped[int] = mapped_column(
        Integer, server_default=text("1"),
    )

    # ── Security ──────────────────────────────────────────────────────
    restrict_mode_hash_table: Mapped[bool] = mapped_column(
        server_default=text("false"),
        doc="Enable inalterability hash chain for posted entries.",
    )

    # ── Notes ─────────────────────────────────────────────────────────
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────
    default_account: Mapped["Account | None"] = relationship(
        foreign_keys=[default_account_id], lazy="selectin",
    )

    def generate_sequence_name(self, is_refund: bool = False) -> str:
        """Generate the next sequence name for an entry in this journal."""
        from datetime import datetime
        now = datetime.utcnow()
        year = now.strftime("%Y")
        month = now.strftime("%m")

        if is_refund and self.use_separate_refund_sequence:
            prefix = self.refund_sequence_prefix or f"R{self.code}/"
            number = self.refund_sequence_next_number
        else:
            prefix = self.sequence_prefix or f"{self.code}/"
            number = self.sequence_next_number

        return f"{prefix}{year}/{month}/{number:04d}"

    def __repr__(self) -> str:
        return f"<Journal code={self.code!r} type={self.journal_type}>"


# Forward reference
from src.modules.accounting.models.account import Account  # noqa: E402
