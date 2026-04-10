"""Sequence management service for invoice numbering.

Handles:
- Tracking and managing invoice sequence numbers per journal
- Gap detection in sequence numbering
- Sequence integrity validation with warning events
- Resequencing draft moves to close gaps
- Querying sequence state information
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import (
    BusinessRuleError,
    NotFoundError,
)
from src.core.events import event_bus
from src.modules.accounting.models.journal import Journal
from src.modules.accounting.models.move import Move
from src.modules.accounting.repositories.journal_repo import JournalRepository
from src.modules.accounting.repositories.move_repo import MoveRepository

logger = logging.getLogger(__name__)

# Pattern to extract the numeric suffix from a sequence name like "INV/2026/04/0001"
_SEQUENCE_NUMBER_RE = re.compile(r"(\d+)$")


@dataclass
class SequenceGap:
    """Represents a missing sequence number in a journal's numbering."""

    expected_number: int
    expected_name: str
    previous_name: str | None
    next_name: str | None


@dataclass
class SequenceInfo:
    """Current state of a journal's sequence numbering."""

    journal_id: uuid.UUID
    journal_code: str
    prefix: str
    next_number: int
    total_sequenced_moves: int
    gap_count: int
    gaps: list[SequenceGap] = field(default_factory=list)


class SequenceService:
    """Manages invoice sequence numbering with gap detection and warnings."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.move_repo = MoveRepository(db)
        self.journal_repo = JournalRepository(db)

    # ── Public API ─────────────────────────────────────────────────────

    async def get_next_number(self, journal_id: uuid.UUID) -> str:
        """Return the next available sequence name for a journal.

        Reads the journal's current ``sequence_next_number`` and formats it
        using the journal's ``generate_sequence_name`` method.  This does
        **not** increment the counter — that is the responsibility of the
        posting workflow in ``MoveService.post_move``.
        """
        journal = await self._get_journal(journal_id)
        return journal.generate_sequence_name(is_refund=False)

    async def detect_gaps(self, journal_id: uuid.UUID) -> list[SequenceGap]:
        """Detect gaps in the sequence numbering for a journal.

        Examines all posted and cancelled moves (those that have been assigned
        a sequence name) and identifies missing numbers in the series.

        Returns a list of ``SequenceGap`` objects describing each missing
        sequence number.
        """
        journal = await self._get_journal(journal_id)
        sequenced_moves = await self._get_sequenced_moves(journal_id)

        if not sequenced_moves:
            return []

        # Extract (number, name) pairs from assigned sequence names
        numbered = self._extract_numbers(sequenced_moves)
        if not numbered:
            return []

        # Sort by extracted number
        numbered.sort(key=lambda pair: pair[0])

        gaps: list[SequenceGap] = []
        prefix = journal.sequence_prefix or f"{journal.code}/"

        for i in range(len(numbered) - 1):
            current_num, current_name = numbered[i]
            next_num, next_name = numbered[i + 1]

            # Check for gaps between consecutive numbers
            for missing in range(current_num + 1, next_num):
                expected_name = self._format_sequence_name(
                    current_name, missing,
                )
                gaps.append(SequenceGap(
                    expected_number=missing,
                    expected_name=expected_name,
                    previous_name=current_name,
                    next_name=next_name,
                ))

        return gaps

    async def validate_sequence_integrity(self, journal_id: uuid.UUID) -> list[SequenceGap]:
        """Check for sequence gaps and publish a warning event if any exist.

        Returns the list of detected gaps (empty if the sequence is intact).
        Publishes a ``sequence.gap_detected`` event when gaps are found so
        that other modules (notifications, audit log) can react.
        """
        journal = await self._get_journal(journal_id)
        gaps = await self.detect_gaps(journal_id)

        if gaps:
            gap_numbers = [g.expected_number for g in gaps]
            logger.warning(
                "Sequence gaps detected in journal %s (%s): missing numbers %s",
                journal.code,
                journal_id,
                gap_numbers,
            )
            await event_bus.publish("sequence.gap_detected", {
                "journal_id": str(journal_id),
                "journal_code": journal.code,
                "gap_count": len(gaps),
                "missing_numbers": gap_numbers,
                "missing_names": [g.expected_name for g in gaps],
            })

        return gaps

    async def resequence(self, journal_id: uuid.UUID) -> int:
        """Resequence draft moves in a journal to close numbering gaps.

        Only draft moves can be resequenced — posted moves are immutable
        and their sequence names must not change.  This method assigns new
        sequential ``name`` values to all draft moves ordered by their
        accounting date and creation time.

        Returns the number of moves that were resequenced.

        Raises ``BusinessRuleError`` if there are no draft moves to
        resequence.
        """
        journal = await self._get_journal(journal_id)

        # Fetch draft moves ordered by date then creation time
        query = (
            select(Move)
            .where(
                Move.journal_id == journal_id,
                Move.state == "draft",
            )
            .order_by(Move.date.asc(), Move.created_at.asc())
        )
        result = await self.db.execute(query)
        draft_moves = list(result.scalars().all())

        if not draft_moves:
            raise BusinessRuleError(
                f"No draft moves to resequence in journal {journal.code}",
            )

        # Find the highest sequence number among posted/cancelled moves
        # so that draft resequencing starts after existing immutable entries
        sequenced_moves = await self._get_sequenced_moves(journal_id)
        numbered = self._extract_numbers(sequenced_moves)

        if numbered:
            numbered.sort(key=lambda pair: pair[0])
            start_number = numbered[-1][0] + 1
        else:
            start_number = 1

        # Assign new sequential names to draft moves
        resequenced = 0
        prefix = journal.sequence_prefix or f"{journal.code}/"

        for i, move in enumerate(draft_moves):
            new_number = start_number + i
            # Build the name using the same format as the journal's
            # generate_sequence_name, but with the corrected number
            from datetime import datetime

            move_date = move.date or datetime.utcnow().date()
            year = move_date.strftime("%Y")
            month = move_date.strftime("%m")
            new_name = f"{prefix}{year}/{month}/{new_number:04d}"

            if move.name != new_name:
                move.name = new_name
                resequenced += 1

        await self.db.flush()

        if resequenced > 0:
            logger.info(
                "Resequenced %d draft moves in journal %s (%s)",
                resequenced,
                journal.code,
                journal_id,
            )
            await event_bus.publish("sequence.resequenced", {
                "journal_id": str(journal_id),
                "journal_code": journal.code,
                "moves_resequenced": resequenced,
            })

        return resequenced

    async def get_sequence_info(self, journal_id: uuid.UUID) -> SequenceInfo:
        """Return the current sequence state for a journal.

        Includes the prefix, next number, total count of sequenced moves,
        number of gaps, and the gap details.
        """
        journal = await self._get_journal(journal_id)
        gaps = await self.detect_gaps(journal_id)

        # Count moves that have been assigned a sequence (not draft "/")
        total_count = await self._count_sequenced_moves(journal_id)
        prefix = journal.sequence_prefix or f"{journal.code}/"

        return SequenceInfo(
            journal_id=journal_id,
            journal_code=journal.code,
            prefix=prefix,
            next_number=journal.sequence_next_number,
            total_sequenced_moves=total_count,
            gap_count=len(gaps),
            gaps=gaps,
        )

    # ── Private helpers ────────────────────────────────────────────────

    async def _get_journal(self, journal_id: uuid.UUID) -> Journal:
        """Fetch a journal by ID or raise ``NotFoundError``."""
        journal = await self.journal_repo.get_by_id(journal_id)
        if journal is None:
            raise NotFoundError("Journal", str(journal_id))
        return journal

    async def _get_sequenced_moves(self, journal_id: uuid.UUID) -> list[Move]:
        """Return all moves in a journal that have an assigned sequence name.

        Moves in draft state still have the default ``/`` name, so they are
        excluded.  Only posted and cancelled moves carry real sequence names.
        """
        query = (
            select(Move)
            .where(
                Move.journal_id == journal_id,
                Move.name != "/",
                Move.state.in_(["posted", "cancel"]),
            )
            .order_by(Move.name.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def _count_sequenced_moves(self, journal_id: uuid.UUID) -> int:
        """Count moves with assigned sequence names in a journal."""
        query = (
            select(func.count())
            .select_from(Move)
            .where(
                Move.journal_id == journal_id,
                Move.name != "/",
                Move.state.in_(["posted", "cancel"]),
            )
        )
        result = await self.db.execute(query)
        return result.scalar() or 0

    @staticmethod
    def _extract_numbers(moves: list[Move]) -> list[tuple[int, str]]:
        """Extract the trailing numeric portion from each move's name.

        Returns a list of ``(number, name)`` tuples for moves whose names
        end with a numeric segment.  Moves with unparseable names are
        silently skipped.
        """
        pairs: list[tuple[int, str]] = []
        for move in moves:
            match = _SEQUENCE_NUMBER_RE.search(move.name)
            if match:
                pairs.append((int(match.group(1)), move.name))
        return pairs

    @staticmethod
    def _format_sequence_name(reference_name: str, number: int) -> str:
        """Replace the trailing number in a reference sequence name.

        Given a name like ``INV/2026/04/0003`` and number ``2``, produces
        ``INV/2026/04/0002``, preserving the zero-padding width from the
        reference name.
        """
        match = _SEQUENCE_NUMBER_RE.search(reference_name)
        if not match:
            return reference_name

        original_digits = match.group(1)
        width = len(original_digits)
        prefix_part = reference_name[: match.start()]
        return f"{prefix_part}{number:0{width}d}"
