"""Schemas for online payment providers and payment links."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ── Helpers ──────────────────────────────────────────────────────────────


def _mask_secret(value: str | None) -> str | None:
    """Show only the last 4 characters of a secret, masking the rest."""
    if not value:
        return None
    if len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


# ── Payment Provider ────────────────────────────────────────────────────


class PaymentProviderCreate(BaseModel):
    """Create a new payment provider configuration."""
    name: str = Field(..., min_length=1, max_length=100)
    provider_type: str = Field(..., min_length=1, max_length=20)
    company_id: uuid.UUID | None = None
    api_key: str | None = None
    secret_key: str | None = None
    webhook_secret: str | None = None
    publishable_key: str | None = None
    merchant_id: str | None = None
    environment: str = Field(default="test", max_length=10)
    supported_currencies: list[str] | None = None
    payment_journal_id: uuid.UUID | None = None
    fees_journal_id: uuid.UUID | None = None
    settings: dict | None = None

    @field_validator("provider_type")
    @classmethod
    def validate_provider_type(cls, v: str) -> str:
        allowed = {"stripe", "paypal", "adyen", "authorize", "mollie", "manual"}
        if v not in allowed:
            raise ValueError(f"provider_type must be one of {allowed}")
        return v

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        if v not in ("test", "production"):
            raise ValueError("environment must be 'test' or 'production'")
        return v


class PaymentProviderRead(BaseModel):
    """Read representation of a payment provider with masked secrets."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    provider_type: str
    state: str
    company_id: uuid.UUID | None = None
    api_key: str | None = None
    secret_key: str | None = None
    webhook_secret: str | None = None
    publishable_key: str | None = None
    merchant_id: str | None = None
    environment: str
    supported_currencies: list[str] | None = None
    payment_journal_id: uuid.UUID | None = None
    fees_journal_id: uuid.UUID | None = None
    is_active: bool
    settings: dict | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("api_key", mode="before")
    @classmethod
    def mask_api_key(cls, v: str | None) -> str | None:
        return _mask_secret(v)

    @field_validator("secret_key", mode="before")
    @classmethod
    def mask_secret_key(cls, v: str | None) -> str | None:
        return _mask_secret(v)

    @field_validator("webhook_secret", mode="before")
    @classmethod
    def mask_webhook_secret(cls, v: str | None) -> str | None:
        return _mask_secret(v)


class PaymentProviderUpdate(BaseModel):
    """Update a payment provider — all fields optional."""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    provider_type: str | None = Field(default=None, min_length=1, max_length=20)
    state: str | None = None
    company_id: uuid.UUID | None = None
    api_key: str | None = None
    secret_key: str | None = None
    webhook_secret: str | None = None
    publishable_key: str | None = None
    merchant_id: str | None = None
    environment: str | None = Field(default=None, max_length=10)
    supported_currencies: list[str] | None = None
    payment_journal_id: uuid.UUID | None = None
    fees_journal_id: uuid.UUID | None = None
    is_active: bool | None = None
    settings: dict | None = None

    @field_validator("provider_type")
    @classmethod
    def validate_provider_type(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {"stripe", "paypal", "adyen", "authorize", "mollie", "manual"}
        if v not in allowed:
            raise ValueError(f"provider_type must be one of {allowed}")
        return v

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in ("disabled", "test", "enabled"):
            raise ValueError("state must be 'disabled', 'test', or 'enabled'")
        return v

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in ("test", "production"):
            raise ValueError("environment must be 'test' or 'production'")
        return v


# ── Payment Link ─────────────────────────────────────────────────────────


class PaymentLinkCreate(BaseModel):
    """Request to create a payment link for an invoice."""
    move_id: uuid.UUID
    provider_id: uuid.UUID | None = None
    expires_in_days: int = Field(default=30, ge=1, le=365)


class PaymentLinkRead(BaseModel):
    """Full payment link representation (internal use)."""
    model_config = {"from_attributes": True}

    id: uuid.UUID
    move_id: uuid.UUID
    provider_id: uuid.UUID
    token: str
    amount: float
    currency_code: str
    status: str
    expires_at: datetime | None = None
    paid_at: datetime | None = None
    external_payment_id: str | None = None
    payment_id: uuid.UUID | None = None
    url: str | None = None
    metadata_json: dict | None = None
    created_at: datetime
    updated_at: datetime


class PaymentLinkPublic(BaseModel):
    """Customer-facing payment link — no secrets or internal IDs."""
    model_config = {"from_attributes": True}

    token: str
    amount: float
    currency_code: str
    status: str
    provider_type: str | None = None


class OnlinePaymentResult(BaseModel):
    """Result returned after creating a payment link."""
    success: bool
    payment_link_url: str | None = None
    token: str
    expires_at: datetime | None = None
