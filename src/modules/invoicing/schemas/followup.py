"""Payment follow-up schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class FollowUpLevelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    sequence: int = 10
    delay_days: int = Field(default=15, ge=0)
    action: str = Field(default="email", pattern="^(email|letter|phone|manual)$")
    send_email: bool = True
    send_letter: bool = False
    join_invoices: bool = True
    manual_action: bool = False
    manual_action_note: str | None = None
    email_subject: str | None = None
    email_body: str | None = None
    is_active: bool = True


class FollowUpLevelRead(BaseModel):
    id: uuid.UUID
    name: str
    sequence: int
    delay_days: int
    action: str
    send_email: bool
    send_letter: bool
    join_invoices: bool
    manual_action: bool
    manual_action_note: str | None
    email_subject: str | None
    email_body: str | None
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class FollowUpLevelUpdate(BaseModel):
    name: str | None = None
    sequence: int | None = None
    delay_days: int | None = None
    action: str | None = None
    send_email: bool | None = None
    send_letter: bool | None = None
    join_invoices: bool | None = None
    manual_action: bool | None = None
    manual_action_note: str | None = None
    email_subject: str | None = None
    email_body: str | None = None
    is_active: bool | None = None


class PartnerFollowUpRead(BaseModel):
    id: uuid.UUID
    partner_id: uuid.UUID
    current_level_id: uuid.UUID | None
    next_action_date: date | None
    last_followup_date: date | None
    last_followup_level_id: uuid.UUID | None
    blocked: bool
    note: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class PartnerFollowUpUpdate(BaseModel):
    blocked: bool | None = None
    note: str | None = None
    next_action_date: date | None = None


class FollowUpAction(BaseModel):
    """Result of running follow-up for a partner."""
    partner_id: uuid.UUID
    level_name: str
    action: str
    overdue_amount: float
    overdue_invoice_count: int
    next_action_date: date | None
