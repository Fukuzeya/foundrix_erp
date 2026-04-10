"""Payment follow-up models — automated reminders for overdue invoices."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Column, String, Integer, Boolean, Date, ForeignKey, Text, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum

from src.core.database.base import Base, UUIDMixin, TimestampMixin


class FollowUpAction(str, enum.Enum):
    EMAIL = "email"
    LETTER = "letter"
    PHONE = "phone"
    MANUAL = "manual"


class FollowUpLevel(Base, UUIDMixin, TimestampMixin):
    """Follow-up level — defines escalation steps for overdue payments.

    Each level specifies how many days after due date to act,
    and what action to take (email, letter, phone call, etc.).
    Levels are ordered by delay_days (ascending).
    """
    __tablename__ = "followup_levels"

    name = Column(String(100), nullable=False)  # e.g., "First Reminder", "Final Warning"
    sequence = Column(Integer, nullable=False, default=10)
    delay_days = Column(Integer, nullable=False, default=15)  # days after due date

    # Actions
    action = Column(SAEnum(FollowUpAction), nullable=False, default=FollowUpAction.EMAIL)
    send_email = Column(Boolean, nullable=False, default=True)
    send_letter = Column(Boolean, nullable=False, default=False)
    join_invoices = Column(Boolean, nullable=False, default=True)  # attach overdue invoices
    manual_action = Column(Boolean, nullable=False, default=False)
    manual_action_note = Column(Text, nullable=True)  # instructions for manual actions

    # Email template
    email_subject = Column(String(500), nullable=True)
    email_body = Column(Text, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<FollowUpLevel {self.name} (+{self.delay_days}d)>"


class PartnerFollowUp(Base, UUIDMixin, TimestampMixin):
    """Tracks the follow-up status for a specific partner.

    Records which follow-up level was last applied, when,
    and when the next action is due.
    """
    __tablename__ = "partner_followups"

    partner_id = Column(UUID(as_uuid=True), nullable=False, unique=True, index=True)

    # Current state
    current_level_id = Column(UUID(as_uuid=True), ForeignKey("followup_levels.id"), nullable=True)
    next_action_date = Column(Date, nullable=True)
    last_followup_date = Column(Date, nullable=True)
    last_followup_level_id = Column(UUID(as_uuid=True), ForeignKey("followup_levels.id"), nullable=True)

    # Manual override
    blocked = Column(Boolean, nullable=False, default=False)  # manually blocked from follow-ups
    note = Column(Text, nullable=True)

    # Relationships
    current_level = relationship("FollowUpLevel", foreign_keys=[current_level_id])
    last_followup_level = relationship("FollowUpLevel", foreign_keys=[last_followup_level_id])

    def __repr__(self) -> str:
        return f"<PartnerFollowUp partner={self.partner_id}>"
