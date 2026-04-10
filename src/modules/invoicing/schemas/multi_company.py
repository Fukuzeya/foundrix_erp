"""Pydantic schemas for the multi-company invoicing subsystem."""

from __future__ import annotations

import uuid

from datetime import datetime
from pydantic import BaseModel, ConfigDict


# ── InterCompanyRule ──────────────────────────────────────────────────


class InterCompanyRuleCreate(BaseModel):
    """Payload for creating an inter-company rule."""

    name: str
    source_company_id: uuid.UUID
    target_company_id: uuid.UUID
    rule_type: str
    auto_validate: bool = False
    source_journal_id: uuid.UUID | None = None
    target_journal_id: uuid.UUID | None = None
    account_mapping: dict | None = None
    tax_mapping: dict | None = None


class InterCompanyRuleRead(BaseModel):
    """Read representation of an inter-company rule."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source_company_id: uuid.UUID
    target_company_id: uuid.UUID
    rule_type: str
    auto_validate: bool
    source_journal_id: uuid.UUID | None
    target_journal_id: uuid.UUID | None
    account_mapping: dict | None
    tax_mapping: dict | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class InterCompanyRuleUpdate(BaseModel):
    """Payload for updating an inter-company rule (all fields optional)."""

    name: str | None = None
    auto_validate: bool | None = None
    source_journal_id: uuid.UUID | None = None
    target_journal_id: uuid.UUID | None = None
    account_mapping: dict | None = None
    tax_mapping: dict | None = None
    is_active: bool | None = None


# ── InterCompanyTransaction ──────────────────────────────────────────


class InterCompanyTransactionRead(BaseModel):
    """Read representation of an inter-company transaction."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_id: uuid.UUID
    source_move_id: uuid.UUID
    target_move_id: uuid.UUID | None
    source_company_id: uuid.UUID
    target_company_id: uuid.UUID
    transaction_type: str
    amount: float
    currency_code: str
    state: str
    error_message: str | None
    synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ── Result / Summary ─────────────────────────────────────────────────


class InterCompanySyncResult(BaseModel):
    """Result of a single inter-company sync operation."""

    source_move_id: uuid.UUID
    target_move_id: uuid.UUID | None = None
    state: str
    error: str | None = None


class InterCompanySummary(BaseModel):
    """Aggregate statistics for inter-company operations."""

    total_rules: int
    active_rules: int
    pending_transactions: int
    synced_transactions: int
    failed_transactions: int
