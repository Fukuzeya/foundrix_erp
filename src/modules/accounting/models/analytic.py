"""Analytic accounting models — cost tracking across dimensions.

Analytic accounts provide a parallel accounting dimension for tracking
costs and revenues by project, department, cost center, etc.
Supports multiple analytic plans with hierarchical accounts.
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


class AnalyticPlan(UUIDMixin, TimestampMixin, Base):
    """A dimension of analytic analysis (e.g. Projects, Departments, Cost Centers)."""

    __tablename__ = "analytic_plans"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("10"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    color: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analytic_plans.id", ondelete="CASCADE"),
        nullable=True,
    )
    complete_name: Mapped[str | None] = mapped_column(String(500), nullable=True)

    accounts: Mapped[list["AnalyticAccount"]] = relationship(
        back_populates="plan", lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<AnalyticPlan name={self.name!r}>"


class AnalyticAccount(UUIDMixin, TimestampMixin, Base):
    """An analytic account for cost/revenue tracking."""

    __tablename__ = "analytic_accounts"
    __table_args__ = (
        Index("ix_analytic_accounts_plan_id", "plan_id"),
        Index("ix_analytic_accounts_code", "code"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analytic_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3), server_default=text("'USD'"))

    # ── Hierarchy ─────────────────────────────────────────────────────
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analytic_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    complete_name: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── Budget ────────────────────────────────────────────────────────
    debit: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    credit: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    balance: Mapped[float] = mapped_column(Float, server_default=text("0.0"))

    plan: Mapped["AnalyticPlan"] = relationship(back_populates="accounts")

    def __repr__(self) -> str:
        return f"<AnalyticAccount name={self.name!r} code={self.code!r}>"


class AnalyticLine(UUIDMixin, TimestampMixin, Base):
    """An analytic journal item — posted alongside regular journal items."""

    __tablename__ = "analytic_lines"
    __table_args__ = (
        Index("ix_analytic_lines_account_id", "account_id"),
        Index("ix_analytic_lines_date", "date"),
    )

    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    date: Mapped[date] = mapped_column(Date, server_default=text("CURRENT_DATE"))
    amount: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    currency_code: Mapped[str] = mapped_column(String(3), server_default=text("'USD'"))

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analytic_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    move_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("move_lines.id", ondelete="SET NULL"),
        nullable=True,
    )
    partner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("partners.id", ondelete="SET NULL"),
        nullable=True,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="SET NULL"),
        nullable=True,
    )
    category: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        doc="invoice/vendor_bill/other.",
    )

    account: Mapped["AnalyticAccount"] = relationship(lazy="selectin")

    def __repr__(self) -> str:
        return f"<AnalyticLine amount={self.amount} account={self.account_id}>"


class Budget(UUIDMixin, TimestampMixin, Base):
    """Budget for tracking planned vs actual performance."""

    __tablename__ = "budgets"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(
        String(20), server_default=text("'draft'"),
        doc="draft/confirmed/validated/done/cancelled.",
    )
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    lines: Mapped[list["BudgetLine"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Budget name={self.name!r} state={self.state}>"


class BudgetLine(UUIDMixin, Base):
    """A budget allocation for an analytic account and/or financial account."""

    __tablename__ = "budget_lines"
    __table_args__ = (
        Index("ix_budget_lines_budget_id", "budget_id"),
    )

    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE"),
        nullable=False,
    )
    analytic_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analytic_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    planned_amount: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    practical_amount: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        doc="Actual amount (computed from analytic lines).",
    )

    def __repr__(self) -> str:
        return f"<BudgetLine planned={self.planned_amount}>"
