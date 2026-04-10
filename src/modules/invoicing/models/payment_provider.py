"""Online payment provider configuration and payment link models."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class PaymentProvider(UUIDMixin, TimestampMixin, Base):
    """Configuration for an online payment provider (Stripe, PayPal, etc.).

    Each provider holds API credentials, supported currencies, and links
    to the journals used for recording incoming payments and fees.
    """

    __tablename__ = "payment_providers"

    # ── Identification ────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        doc="Human-readable provider name.",
    )
    provider_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        doc="stripe/paypal/adyen/authorize/mollie/manual.",
    )
    state: Mapped[str] = mapped_column(
        String(20), server_default=text("'disabled'"),
        doc="disabled/test/enabled.",
    )

    # ── Ownership ─────────────────────────────────────────────────────
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )

    # ── Credentials ───────────────────────────────────────────────────
    api_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    secret_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(500), nullable=True)
    publishable_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    merchant_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # ── Environment ───────────────────────────────────────────────────
    environment: Mapped[str] = mapped_column(
        String(10), server_default=text("'test'"),
        doc="test/production.",
    )

    # ── Currency support ──────────────────────────────────────────────
    supported_currencies: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(3)), nullable=True,
        doc="ISO 4217 currency codes accepted by this provider.",
    )

    # ── Journal links ─────────────────────────────────────────────────
    payment_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
        doc="Journal for recording incoming online payments.",
    )
    fees_journal_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
        doc="Journal for recording provider transaction fees.",
    )

    # ── Flags ─────────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"),
    )

    # ── Provider-specific settings ────────────────────────────────────
    settings: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        doc="Provider-specific configuration (capture mode, etc.).",
    )

    def __repr__(self) -> str:
        return f"<PaymentProvider name={self.name!r} type={self.provider_type} state={self.state}>"


class PaymentLink(UUIDMixin, TimestampMixin, Base):
    """A shareable payment link tied to an invoice.

    Customers use this link to pay an outstanding invoice online.
    Each link is associated with a specific provider and has a unique
    token for URL generation.
    """

    __tablename__ = "payment_links"
    __table_args__ = (
        Index("ix_payment_links_move_id", "move_id"),
        Index("ix_payment_links_token", "token", unique=True),
    )

    # ── Link target ───────────────────────────────────────────────────
    move_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
        doc="The invoice (move) this payment link is for.",
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payment_providers.id"), nullable=False,
    )

    # ── Token & URL ───────────────────────────────────────────────────
    token: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True,
        doc="Unique URL-safe token for the payment link.",
    )
    url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        doc="Full payment URL for the customer.",
    )

    # ── Amount ────────────────────────────────────────────────────────
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)

    # ── Status & lifecycle ────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), server_default=text("'active'"),
        doc="active/paid/expired/cancelled.",
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ── External tracking ─────────────────────────────────────────────
    external_payment_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        doc="Payment ID from the provider (e.g. Stripe PaymentIntent ID).",
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
        doc="Foundrix Payment record created upon successful payment.",
    )

    # ── Extra data ────────────────────────────────────────────────────
    metadata_json: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        doc="Arbitrary metadata (customer info, redirect URLs, etc.).",
    )

    # ── Relationships ─────────────────────────────────────────────────
    provider: Mapped["PaymentProvider"] = relationship(lazy="selectin")

    def __repr__(self) -> str:
        return f"<PaymentLink token={self.token!r} status={self.status} amount={self.amount}>"
