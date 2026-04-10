"""Advanced accounting reports — tax audit, general ledger, journal report,
partner ledger, cash flow, consolidation, and executive summary.

Extends the core ``ReportingService`` with richer analytical reports
suitable for auditors, management, and multi-company environments.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import func, select, case, and_, or_, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.accounting.models.account import Account, ACCOUNT_TYPE_GROUPS
from src.modules.accounting.models.journal import Journal
from src.modules.accounting.models.move import Move, MoveLine, OUTBOUND_TYPES, INBOUND_TYPES
from src.modules.accounting.models.tax import Tax

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mapping account types to cash flow activity categories (indirect method)
# ---------------------------------------------------------------------------
_OPERATING_TYPES = {
    "asset_receivable", "asset_current", "asset_prepayments",
    "liability_payable", "liability_current", "liability_credit_card",
    "income", "income_other",
    "expense", "expense_other", "expense_depreciation", "expense_direct_cost",
}
_INVESTING_TYPES = {
    "asset_non_current", "asset_fixed",
}
_FINANCING_TYPES = {
    "liability_non_current", "equity", "equity_unaffected",
}


class AdvancedReportingService:
    """Generates advanced financial reports from posted journal entries."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Tax Audit Report
    # ------------------------------------------------------------------
    async def tax_audit_report(
        self, date_from: date, date_to: date,
    ) -> dict:
        """Detailed tax audit report.

        Returns all taxable transactions grouped by tax rate, with base vs tax
        amounts and a breakdown by sale / purchase direction.
        """
        # Fetch tax lines with their parent move type so we can classify
        # sale vs purchase.
        query = (
            select(
                Tax.id.label("tax_id"),
                Tax.name.label("tax_name"),
                Tax.amount.label("tax_rate"),
                Tax.amount_type.label("tax_amount_type"),
                Tax.type_tax_use.label("tax_use"),
                Move.move_type,
                func.coalesce(func.sum(MoveLine.tax_base_amount), 0).label("base_amount"),
                func.coalesce(func.sum(MoveLine.debit), 0).label("tax_debit"),
                func.coalesce(func.sum(MoveLine.credit), 0).label("tax_credit"),
                func.count(MoveLine.id).label("line_count"),
            )
            .join(Move, MoveLine.move_id == Move.id)
            .join(Tax, MoveLine.tax_line_id == Tax.id)
            .where(
                Move.state == "posted",
                Move.date >= date_from,
                Move.date <= date_to,
                MoveLine.tax_line_id.isnot(None),
            )
            .group_by(
                Tax.id, Tax.name, Tax.amount, Tax.amount_type,
                Tax.type_tax_use, Move.move_type,
            )
            .order_by(Tax.name, Move.move_type)
        )

        result = await self.db.execute(query)
        rows = result.all()

        # Organise into a nested structure keyed by tax
        tax_groups: dict[str, dict] = {}
        for r in rows:
            tid = str(r.tax_id)
            if tid not in tax_groups:
                tax_groups[tid] = {
                    "tax_id": tid,
                    "tax_name": r.tax_name,
                    "tax_rate": r.tax_rate,
                    "tax_amount_type": r.tax_amount_type,
                    "tax_use": r.tax_use,
                    "sale": {"base_amount": 0.0, "tax_amount": 0.0, "line_count": 0},
                    "purchase": {"base_amount": 0.0, "tax_amount": 0.0, "line_count": 0},
                    "other": {"base_amount": 0.0, "tax_amount": 0.0, "line_count": 0},
                    "total_base": 0.0,
                    "total_tax": 0.0,
                }

            group = tax_groups[tid]
            tax_amount = round(r.tax_debit - r.tax_credit, 2)
            base_amount = round(float(r.base_amount), 2)

            if r.move_type in OUTBOUND_TYPES:
                bucket = "sale"
            elif r.move_type in INBOUND_TYPES:
                bucket = "purchase"
            else:
                bucket = "other"

            group[bucket]["base_amount"] = round(group[bucket]["base_amount"] + base_amount, 2)
            group[bucket]["tax_amount"] = round(group[bucket]["tax_amount"] + tax_amount, 2)
            group[bucket]["line_count"] += r.line_count
            group["total_base"] = round(group["total_base"] + base_amount, 2)
            group["total_tax"] = round(group["total_tax"] + tax_amount, 2)

        grand_total_base = round(sum(g["total_base"] for g in tax_groups.values()), 2)
        grand_total_tax = round(sum(g["total_tax"] for g in tax_groups.values()), 2)

        return {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "tax_groups": list(tax_groups.values()),
            "grand_total_base": grand_total_base,
            "grand_total_tax": grand_total_tax,
        }

    # ------------------------------------------------------------------
    # General Ledger (multi-account, with opening / closing balances)
    # ------------------------------------------------------------------
    async def general_ledger(
        self,
        date_from: date,
        date_to: date,
        account_ids: list[uuid.UUID] | None = None,
    ) -> list[dict]:
        """Full general ledger grouped by account.

        Each account section contains opening balance (all posted entries
        before ``date_from``), individual move lines in the period, and a
        computed closing balance.
        """
        # --- 1. Determine which accounts to include ----
        acct_filter = Account.is_active.is_(True)
        if account_ids:
            acct_filter = and_(acct_filter, Account.id.in_(account_ids))

        accounts_q = (
            select(Account.id, Account.code, Account.name, Account.account_type, Account.internal_group)
            .where(acct_filter)
            .order_by(Account.code)
        )
        acct_rows = (await self.db.execute(accounts_q)).all()

        if not acct_rows:
            return []

        acct_ids = [r[0] for r in acct_rows]
        acct_map = {
            r[0]: {
                "account_id": str(r[0]),
                "account_code": r[1],
                "account_name": r[2],
                "account_type": r[3],
                "internal_group": r[4],
            }
            for r in acct_rows
        }

        # --- 2. Opening balances (all posted entries before date_from) ---
        opening_q = (
            select(
                MoveLine.account_id,
                func.coalesce(func.sum(MoveLine.debit), 0).label("debit"),
                func.coalesce(func.sum(MoveLine.credit), 0).label("credit"),
            )
            .join(Move, MoveLine.move_id == Move.id)
            .where(
                Move.state == "posted",
                Move.date < date_from,
                MoveLine.account_id.in_(acct_ids),
            )
            .group_by(MoveLine.account_id)
        )
        opening_rows = (await self.db.execute(opening_q)).all()
        opening_map: dict[uuid.UUID, tuple[float, float]] = {
            r[0]: (float(r[1]), float(r[2])) for r in opening_rows
        }

        # --- 3. Move lines in the period ---
        lines_q = (
            select(
                MoveLine.account_id,
                MoveLine.id,
                Move.date,
                Move.name.label("move_name"),
                MoveLine.name.label("description"),
                MoveLine.partner_id,
                MoveLine.debit,
                MoveLine.credit,
                MoveLine.balance,
                MoveLine.reconciled,
            )
            .join(Move, MoveLine.move_id == Move.id)
            .where(
                Move.state == "posted",
                Move.date >= date_from,
                Move.date <= date_to,
                MoveLine.account_id.in_(acct_ids),
            )
            .order_by(MoveLine.account_id, Move.date, Move.name)
        )
        lines_rows = (await self.db.execute(lines_q)).all()

        # Group lines by account
        lines_by_acct: dict[uuid.UUID, list] = {aid: [] for aid in acct_ids}
        for r in lines_rows:
            lines_by_acct.setdefault(r[0], []).append(r)

        # --- 4. Build result ---
        result: list[dict] = []
        for aid in acct_ids:
            opening_debit, opening_credit = opening_map.get(aid, (0.0, 0.0))
            opening_balance = round(opening_debit - opening_credit, 2)

            period_lines = []
            running = opening_balance
            period_debit = 0.0
            period_credit = 0.0

            for r in lines_by_acct.get(aid, []):
                running = round(running + float(r.debit) - float(r.credit), 2)
                period_debit += float(r.debit)
                period_credit += float(r.credit)
                period_lines.append({
                    "line_id": str(r[1]),
                    "date": r[2].isoformat(),
                    "move_name": r.move_name,
                    "description": r.description,
                    "partner_id": str(r.partner_id) if r.partner_id else None,
                    "debit": round(float(r.debit), 2),
                    "credit": round(float(r.credit), 2),
                    "balance": round(float(r.balance), 2),
                    "running_balance": running,
                    "reconciled": r.reconciled,
                })

            closing_balance = round(opening_balance + period_debit - period_credit, 2)

            # Skip accounts with no activity and zero opening balance
            if not period_lines and abs(opening_balance) < 0.005:
                continue

            entry = {
                **acct_map[aid],
                "opening_balance": opening_balance,
                "period_debit": round(period_debit, 2),
                "period_credit": round(period_credit, 2),
                "closing_balance": closing_balance,
                "lines": period_lines,
            }
            result.append(entry)

        return result

    # ------------------------------------------------------------------
    # Journal Report
    # ------------------------------------------------------------------
    async def journal_report(
        self,
        date_from: date,
        date_to: date,
        journal_ids: list[uuid.UUID] | None = None,
    ) -> list[dict]:
        """Journal-based report showing all posted entries per journal."""
        # Determine journals
        journal_filter = Journal.is_active.is_(True)
        if journal_ids:
            journal_filter = and_(journal_filter, Journal.id.in_(journal_ids))

        journals_q = (
            select(Journal.id, Journal.code, Journal.name, Journal.journal_type)
            .where(journal_filter)
            .order_by(Journal.code)
        )
        journal_rows = (await self.db.execute(journals_q)).all()
        if not journal_rows:
            return []

        jids = [r[0] for r in journal_rows]
        journal_map = {
            r[0]: {"journal_id": str(r[0]), "journal_code": r[1], "journal_name": r[2], "journal_type": r[3]}
            for r in journal_rows
        }

        # Fetch moves with their lines
        moves_q = (
            select(
                Move.id,
                Move.journal_id,
                Move.name,
                Move.date,
                Move.move_type,
                Move.partner_id,
                Move.amount_total,
                Move.narration,
            )
            .where(
                Move.state == "posted",
                Move.date >= date_from,
                Move.date <= date_to,
                Move.journal_id.in_(jids),
            )
            .order_by(Move.journal_id, Move.date, Move.name)
        )
        move_rows = (await self.db.execute(moves_q)).all()

        move_ids = [r[0] for r in move_rows]
        moves_by_journal: dict[uuid.UUID, list] = {jid: [] for jid in jids}
        move_id_to_journal: dict[uuid.UUID, uuid.UUID] = {}
        for r in move_rows:
            moves_by_journal[r.journal_id].append(r)
            move_id_to_journal[r[0]] = r.journal_id

        # Fetch lines for those moves
        if move_ids:
            ml_q = (
                select(
                    MoveLine.move_id,
                    MoveLine.account_id,
                    Account.code.label("account_code"),
                    Account.name.label("account_name"),
                    MoveLine.name.label("description"),
                    MoveLine.debit,
                    MoveLine.credit,
                    MoveLine.partner_id,
                )
                .join(Account, MoveLine.account_id == Account.id)
                .where(MoveLine.move_id.in_(move_ids))
                .order_by(MoveLine.sequence)
            )
            ml_rows = (await self.db.execute(ml_q)).all()
        else:
            ml_rows = []

        lines_by_move: dict[uuid.UUID, list[dict]] = {}
        for r in ml_rows:
            lines_by_move.setdefault(r.move_id, []).append({
                "account_code": r.account_code,
                "account_name": r.account_name,
                "description": r.description,
                "debit": round(float(r.debit), 2),
                "credit": round(float(r.credit), 2),
                "partner_id": str(r.partner_id) if r.partner_id else None,
            })

        # Assemble
        result: list[dict] = []
        for jid in jids:
            j_moves = moves_by_journal[jid]
            if not j_moves:
                continue

            total_debit = 0.0
            total_credit = 0.0
            entries = []
            for m in j_moves:
                m_lines = lines_by_move.get(m[0], [])
                m_debit = sum(l["debit"] for l in m_lines)
                m_credit = sum(l["credit"] for l in m_lines)
                total_debit += m_debit
                total_credit += m_credit
                entries.append({
                    "move_id": str(m[0]),
                    "move_name": m.name,
                    "date": m.date.isoformat(),
                    "move_type": m.move_type,
                    "partner_id": str(m.partner_id) if m.partner_id else None,
                    "amount_total": round(float(m.amount_total), 2),
                    "narration": m.narration,
                    "lines": m_lines,
                    "debit": round(m_debit, 2),
                    "credit": round(m_credit, 2),
                })

            result.append({
                **journal_map[jid],
                "entry_count": len(entries),
                "total_debit": round(total_debit, 2),
                "total_credit": round(total_credit, 2),
                "entries": entries,
            })

        return result

    # ------------------------------------------------------------------
    # Partner Ledger
    # ------------------------------------------------------------------
    async def partner_ledger(
        self,
        date_from: date,
        date_to: date,
        partner_id: uuid.UUID | None = None,
    ) -> list[dict]:
        """Partner-centric ledger with opening balance, transactions, and
        closing balance per partner.

        Only considers move lines on receivable/payable accounts.
        """
        receivable_payable = {"asset_receivable", "liability_payable"}

        # Base conditions shared across queries
        base_conds = [
            Move.state == "posted",
            Account.account_type.in_(receivable_payable),
            MoveLine.partner_id.isnot(None),
        ]
        if partner_id:
            base_conds.append(MoveLine.partner_id == partner_id)

        # --- 1. Discover partners with activity ---
        partner_q = (
            select(MoveLine.partner_id)
            .join(Move, MoveLine.move_id == Move.id)
            .join(Account, MoveLine.account_id == Account.id)
            .where(*base_conds)
            .group_by(MoveLine.partner_id)
        )
        partner_rows = (await self.db.execute(partner_q)).all()
        p_ids = [r[0] for r in partner_rows]
        if not p_ids:
            return []

        # --- 2. Opening balances ---
        opening_q = (
            select(
                MoveLine.partner_id,
                func.coalesce(func.sum(MoveLine.debit), 0).label("debit"),
                func.coalesce(func.sum(MoveLine.credit), 0).label("credit"),
            )
            .join(Move, MoveLine.move_id == Move.id)
            .join(Account, MoveLine.account_id == Account.id)
            .where(
                *base_conds,
                Move.date < date_from,
            )
            .group_by(MoveLine.partner_id)
        )
        opening_rows = (await self.db.execute(opening_q)).all()
        opening_map = {r[0]: round(float(r[1]) - float(r[2]), 2) for r in opening_rows}

        # --- 3. Period lines ---
        lines_q = (
            select(
                MoveLine.partner_id,
                MoveLine.id,
                Move.date,
                Move.name.label("move_name"),
                Move.move_type,
                MoveLine.name.label("description"),
                Account.code.label("account_code"),
                MoveLine.debit,
                MoveLine.credit,
                MoveLine.amount_residual,
                MoveLine.reconciled,
            )
            .join(Move, MoveLine.move_id == Move.id)
            .join(Account, MoveLine.account_id == Account.id)
            .where(
                *base_conds,
                Move.date >= date_from,
                Move.date <= date_to,
            )
            .order_by(MoveLine.partner_id, Move.date, Move.name)
        )
        lines_rows = (await self.db.execute(lines_q)).all()

        lines_by_partner: dict[uuid.UUID, list] = {pid: [] for pid in p_ids}
        for r in lines_rows:
            lines_by_partner.setdefault(r[0], []).append(r)

        # --- 4. Assemble ---
        result: list[dict] = []
        for pid in p_ids:
            opening = opening_map.get(pid, 0.0)
            running = opening
            period_debit = 0.0
            period_credit = 0.0
            entries = []

            for r in lines_by_partner.get(pid, []):
                d = float(r.debit)
                c = float(r.credit)
                running = round(running + d - c, 2)
                period_debit += d
                period_credit += c
                entries.append({
                    "line_id": str(r[1]),
                    "date": r[2].isoformat(),
                    "move_name": r.move_name,
                    "move_type": r.move_type,
                    "description": r.description,
                    "account_code": r.account_code,
                    "debit": round(d, 2),
                    "credit": round(c, 2),
                    "running_balance": running,
                    "amount_residual": round(float(r.amount_residual), 2),
                    "reconciled": r.reconciled,
                })

            closing = round(opening + period_debit - period_credit, 2)

            if not entries and abs(opening) < 0.005:
                continue

            result.append({
                "partner_id": str(pid),
                "opening_balance": opening,
                "period_debit": round(period_debit, 2),
                "period_credit": round(period_credit, 2),
                "closing_balance": closing,
                "lines": entries,
            })

        # Sort by absolute closing balance descending for relevance
        result.sort(key=lambda p: abs(p["closing_balance"]), reverse=True)
        return result

    # ------------------------------------------------------------------
    # Cash Flow Statement (indirect method)
    # ------------------------------------------------------------------
    async def cash_flow_statement(
        self, date_from: date, date_to: date,
    ) -> dict:
        """Cash flow statement using the indirect method.

        Derives operating / investing / financing activities from account
        type classifications and the change in account balances over the
        period.
        """
        # Net income (income - expense) in the period
        pnl_q = (
            select(
                Account.internal_group,
                func.coalesce(func.sum(MoveLine.debit), 0).label("debit"),
                func.coalesce(func.sum(MoveLine.credit), 0).label("credit"),
            )
            .join(MoveLine, MoveLine.account_id == Account.id)
            .join(Move, MoveLine.move_id == Move.id)
            .where(
                Move.state == "posted",
                Move.date >= date_from,
                Move.date <= date_to,
                Account.internal_group.in_(["income", "expense"]),
            )
            .group_by(Account.internal_group)
        )
        pnl_rows = (await self.db.execute(pnl_q)).all()
        income_total = 0.0
        expense_total = 0.0
        for r in pnl_rows:
            if r[0] == "income":
                income_total = float(r[2]) - float(r[1])  # credit - debit
            elif r[0] == "expense":
                expense_total = float(r[1]) - float(r[2])  # debit - credit
        net_income = round(income_total - expense_total, 2)

        # Balance changes per account type in the period
        changes_q = (
            select(
                Account.account_type,
                Account.internal_group,
                Account.code,
                Account.name,
                func.coalesce(func.sum(MoveLine.debit), 0).label("debit"),
                func.coalesce(func.sum(MoveLine.credit), 0).label("credit"),
            )
            .join(MoveLine, MoveLine.account_id == Account.id)
            .join(Move, MoveLine.move_id == Move.id)
            .where(
                Move.state == "posted",
                Move.date >= date_from,
                Move.date <= date_to,
                # Only balance sheet accounts for working capital changes
                Account.internal_group.in_(["asset", "liability", "equity"]),
            )
            .group_by(Account.account_type, Account.internal_group, Account.code, Account.name)
            .order_by(Account.code)
        )
        changes_rows = (await self.db.execute(changes_q)).all()

        operating_items: list[dict] = []
        investing_items: list[dict] = []
        financing_items: list[dict] = []

        operating_total = 0.0
        investing_total = 0.0
        financing_total = 0.0

        for r in changes_rows:
            acct_type = r[0]
            net_change = float(r[4]) - float(r[5])  # debit - credit

            # Cash accounts are the result, not a source — skip
            if acct_type == "asset_cash":
                continue

            # For assets, an increase in balance (debit) is a cash outflow
            # For liabilities/equity, an increase (credit) is a cash inflow
            if r[1] == "asset":
                cash_effect = round(-net_change, 2)  # asset increase = cash used
            else:
                cash_effect = round(-net_change, 2)  # liability/equity: credit increase = +cash

            item = {
                "account_type": acct_type,
                "account_code": r[2],
                "account_name": r[3],
                "net_change": round(net_change, 2),
                "cash_effect": cash_effect,
            }

            if acct_type in _OPERATING_TYPES:
                operating_items.append(item)
                operating_total += cash_effect
            elif acct_type in _INVESTING_TYPES:
                investing_items.append(item)
                investing_total += cash_effect
            elif acct_type in _FINANCING_TYPES:
                financing_items.append(item)
                financing_total += cash_effect

        # Cash beginning / ending
        cash_beginning_q = (
            select(
                func.coalesce(func.sum(MoveLine.debit), 0).label("debit"),
                func.coalesce(func.sum(MoveLine.credit), 0).label("credit"),
            )
            .join(Move, MoveLine.move_id == Move.id)
            .join(Account, MoveLine.account_id == Account.id)
            .where(
                Move.state == "posted",
                Move.date < date_from,
                Account.account_type == "asset_cash",
            )
        )
        cb_row = (await self.db.execute(cash_beginning_q)).one()
        cash_beginning = round(float(cb_row[0]) - float(cb_row[1]), 2)

        cash_period_q = (
            select(
                func.coalesce(func.sum(MoveLine.debit), 0).label("debit"),
                func.coalesce(func.sum(MoveLine.credit), 0).label("credit"),
            )
            .join(Move, MoveLine.move_id == Move.id)
            .join(Account, MoveLine.account_id == Account.id)
            .where(
                Move.state == "posted",
                Move.date >= date_from,
                Move.date <= date_to,
                Account.account_type == "asset_cash",
            )
        )
        cp_row = (await self.db.execute(cash_period_q)).one()
        net_cash_change = round(float(cp_row[0]) - float(cp_row[1]), 2)
        cash_ending = round(cash_beginning + net_cash_change, 2)

        return {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "net_income": net_income,
            "operating_activities": {
                "net_income": net_income,
                "adjustments": operating_items,
                "total": round(net_income + operating_total, 2),
            },
            "investing_activities": {
                "items": investing_items,
                "total": round(investing_total, 2),
            },
            "financing_activities": {
                "items": financing_items,
                "total": round(financing_total, 2),
            },
            "net_change_in_cash": net_cash_change,
            "cash_beginning": cash_beginning,
            "cash_ending": cash_ending,
        }

    # ------------------------------------------------------------------
    # Consolidation Report (multi-company)
    # ------------------------------------------------------------------
    async def consolidation_report(
        self,
        date_from: date,
        date_to: date,
        company_ids: list[uuid.UUID] | None = None,
    ) -> dict:
        """Multi-company consolidation report.

        Aggregates a trial balance across all (or selected) companies and
        identifies inter-company transactions for elimination.

        Because the current schema does not carry ``company_id`` directly on
        Move/Account, this implementation builds a consolidated trial balance
        from all posted entries in the period and flags inter-company journal
        entries (entries that reference a partner whose id is in
        ``company_ids``) for elimination.
        """
        # --- 1. Consolidated trial balance ---
        tb_q = (
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
            .where(or_(Move.state == "posted", Move.id.is_(None)))
            .where(or_(Move.date >= date_from, Move.id.is_(None)))
            .where(or_(Move.date <= date_to, Move.id.is_(None)))
            .group_by(Account.id, Account.code, Account.name, Account.account_type, Account.internal_group)
            .order_by(Account.code)
        )
        tb_rows = (await self.db.execute(tb_q)).all()

        trial_balance = [
            {
                "account_id": str(r[0]),
                "account_code": r[1],
                "account_name": r[2],
                "account_type": r[3],
                "internal_group": r[4],
                "debit": round(float(r[5]), 2),
                "credit": round(float(r[6]), 2),
                "balance": round(float(r[7]), 2),
            }
            for r in tb_rows
            if abs(r[5]) > 0.001 or abs(r[6]) > 0.001
        ]

        # --- 2. Inter-company eliminations ---
        # If company_ids provided, find move lines where partner_id is one of
        # the company_ids (i.e. transactions between group entities).
        eliminations: list[dict] = []
        elimination_debit = 0.0
        elimination_credit = 0.0

        if company_ids:
            elim_q = (
                select(
                    Account.code.label("account_code"),
                    Account.name.label("account_name"),
                    MoveLine.partner_id,
                    func.coalesce(func.sum(MoveLine.debit), 0).label("debit"),
                    func.coalesce(func.sum(MoveLine.credit), 0).label("credit"),
                )
                .join(Move, MoveLine.move_id == Move.id)
                .join(Account, MoveLine.account_id == Account.id)
                .where(
                    Move.state == "posted",
                    Move.date >= date_from,
                    Move.date <= date_to,
                    MoveLine.partner_id.in_(company_ids),
                )
                .group_by(Account.code, Account.name, MoveLine.partner_id)
                .order_by(Account.code)
            )
            elim_rows = (await self.db.execute(elim_q)).all()

            for r in elim_rows:
                d = round(float(r[3]), 2)
                c = round(float(r[4]), 2)
                elimination_debit += d
                elimination_credit += c
                eliminations.append({
                    "account_code": r[0],
                    "account_name": r[1],
                    "partner_id": str(r[2]),
                    "debit": d,
                    "credit": c,
                    "balance": round(d - c, 2),
                })

        # --- 3. Consolidated totals ---
        total_debit = sum(r["debit"] for r in trial_balance)
        total_credit = sum(r["credit"] for r in trial_balance)

        return {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "company_ids": [str(c) for c in (company_ids or [])],
            "trial_balance": trial_balance,
            "total_debit": round(total_debit, 2),
            "total_credit": round(total_credit, 2),
            "eliminations": eliminations,
            "elimination_debit": round(elimination_debit, 2),
            "elimination_credit": round(elimination_credit, 2),
            "consolidated_debit": round(total_debit - elimination_debit, 2),
            "consolidated_credit": round(total_credit - elimination_credit, 2),
        }

    # ------------------------------------------------------------------
    # Executive Summary / Dashboard
    # ------------------------------------------------------------------
    async def executive_summary(
        self, date_from: date, date_to: date,
    ) -> dict:
        """High-level executive dashboard with key financial metrics and
        year-over-year comparisons.
        """
        # --- Current period aggregates by account type ---
        current = await self._period_aggregates(date_from, date_to)

        # --- Prior year same period ---
        py_from = date_from.replace(year=date_from.year - 1)
        py_to = date_to.replace(year=date_to.year - 1)
        prior = await self._period_aggregates(py_from, py_to)

        # Revenue = income group (credit - debit)
        revenue = current.get("income", 0.0)
        cogs = current.get("expense_direct_cost", 0.0)
        gross_margin = round(revenue - cogs, 2)
        gross_margin_pct = round((gross_margin / revenue * 100) if revenue else 0.0, 2)

        # Operating expenses = total expense minus COGS and depreciation
        total_expense = current.get("_total_expense", 0.0)
        depreciation = current.get("expense_depreciation", 0.0)
        opex = round(total_expense - cogs - depreciation, 2)
        operating_income = round(gross_margin - opex, 2)

        # EBITDA = operating income + depreciation
        ebitda = round(operating_income + depreciation, 2)

        # Net income
        net_income = round(revenue - total_expense, 2)
        net_margin_pct = round((net_income / revenue * 100) if revenue else 0.0, 2)

        # Prior year comparisons
        py_revenue = prior.get("income", 0.0)
        py_net_income = py_revenue - prior.get("_total_expense", 0.0)

        revenue_yoy = round(((revenue - py_revenue) / py_revenue * 100) if py_revenue else 0.0, 2)
        net_income_yoy = round(
            ((net_income - py_net_income) / abs(py_net_income) * 100) if py_net_income else 0.0, 2,
        )

        # --- Balance sheet ratios (as of date_to) ---
        bs = await self._balance_sheet_totals(date_to)

        current_assets = bs.get("asset_current", 0.0) + bs.get("asset_cash", 0.0) + bs.get("asset_receivable", 0.0)
        current_liabilities = (
            bs.get("liability_current", 0.0)
            + bs.get("liability_payable", 0.0)
            + bs.get("liability_credit_card", 0.0)
        )

        current_ratio = round(current_assets / current_liabilities, 2) if current_liabilities else None
        # Quick ratio = (current assets - prepayments) / current liabilities
        quick_assets = current_assets - bs.get("asset_prepayments", 0.0)
        quick_ratio = round(quick_assets / current_liabilities, 2) if current_liabilities else None

        total_assets = bs.get("_total_assets", 0.0)
        total_liabilities = bs.get("_total_liabilities", 0.0)
        total_equity = bs.get("_total_equity", 0.0)

        debt_to_equity = round(total_liabilities / total_equity, 2) if total_equity else None
        roe = round((net_income / total_equity * 100) if total_equity else 0.0, 2)

        return {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "income_statement": {
                "revenue": round(revenue, 2),
                "cost_of_goods_sold": round(cogs, 2),
                "gross_margin": gross_margin,
                "gross_margin_pct": gross_margin_pct,
                "operating_expenses": opex,
                "depreciation": round(depreciation, 2),
                "operating_income": operating_income,
                "ebitda": ebitda,
                "net_income": round(net_income, 2),
                "net_margin_pct": net_margin_pct,
            },
            "yoy_comparison": {
                "prior_period": {"date_from": py_from.isoformat(), "date_to": py_to.isoformat()},
                "prior_revenue": round(py_revenue, 2),
                "prior_net_income": round(py_net_income, 2),
                "revenue_yoy_pct": revenue_yoy,
                "net_income_yoy_pct": net_income_yoy,
            },
            "balance_sheet_snapshot": {
                "as_of": date_to.isoformat(),
                "total_assets": round(total_assets, 2),
                "total_liabilities": round(total_liabilities, 2),
                "total_equity": round(total_equity, 2),
                "current_assets": round(current_assets, 2),
                "current_liabilities": round(current_liabilities, 2),
            },
            "ratios": {
                "current_ratio": current_ratio,
                "quick_ratio": quick_ratio,
                "debt_to_equity": debt_to_equity,
                "return_on_equity_pct": roe,
            },
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    async def _period_aggregates(
        self, date_from: date, date_to: date,
    ) -> dict[str, float]:
        """Return P&L aggregates keyed by account_type for a period.

        Special keys:
        - ``income``: total income (credit - debit for income group)
        - ``_total_expense``: total expenses (debit - credit for expense group)
        - Individual expense account types (e.g. ``expense_direct_cost``)
        """
        query = (
            select(
                Account.account_type,
                Account.internal_group,
                func.coalesce(func.sum(MoveLine.debit), 0).label("debit"),
                func.coalesce(func.sum(MoveLine.credit), 0).label("credit"),
            )
            .join(MoveLine, MoveLine.account_id == Account.id)
            .join(Move, MoveLine.move_id == Move.id)
            .where(
                Move.state == "posted",
                Move.date >= date_from,
                Move.date <= date_to,
                Account.internal_group.in_(["income", "expense"]),
            )
            .group_by(Account.account_type, Account.internal_group)
        )
        rows = (await self.db.execute(query)).all()

        result: dict[str, float] = {"income": 0.0, "_total_expense": 0.0}
        for r in rows:
            acct_type, group, debit, credit = r[0], r[1], float(r[2]), float(r[3])
            if group == "income":
                amount = credit - debit
                result["income"] = round(result["income"] + amount, 2)
                result[acct_type] = round(result.get(acct_type, 0.0) + amount, 2)
            elif group == "expense":
                amount = debit - credit
                result["_total_expense"] = round(result["_total_expense"] + amount, 2)
                result[acct_type] = round(result.get(acct_type, 0.0) + amount, 2)

        return result

    async def _balance_sheet_totals(self, as_of: date) -> dict[str, float]:
        """Return balance sheet totals keyed by account_type as of a date.

        Special keys: ``_total_assets``, ``_total_liabilities``, ``_total_equity``.
        """
        query = (
            select(
                Account.account_type,
                Account.internal_group,
                func.coalesce(func.sum(MoveLine.debit), 0).label("debit"),
                func.coalesce(func.sum(MoveLine.credit), 0).label("credit"),
            )
            .join(MoveLine, MoveLine.account_id == Account.id)
            .join(Move, MoveLine.move_id == Move.id)
            .where(
                Move.state == "posted",
                Move.date <= as_of,
                Account.internal_group.in_(["asset", "liability", "equity"]),
            )
            .group_by(Account.account_type, Account.internal_group)
        )
        rows = (await self.db.execute(query)).all()

        result: dict[str, float] = {
            "_total_assets": 0.0,
            "_total_liabilities": 0.0,
            "_total_equity": 0.0,
        }
        for r in rows:
            acct_type, group, debit, credit = r[0], r[1], float(r[2]), float(r[3])
            if group == "asset":
                balance = debit - credit
                result["_total_assets"] = round(result["_total_assets"] + balance, 2)
            elif group == "liability":
                balance = credit - debit
                result["_total_liabilities"] = round(result["_total_liabilities"] + balance, 2)
            elif group == "equity":
                balance = credit - debit
                result["_total_equity"] = round(result["_total_equity"] + balance, 2)

            result[acct_type] = round(result.get(acct_type, 0.0) + abs(debit - credit), 2)

        return result
