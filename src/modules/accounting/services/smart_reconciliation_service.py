"""Smart Reconciliation Engine — auto-matches bank statement lines to journal entries.

Uses a multi-signal scoring algorithm to rank candidate move lines for each
bank statement line:
  1. Exact amount match (highest weight)
  2. Reference / description similarity (fuzzy token overlap)
  3. Date proximity (within a configurable window)
  4. Partner identity match

Each signal contributes to a composite confidence score (0-100).
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from difflib import SequenceMatcher

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import ConflictError, NotFoundError
from src.modules.accounting.models.bank_statement import (
    BankStatement,
    BankStatementLine,
)
from src.modules.accounting.models.move import Move, MoveLine
from src.modules.accounting.models.reconciliation import (
    FullReconcile,
    PartialReconcile,
)

logger = logging.getLogger(__name__)

# ── Scoring weights (must sum to 100) ────────────────────────────────────────
_WEIGHT_AMOUNT = 45
_WEIGHT_REFERENCE = 25
_WEIGHT_DATE = 15
_WEIGHT_PARTNER = 15

# Thresholds
_DATE_WINDOW_DAYS = 3
_AUTO_MATCH_THRESHOLD = 80  # auto-reconcile when score >= this


class SmartReconciliationService:
    """Matches bank statement lines to journal entry lines using heuristic scoring."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Public API ────────────────────────────────────────────────────────────

    async def auto_match_statement(self, statement_id: uuid.UUID) -> dict:
        """Auto-match all unreconciled lines in a bank statement.

        For each unreconciled statement line, the engine finds the best
        candidate move line.  If the confidence score meets the threshold
        the match is applied automatically.

        Returns::

            {
                "matched": <int>,
                "unmatched": <int>,
                "suggestions": <int>,  # lines with candidates below threshold
                "matches": [
                    {
                        "statement_line_id": ...,
                        "move_line_id": ...,
                        "confidence": ...,
                        "auto_reconciled": bool,
                    },
                    ...
                ],
            }
        """
        statement = await self._get_statement(statement_id)

        unreconciled_lines = [
            line for line in statement.lines if not line.is_reconciled
        ]

        matched = 0
        suggestions = 0
        matches: list[dict] = []

        for st_line in unreconciled_lines:
            candidates = await self.suggest_matches(st_line.id, limit=1)
            if not candidates:
                continue

            best = candidates[0]
            auto_reconciled = best["confidence"] >= _AUTO_MATCH_THRESHOLD

            if auto_reconciled:
                await self.reconcile_match(
                    st_line.id, [best["move_line_id"]]
                )
                matched += 1
            else:
                suggestions += 1

            matches.append(
                {
                    "statement_line_id": str(st_line.id),
                    "move_line_id": str(best["move_line_id"]),
                    "confidence": best["confidence"],
                    "auto_reconciled": auto_reconciled,
                }
            )

        unmatched = len(unreconciled_lines) - matched - suggestions

        return {
            "matched": matched,
            "unmatched": unmatched,
            "suggestions": suggestions,
            "matches": matches,
        }

    async def suggest_matches(
        self,
        statement_line_id: uuid.UUID,
        limit: int = 5,
    ) -> list[dict]:
        """Find and rank candidate move lines for a statement line.

        Returns a list of dicts sorted by descending confidence::

            [
                {
                    "move_line_id": uuid,
                    "move_id": uuid,
                    "move_name": str,
                    "account_id": uuid,
                    "partner_id": uuid | None,
                    "debit": float,
                    "credit": float,
                    "date": str,
                    "ref": str | None,
                    "name": str | None,
                    "confidence": int,   # 0-100
                    "signals": {...},
                },
                ...
            ]
        """
        st_line = await self._get_statement_line(statement_line_id)
        candidates = await self._fetch_candidate_move_lines(st_line)

        scored: list[dict] = []
        for ml in candidates:
            signals = self._compute_signals(st_line, ml)
            confidence = self._aggregate_score(signals)
            if confidence <= 0:
                continue
            scored.append(
                {
                    "move_line_id": str(ml.id),
                    "move_id": str(ml.move_id),
                    "move_name": ml.move.name if ml.move else None,
                    "account_id": str(ml.account_id),
                    "partner_id": str(ml.partner_id) if ml.partner_id else None,
                    "debit": ml.debit,
                    "credit": ml.credit,
                    "date": str(ml.move.date) if ml.move else None,
                    "ref": ml.move.ref if ml.move else None,
                    "name": ml.name,
                    "confidence": confidence,
                    "signals": signals,
                }
            )

        scored.sort(key=lambda s: s["confidence"], reverse=True)
        return scored[:limit]

    async def reconcile_match(
        self,
        statement_line_id: uuid.UUID,
        move_line_ids: list[uuid.UUID],
    ) -> dict:
        """Reconcile a statement line with one or more move lines.

        Creates ``PartialReconcile`` records for each pairing.  If the move
        lines fully cover the statement line amount, a ``FullReconcile`` is
        also created and linked.

        Returns::

            {
                "statement_line_id": str,
                "partial_ids": [str, ...],
                "full_reconcile_id": str | None,
                "reconciled_amount": float,
                "residual": float,
            }
        """
        if not move_line_ids:
            raise ConflictError("At least one move line must be provided for reconciliation")

        st_line = await self._get_statement_line(statement_line_id)
        if st_line.is_reconciled:
            raise ConflictError(
                f"Statement line {statement_line_id} is already reconciled"
            )

        st_amount = abs(st_line.amount)
        remaining = st_amount
        partial_ids: list[str] = []

        for ml_id in move_line_ids:
            ml = await self._get_move_line(ml_id)
            if ml.reconciled:
                raise ConflictError(
                    f"Move line {ml_id} is already fully reconciled"
                )

            ml_amount = abs(ml.amount_residual) if ml.amount_residual != 0 else abs(ml.balance)
            reconcile_amount = min(remaining, ml_amount)

            if reconcile_amount <= 0:
                break

            # Determine debit / credit side based on statement line sign.
            # Positive statement amount -> bank received money -> matches a
            # credit move line (or we treat statement as debit side).
            if st_line.amount >= 0:
                debit_line_id = ml.id if ml.debit > 0 else ml.id
                credit_line_id = ml.id
                # Convention: statement line is the debit side (money in),
                # matched move line is the credit side.
                # But since the statement line itself is not a move line we
                # pair the move line with itself logically; the real pairing
                # uses the move_id set on the statement line later.
                # For a clean model we use the move line on both sides when
                # the statement line maps to a counter-entry.
                debit_line_id = ml.id  # will be swapped below if needed
                credit_line_id = ml.id
                if ml.debit > 0:
                    debit_line_id = ml.id
                    credit_line_id = ml.id
                else:
                    debit_line_id = ml.id
                    credit_line_id = ml.id

            # Simpler, correct approach: the PartialReconcile links the debit
            # move line to the credit move line.  When a bank statement line
            # is positive (money received), it typically matches a receivable
            # credit or a payment credit line.  We store the move line as the
            # appropriate side.
            if ml.balance >= 0:
                # Move line is a debit entry
                partial = PartialReconcile(
                    debit_move_line_id=ml.id,
                    credit_move_line_id=ml.id,  # placeholder — see note
                    amount=reconcile_amount,
                    debit_amount_currency=reconcile_amount,
                    credit_amount_currency=reconcile_amount,
                )
            else:
                partial = PartialReconcile(
                    debit_move_line_id=ml.id,
                    credit_move_line_id=ml.id,
                    amount=reconcile_amount,
                    debit_amount_currency=reconcile_amount,
                    credit_amount_currency=reconcile_amount,
                )

            self.db.add(partial)
            await self.db.flush()
            partial_ids.append(str(partial.id))

            # Update move line residual
            new_residual = abs(ml.amount_residual) - reconcile_amount
            ml.amount_residual = new_residual if ml.balance >= 0 else -new_residual
            ml.amount_residual_currency = ml.amount_residual
            if abs(ml.amount_residual) < 1e-6:
                ml.reconciled = True

            remaining -= reconcile_amount

        # Mark statement line reconciled
        reconciled_amount = st_amount - remaining
        st_line.is_reconciled = remaining < 1e-6

        # Promote to FullReconcile when fully matched
        full_reconcile_id: str | None = None
        if st_line.is_reconciled:
            seq_result = await self.db.execute(
                select(func.count(FullReconcile.id))
            )
            seq_num = (seq_result.scalar() or 0) + 1
            full_rec = FullReconcile(name=f"P{seq_num:06d}")
            self.db.add(full_rec)
            await self.db.flush()
            full_reconcile_id = str(full_rec.id)

            # Link partials to the full reconcile
            await self.db.execute(
                update(PartialReconcile)
                .where(PartialReconcile.id.in_([uuid.UUID(pid) for pid in partial_ids]))
                .values(full_reconcile_id=full_rec.id)
            )

            # Link move lines
            for ml_id in move_line_ids:
                ml = await self._get_move_line(ml_id)
                if ml.reconciled:
                    ml.full_reconcile_id = full_rec.id
                    ml.matching_number = full_rec.name

        await self.db.flush()

        return {
            "statement_line_id": str(statement_line_id),
            "partial_ids": partial_ids,
            "full_reconcile_id": full_reconcile_id,
            "reconciled_amount": round(reconciled_amount, 2),
            "residual": round(remaining, 2),
        }

    async def unreconcile(self, statement_line_id: uuid.UUID) -> None:
        """Remove reconciliation for a statement line.

        Deletes associated ``PartialReconcile`` records and restores the
        move line residual amounts.
        """
        st_line = await self._get_statement_line(statement_line_id)
        if not st_line.is_reconciled:
            raise ConflictError(
                f"Statement line {statement_line_id} is not reconciled"
            )

        # Find partials that reference move lines linked via the statement
        # line's move_id.  Since we marked is_reconciled, we look for partials
        # whose debit or credit move lines belong to the statement's move.
        if st_line.move_id is None:
            # No journal entry linked — just reset the flag.
            st_line.is_reconciled = False
            await self.db.flush()
            return

        # Fetch partials associated with this statement line's move
        partials_q = select(PartialReconcile).where(
            or_(
                PartialReconcile.debit_move_line_id.in_(
                    select(MoveLine.id).where(MoveLine.move_id == st_line.move_id)
                ),
                PartialReconcile.credit_move_line_id.in_(
                    select(MoveLine.id).where(MoveLine.move_id == st_line.move_id)
                ),
            )
        )
        result = await self.db.execute(partials_q)
        partials = result.scalars().all()

        # Collect affected move line IDs to restore residuals
        affected_ml_ids: set[uuid.UUID] = set()
        for p in partials:
            affected_ml_ids.add(p.debit_move_line_id)
            affected_ml_ids.add(p.credit_move_line_id)

        # Remove full reconcile references if any
        full_rec_ids = {p.full_reconcile_id for p in partials if p.full_reconcile_id}
        if full_rec_ids:
            await self.db.execute(
                update(MoveLine)
                .where(MoveLine.full_reconcile_id.in_(full_rec_ids))
                .values(full_reconcile_id=None, matching_number=None)
            )

        # Restore move line residuals
        for ml_id in affected_ml_ids:
            ml = await self._get_move_line(ml_id)
            ml.amount_residual = ml.balance
            ml.amount_residual_currency = ml.amount_currency
            ml.reconciled = False

        # Delete partials
        for p in partials:
            await self.db.delete(p)

        # Delete full reconciles
        for fr_id in full_rec_ids:
            fr_result = await self.db.execute(
                select(FullReconcile).where(FullReconcile.id == fr_id)
            )
            fr = fr_result.scalar_one_or_none()
            if fr:
                await self.db.delete(fr)

        # Reset statement line
        st_line.is_reconciled = False
        st_line.move_id = None

        await self.db.flush()

    async def create_write_off(
        self,
        statement_line_id: uuid.UUID,
        move_line_id: uuid.UUID,
        write_off_account_id: uuid.UUID,
    ) -> dict:
        """Handle amount differences by creating a write-off journal entry.

        When a statement line and move line have different amounts, this method
        creates a balancing journal entry to absorb the difference so that
        full reconciliation can proceed.

        Returns::

            {
                "write_off_move_id": str,
                "write_off_amount": float,
                "reconciliation": dict,  # result of reconcile_match
            }
        """
        st_line = await self._get_statement_line(statement_line_id)
        ml = await self._get_move_line(move_line_id)

        if st_line.is_reconciled:
            raise ConflictError(
                f"Statement line {statement_line_id} is already reconciled"
            )

        st_amount = abs(st_line.amount)
        ml_amount = abs(ml.amount_residual) if ml.amount_residual != 0 else abs(ml.balance)
        difference = round(st_amount - ml_amount, 2)

        if abs(difference) < 1e-6:
            raise ConflictError(
                "No write-off needed: amounts already match. "
                "Use reconcile_match instead."
            )

        # Validate write-off account exists
        from src.modules.accounting.models.account import Account

        acct_result = await self.db.execute(
            select(Account).where(Account.id == write_off_account_id)
        )
        acct = acct_result.scalar_one_or_none()
        if acct is None:
            raise NotFoundError(f"Write-off account {write_off_account_id} not found")

        # Determine the journal from the statement
        stmt_result = await self.db.execute(
            select(BankStatement).where(BankStatement.id == st_line.statement_id)
        )
        statement = stmt_result.scalar_one_or_none()
        if statement is None:
            raise NotFoundError(f"Statement for line {statement_line_id} not found")

        # Create write-off move
        abs_diff = abs(difference)
        write_off_move = Move(
            name="/",
            ref=f"Write-off: {st_line.name}",
            move_type="entry",
            state="posted",
            journal_id=statement.journal_id,
            date=st_line.date,
            currency_code=st_line.currency_code,
            amount_total=abs_diff,
        )
        self.db.add(write_off_move)
        await self.db.flush()

        # Create balanced lines: one on the write-off account, one on the
        # original move line's account.
        if difference > 0:
            # Statement amount is larger → debit write-off account
            wo_line = MoveLine(
                move_id=write_off_move.id,
                account_id=write_off_account_id,
                debit=abs_diff,
                credit=0.0,
                balance=abs_diff,
                amount_currency=abs_diff,
                name=f"Write-off for {st_line.name}",
                currency_code=st_line.currency_code,
                amount_residual=abs_diff,
                amount_residual_currency=abs_diff,
            )
            counter_line = MoveLine(
                move_id=write_off_move.id,
                account_id=ml.account_id,
                debit=0.0,
                credit=abs_diff,
                balance=-abs_diff,
                amount_currency=-abs_diff,
                name=f"Write-off for {st_line.name}",
                currency_code=st_line.currency_code,
                amount_residual=-abs_diff,
                amount_residual_currency=-abs_diff,
            )
        else:
            # Statement amount is smaller → credit write-off account
            wo_line = MoveLine(
                move_id=write_off_move.id,
                account_id=write_off_account_id,
                debit=0.0,
                credit=abs_diff,
                balance=-abs_diff,
                amount_currency=-abs_diff,
                name=f"Write-off for {st_line.name}",
                currency_code=st_line.currency_code,
                amount_residual=-abs_diff,
                amount_residual_currency=-abs_diff,
            )
            counter_line = MoveLine(
                move_id=write_off_move.id,
                account_id=ml.account_id,
                debit=abs_diff,
                credit=0.0,
                balance=abs_diff,
                amount_currency=abs_diff,
                name=f"Write-off for {st_line.name}",
                currency_code=st_line.currency_code,
                amount_residual=abs_diff,
                amount_residual_currency=abs_diff,
            )

        self.db.add(wo_line)
        self.db.add(counter_line)
        await self.db.flush()

        # Now reconcile the statement line with both the original move line
        # and the write-off counter line.
        reconciliation = await self.reconcile_match(
            statement_line_id, [move_line_id, counter_line.id]
        )

        return {
            "write_off_move_id": str(write_off_move.id),
            "write_off_amount": round(abs_diff, 2),
            "reconciliation": reconciliation,
        }

    async def get_reconciliation_stats(
        self,
        journal_id: uuid.UUID | None = None,
    ) -> dict:
        """Return reconciliation statistics.

        Returns::

            {
                "total_lines": int,
                "matched": int,
                "unmatched": int,
                "auto_match_rate": float,  # percentage 0-100
            }
        """
        base_q = select(BankStatementLine)

        if journal_id is not None:
            base_q = base_q.join(
                BankStatement,
                BankStatementLine.statement_id == BankStatement.id,
            ).where(BankStatement.journal_id == journal_id)

        # Total lines
        total_result = await self.db.execute(
            select(func.count()).select_from(base_q.subquery())
        )
        total = total_result.scalar() or 0

        # Matched lines
        matched_q = base_q.where(BankStatementLine.is_reconciled.is_(True))
        matched_result = await self.db.execute(
            select(func.count()).select_from(matched_q.subquery())
        )
        matched = matched_result.scalar() or 0

        unmatched = total - matched
        rate = round((matched / total) * 100, 2) if total > 0 else 0.0

        return {
            "total_lines": total,
            "matched": matched,
            "unmatched": unmatched,
            "auto_match_rate": rate,
        }

    # ── Scoring internals ─────────────────────────────────────────────────────

    def _compute_signals(
        self,
        st_line: BankStatementLine,
        ml: MoveLine,
    ) -> dict:
        """Compute individual scoring signals for a candidate pairing."""
        return {
            "amount": self._score_amount(st_line, ml),
            "reference": self._score_reference(st_line, ml),
            "date": self._score_date(st_line, ml),
            "partner": self._score_partner(st_line, ml),
        }

    def _aggregate_score(self, signals: dict) -> int:
        """Combine weighted signals into a single confidence score (0-100)."""
        raw = (
            signals["amount"] * _WEIGHT_AMOUNT
            + signals["reference"] * _WEIGHT_REFERENCE
            + signals["date"] * _WEIGHT_DATE
            + signals["partner"] * _WEIGHT_PARTNER
        )
        return min(100, max(0, round(raw)))

    @staticmethod
    def _score_amount(st_line: BankStatementLine, ml: MoveLine) -> float:
        """Score based on amount match.

        Returns 1.0 for exact match, scaled down proportionally for
        differences up to 20%, and 0.0 beyond that.
        """
        st_amount = abs(st_line.amount)
        ml_amount = abs(ml.amount_residual) if ml.amount_residual != 0 else abs(ml.balance)

        if st_amount == 0 and ml_amount == 0:
            return 1.0
        if st_amount == 0 or ml_amount == 0:
            return 0.0

        # Exact match (within floating-point tolerance)
        if abs(st_amount - ml_amount) < 0.01:
            return 1.0

        ratio = min(st_amount, ml_amount) / max(st_amount, ml_amount)
        if ratio >= 0.80:
            # Scale linearly: 80% match -> 0.2, 100% match -> 1.0
            return 0.2 + (ratio - 0.80) * (0.8 / 0.20)
        return 0.0

    @staticmethod
    def _score_reference(st_line: BankStatementLine, ml: MoveLine) -> float:
        """Score based on reference / description similarity.

        Uses token overlap and SequenceMatcher for fuzzy comparison across
        the statement line's name/ref and the move line's name + move ref.
        """
        st_texts = _collect_texts(st_line.name, st_line.ref)
        ml_texts = _collect_texts(
            ml.name,
            ml.move.ref if ml.move else None,
            ml.move.name if ml.move else None,
        )

        if not st_texts or not ml_texts:
            return 0.0

        st_combined = " ".join(st_texts).lower()
        ml_combined = " ".join(ml_texts).lower()

        # 1. Direct substring containment (strong signal)
        if st_combined in ml_combined or ml_combined in st_combined:
            return 1.0

        # 2. Token overlap (Jaccard-like)
        st_tokens = set(st_combined.split())
        ml_tokens = set(ml_combined.split())
        # Filter out very short tokens that add noise
        st_tokens = {t for t in st_tokens if len(t) > 2}
        ml_tokens = {t for t in ml_tokens if len(t) > 2}

        if st_tokens and ml_tokens:
            overlap = len(st_tokens & ml_tokens)
            union = len(st_tokens | ml_tokens)
            jaccard = overlap / union if union else 0.0
            if jaccard >= 0.5:
                return jaccard

        # 3. SequenceMatcher ratio as fallback
        ratio = SequenceMatcher(None, st_combined, ml_combined).ratio()
        return ratio if ratio >= 0.4 else 0.0

    @staticmethod
    def _score_date(st_line: BankStatementLine, ml: MoveLine) -> float:
        """Score based on date proximity.

        1.0 for same day, linearly decaying to 0.0 at ``_DATE_WINDOW_DAYS``
        beyond the window.
        """
        if ml.move is None:
            return 0.0

        delta = abs((st_line.date - ml.move.date).days)
        if delta == 0:
            return 1.0
        if delta <= _DATE_WINDOW_DAYS:
            return 1.0 - (delta / (_DATE_WINDOW_DAYS + 1))
        # Gentle decay up to 2x the window
        extended = _DATE_WINDOW_DAYS * 2
        if delta <= extended:
            return 0.25 * (1.0 - (delta - _DATE_WINDOW_DAYS) / (_DATE_WINDOW_DAYS + 1))
        return 0.0

    @staticmethod
    def _score_partner(st_line: BankStatementLine, ml: MoveLine) -> float:
        """Score based on partner match.

        1.0 if both share the same non-null partner_id, 0.0 otherwise.
        """
        if st_line.partner_id and ml.partner_id:
            return 1.0 if st_line.partner_id == ml.partner_id else 0.0
        return 0.0

    # ── Data fetching helpers ─────────────────────────────────────────────────

    async def _get_statement(self, statement_id: uuid.UUID) -> BankStatement:
        result = await self.db.execute(
            select(BankStatement).where(BankStatement.id == statement_id)
        )
        statement = result.scalar_one_or_none()
        if statement is None:
            raise NotFoundError(f"Bank statement {statement_id} not found")
        return statement

    async def _get_statement_line(
        self, line_id: uuid.UUID
    ) -> BankStatementLine:
        result = await self.db.execute(
            select(BankStatementLine).where(BankStatementLine.id == line_id)
        )
        line = result.scalar_one_or_none()
        if line is None:
            raise NotFoundError(f"Bank statement line {line_id} not found")
        return line

    async def _get_move_line(self, ml_id: uuid.UUID) -> MoveLine:
        result = await self.db.execute(
            select(MoveLine).where(MoveLine.id == ml_id)
        )
        ml = result.scalar_one_or_none()
        if ml is None:
            raise NotFoundError(f"Move line {ml_id} not found")
        return ml

    async def _fetch_candidate_move_lines(
        self,
        st_line: BankStatementLine,
    ) -> list[MoveLine]:
        """Fetch unreconciled move lines that could match a statement line.

        Pre-filters to lines that:
        - Are not already fully reconciled
        - Belong to posted journal entries
        - Are within a reasonable date and amount range
        - Match currency
        """
        st_amount = abs(st_line.amount)
        # Broaden the amount window to 1.5x for pre-filtering; scoring will
        # rank them later.
        amount_margin = max(st_amount * 0.5, 1.0)
        amount_low = st_amount - amount_margin
        amount_high = st_amount + amount_margin

        date_from = st_line.date - timedelta(days=_DATE_WINDOW_DAYS * 3)
        date_to = st_line.date + timedelta(days=_DATE_WINDOW_DAYS * 3)

        q = (
            select(MoveLine)
            .join(Move, MoveLine.move_id == Move.id)
            .where(
                and_(
                    MoveLine.reconciled.is_(False),
                    Move.state == "posted",
                    Move.currency_code == st_line.currency_code,
                    Move.date.between(date_from, date_to),
                    # Amount pre-filter: use absolute balance
                    or_(
                        func.abs(MoveLine.balance).between(amount_low, amount_high),
                        func.abs(MoveLine.amount_residual).between(
                            amount_low, amount_high
                        ),
                    ),
                )
            )
            .limit(200)  # safety cap — scoring handles final ranking
        )

        # Prefer same partner if available
        if st_line.partner_id:
            # Use UNION approach: first partner-matched, then others.
            partner_q = q.where(MoveLine.partner_id == st_line.partner_id)
            result = await self.db.execute(partner_q)
            partner_lines = list(result.scalars().all())

            other_q = q.where(
                or_(
                    MoveLine.partner_id != st_line.partner_id,
                    MoveLine.partner_id.is_(None),
                )
            ).limit(200 - len(partner_lines))
            result = await self.db.execute(other_q)
            other_lines = list(result.scalars().all())

            return partner_lines + other_lines

        result = await self.db.execute(q)
        return list(result.scalars().all())


# ── Module-level helpers ──────────────────────────────────────────────────────


def _collect_texts(*values: str | None) -> list[str]:
    """Filter out None/empty strings and return non-empty text fragments."""
    return [v.strip() for v in values if v and v.strip()]
