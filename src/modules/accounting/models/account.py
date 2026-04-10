"""Chart of Accounts model.

Implements a hierarchical chart of accounts following IFRS/GAAP standards
with 19 account types mapped to 6 internal groups. Supports multi-currency
accounts, reconciliation, and automatic opening balance management.

Account types determine:
- Internal group (asset/liability/equity/income/expense/off)
- Whether the account carries balance forward across fiscal years
- Whether the account must be reconcilable
- Default tax behavior
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    Float,
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


# Account types and their internal groups
ACCOUNT_TYPE_GROUPS = {
    "asset_receivable": "asset",
    "asset_cash": "asset",
    "asset_current": "asset",
    "asset_non_current": "asset",
    "asset_prepayments": "asset",
    "asset_fixed": "asset",
    "liability_payable": "liability",
    "liability_credit_card": "liability",
    "liability_current": "liability",
    "liability_non_current": "liability",
    "equity": "equity",
    "equity_unaffected": "equity",
    "income": "income",
    "income_other": "income",
    "expense": "expense",
    "expense_other": "expense",
    "expense_depreciation": "expense",
    "expense_direct_cost": "expense",
    "off_balance": "off",
}

# Account types that carry forward balances across fiscal years
BALANCE_SHEET_TYPES = {
    "asset_receivable", "asset_cash", "asset_current", "asset_non_current",
    "asset_prepayments", "asset_fixed",
    "liability_payable", "liability_credit_card", "liability_current",
    "liability_non_current",
    "equity",
}

# Account types that MUST be reconcilable
MUST_RECONCILE_TYPES = {"asset_receivable", "liability_payable"}


class AccountTag(UUIDMixin, Base):
    """Tags for accounts and tax reporting."""

    __tablename__ = "account_tags"
    __table_args__ = (
        UniqueConstraint("name", "applicability", name="uq_account_tags_name_applicability"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    applicability: Mapped[str] = mapped_column(
        String(20), server_default=text("'accounts'"),
        doc="One of: accounts, taxes.",
    )
    color: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Account(UUIDMixin, TimestampMixin, Base):
    """A ledger account in the chart of accounts.

    Every financial transaction ultimately posts to accounts. The
    ``account_type`` determines the account's behavior in reporting,
    reconciliation, and fiscal year closing.
    """

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("code", name="uq_accounts_code"),
        Index("ix_accounts_account_type", "account_type"),
        Index("ix_accounts_internal_group", "internal_group"),
        Index("ix_accounts_reconcile", "reconcile"),
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    account_type: Mapped[str] = mapped_column(
        String(30), nullable=False,
        doc="One of the 19 standard account types.",
    )
    internal_group: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="Computed from account_type: asset/liability/equity/income/expense/off.",
    )
    reconcile: Mapped[bool] = mapped_column(
        server_default=text("false"),
        doc="If true, this account supports partial/full reconciliation.",
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    # ── Optional ──────────────────────────────────────────────────────
    currency_code: Mapped[str | None] = mapped_column(
        String(3), nullable=True,
        doc="If set, all entries to this account must use this currency.",
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    non_trade: Mapped[bool] = mapped_column(
        server_default=text("false"),
        doc="Non-trade receivable/payable (e.g. employee advances).",
    )

    # ── Reporting ─────────────────────────────────────────────────────
    include_initial_balance: Mapped[bool] = mapped_column(
        server_default=text("false"),
        doc="Carry forward balance across fiscal years (balance sheet accounts).",
    )

    # ── Relationships ─────────────────────────────────────────────────
    parent: Mapped["Account | None"] = relationship(
        "Account", remote_side="Account.id", foreign_keys=[parent_id],
    )

    @property
    def is_balance_sheet(self) -> bool:
        return self.account_type in BALANCE_SHEET_TYPES

    def __repr__(self) -> str:
        return f"<Account code={self.code!r} name={self.name!r} type={self.account_type}>"
