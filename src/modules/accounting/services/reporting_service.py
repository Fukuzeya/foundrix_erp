"""Accounting reports service — trial balance, P&L, balance sheet, tax reports.

Generates the core financial statements required by IFRS/GAAP:
- Trial Balance
- Profit & Loss (Income Statement)
- Balance Sheet (Statement of Financial Position)
- General Ledger
- Aged Receivable / Payable
- Tax Report (VAT/GST summary)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.accounting.models.account import Account, ACCOUNT_TYPE_GROUPS
from src.modules.accounting.models.move import Move, MoveLine

logger = logging.getLogger(__name__)


@dataclass
class ReportLine:
    account_id: uuid.UUID | None = None
    account_code: str = ""
    account_name: str = ""
    account_type: str = ""
    internal_group: str = ""
    debit: float = 0.0
    credit: float = 0.0
    balance: float = 0.0


@dataclass
class AgedLine:
    partner_id: uuid.UUID | None = None
    partner_name: str = ""
    current: float = 0.0
    days_1_30: float = 0.0
    days_31_60: float = 0.0
    days_61_90: float = 0.0
    days_over_90: float = 0.0
    total: float = 0.0


class ReportingService:
    """Generates financial reports from posted journal entries."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def trial_balance(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[ReportLine]:
        """Generate trial balance — debit/credit/balance per account."""
        query = (
            select(
                Account.id,
                Account.code,
                Account.name,
                Account.account_type,
                Account.internal_group,
                func.coalesce(func.sum(MoveLine.debit), 0).label("debit"),
                func.coalesce(func.sum(MoveLine.credit), 0).label("credit"),
                func.coalesce(func.sum(MoveLine.balance), 0).label("balance"),
            )
            .outerjoin(MoveLine, MoveLine.account_id == Account.id)
            .outerjoin(Move, MoveLine.move_id == Move.id)
            .where(Account.is_active.is_(True))
        )

        # Only posted entries
        query = query.where(
            (Move.state == "posted") | (Move.id.is_(None))
        )

        if date_from:
            query = query.where((Move.date >= date_from) | (Move.id.is_(None)))
        if date_to:
            query = query.where((Move.date <= date_to) | (Move.id.is_(None)))

        query = query.group_by(
            Account.id, Account.code, Account.name,
            Account.account_type, Account.internal_group,
        ).order_by(Account.code)

        result = await self.db.execute(query)
        return [
            ReportLine(
                account_id=r[0], account_code=r[1], account_name=r[2],
                account_type=r[3], internal_group=r[4],
                debit=r[5], credit=r[6], balance=r[7],
            )
            for r in result.all()
            if abs(r[5]) > 0.001 or abs(r[6]) > 0.001  # Skip zero-balance accounts
        ]

    async def profit_and_loss(
        self, *, date_from: date, date_to: date,
    ) -> dict:
        """Generate Profit & Loss (Income Statement)."""
        tb = await self.trial_balance(date_from=date_from, date_to=date_to)

        income_lines = [l for l in tb if l.internal_group == "income"]
        expense_lines = [l for l in tb if l.internal_group == "expense"]

        total_income = sum(l.credit - l.debit for l in income_lines)
        total_expense = sum(l.debit - l.credit for l in expense_lines)
        net_profit = total_income - total_expense

        return {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "income": [self._line_to_dict(l) for l in income_lines],
            "expenses": [self._line_to_dict(l) for l in expense_lines],
            "total_income": round(total_income, 2),
            "total_expenses": round(total_expense, 2),
            "net_profit": round(net_profit, 2),
        }

    async def balance_sheet(self, *, as_of: date) -> dict:
        """Generate Balance Sheet (Statement of Financial Position)."""
        tb = await self.trial_balance(date_to=as_of)

        assets = [l for l in tb if l.internal_group == "asset"]
        liabilities = [l for l in tb if l.internal_group == "liability"]
        equity = [l for l in tb if l.internal_group == "equity"]

        total_assets = sum(l.debit - l.credit for l in assets)
        total_liabilities = sum(l.credit - l.debit for l in liabilities)
        total_equity = sum(l.credit - l.debit for l in equity)

        return {
            "as_of": as_of.isoformat(),
            "assets": [self._line_to_dict(l) for l in assets],
            "liabilities": [self._line_to_dict(l) for l in liabilities],
            "equity": [self._line_to_dict(l) for l in equity],
            "total_assets": round(total_assets, 2),
            "total_liabilities": round(total_liabilities, 2),
            "total_equity": round(total_equity, 2),
            "check": round(total_assets - total_liabilities - total_equity, 2),
        }

    async def general_ledger(
        self, *, account_id: uuid.UUID, date_from: date | None = None, date_to: date | None = None,
    ) -> list[dict]:
        """Get all journal items for an account (general ledger)."""
        query = (
            select(MoveLine, Move.name.label("move_name"), Move.date.label("move_date"))
            .join(Move, MoveLine.move_id == Move.id)
            .where(
                MoveLine.account_id == account_id,
                Move.state == "posted",
            )
        )
        if date_from:
            query = query.where(Move.date >= date_from)
        if date_to:
            query = query.where(Move.date <= date_to)
        query = query.order_by(Move.date, Move.name)

        result = await self.db.execute(query)
        entries = []
        running_balance = 0.0

        for row in result.all():
            line = row[0]
            running_balance += line.balance
            entries.append({
                "date": row.move_date.isoformat(),
                "move_name": row.move_name,
                "description": line.name,
                "partner_id": str(line.partner_id) if line.partner_id else None,
                "debit": line.debit,
                "credit": line.credit,
                "balance": line.balance,
                "running_balance": round(running_balance, 2),
                "reconciled": line.reconciled,
            })

        return entries

    async def aged_receivable(self, *, as_of: date | None = None) -> list[AgedLine]:
        """Aged receivable report — outstanding customer invoices by age bucket."""
        return await self._aged_report("asset_receivable", as_of or date.today())

    async def aged_payable(self, *, as_of: date | None = None) -> list[AgedLine]:
        """Aged payable report — outstanding vendor bills by age bucket."""
        return await self._aged_report("liability_payable", as_of or date.today())

    async def tax_report(
        self, *, date_from: date, date_to: date,
    ) -> list[dict]:
        """Tax report — summary of taxes collected and paid."""
        from src.modules.accounting.models.tax import Tax

        query = (
            select(
                MoveLine.tax_line_id,
                func.sum(MoveLine.debit).label("debit"),
                func.sum(MoveLine.credit).label("credit"),
                func.sum(MoveLine.balance).label("balance"),
                func.sum(MoveLine.tax_base_amount).label("base_amount"),
            )
            .join(Move, MoveLine.move_id == Move.id)
            .where(
                Move.state == "posted",
                Move.date >= date_from,
                Move.date <= date_to,
                MoveLine.tax_line_id.isnot(None),
            )
            .group_by(MoveLine.tax_line_id)
        )

        result = await self.db.execute(query)
        return [
            {
                "tax_id": str(r[0]),
                "debit": r[1] or 0,
                "credit": r[2] or 0,
                "balance": r[3] or 0,
                "base_amount": r[4] or 0,
            }
            for r in result.all()
        ]

    async def _aged_report(self, account_type: str, as_of: date) -> list[AgedLine]:
        """Generate aged report for receivable or payable accounts."""
        query = (
            select(
                MoveLine.partner_id,
                MoveLine.amount_residual,
                MoveLine.date_maturity,
            )
            .join(Move, MoveLine.move_id == Move.id)
            .join(Account, MoveLine.account_id == Account.id)
            .where(
                Account.account_type == account_type,
                Move.state == "posted",
                MoveLine.reconciled.is_(False),
                MoveLine.amount_residual != 0,
            )
        )

        result = await self.db.execute(query)
        partner_buckets: dict[uuid.UUID | None, AgedLine] = {}

        for row in result.all():
            partner_id = row[0]
            amount = abs(row[1])
            maturity = row[2]

            if partner_id not in partner_buckets:
                partner_buckets[partner_id] = AgedLine(partner_id=partner_id)

            line = partner_buckets[partner_id]

            if maturity is None or maturity >= as_of:
                line.current += amount
            else:
                days_overdue = (as_of - maturity).days
                if days_overdue <= 30:
                    line.days_1_30 += amount
                elif days_overdue <= 60:
                    line.days_31_60 += amount
                elif days_overdue <= 90:
                    line.days_61_90 += amount
                else:
                    line.days_over_90 += amount

            line.total += amount

        return sorted(partner_buckets.values(), key=lambda l: l.total, reverse=True)

    async def account_balances(self) -> list[dict]:
        """Get current balance for all accounts with posted entries."""
        from src.modules.accounting.repositories.move_repo import MoveLineRepository
        repo = MoveLineRepository(self.db)
        return await repo.get_account_balances()

    def _line_to_dict(self, line: ReportLine) -> dict:
        return {
            "account_id": str(line.account_id),
            "account_code": line.account_code,
            "account_name": line.account_name,
            "debit": round(line.debit, 2),
            "credit": round(line.credit, 2),
            "balance": round(line.balance, 2),
        }
