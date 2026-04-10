"""Fiscal year and period lock management.

Implements date-based lock thresholds rather than separate period records.
Supports soft locks (overridable by advisors) and hard locks (irreversible).
"""

import uuid
from datetime import date

from sqlalchemy import (
    Date,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class FiscalYear(UUIDMixin, TimestampMixin, Base):
    """Fiscal year definition with lock date management.

    Lock dates prevent posting entries before a certain date.
    Multiple lock levels provide granular control:
    - sale_lock_date: Locks sales journal entries
    - purchase_lock_date: Locks purchase journal entries
    - tax_lock_date: Locks entries with taxes
    - fiscalyear_lock_date: Locks all entries
    - hard_lock_date: Irreversible lock (audit requirement)
    """

    __tablename__ = "fiscal_years"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)

    # ── Lock dates ────────────────────────────────────────────────────
    sale_lock_date: Mapped[date | None] = mapped_column(
        Date, nullable=True,
        doc="Entries in sales journals locked up to this date.",
    )
    purchase_lock_date: Mapped[date | None] = mapped_column(
        Date, nullable=True,
        doc="Entries in purchase journals locked up to this date.",
    )
    tax_lock_date: Mapped[date | None] = mapped_column(
        Date, nullable=True,
        doc="Tax entries locked up to this date.",
    )
    fiscalyear_lock_date: Mapped[date | None] = mapped_column(
        Date, nullable=True,
        doc="All entries locked up to this date.",
    )
    hard_lock_date: Mapped[date | None] = mapped_column(
        Date, nullable=True,
        doc="Irreversible lock date (cannot be reduced).",
    )

    # ── Fiscal year config ────────────────────────────────────────────
    last_day: Mapped[int] = mapped_column(
        Integer, server_default=text("31"),
        doc="Last day of fiscal year (1-31).",
    )
    last_month: Mapped[int] = mapped_column(
        Integer, server_default=text("12"),
        doc="Last month of fiscal year (1-12).",
    )

    state: Mapped[str] = mapped_column(
        String(20), server_default=text("'open'"),
        doc="open/closed.",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<FiscalYear name={self.name!r} {self.date_from} to {self.date_to}>"
