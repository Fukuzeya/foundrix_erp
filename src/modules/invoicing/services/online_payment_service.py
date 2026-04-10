"""Online payment service — payment link generation and provider management.

Handles:
- Creating shareable payment links for invoices
- Processing payment callbacks from external providers
- Managing payment provider configurations
- Expiring stale payment links
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError, ValidationError
from src.core.events import event_bus
from src.modules.accounting.models.move import Move, INVOICE_TYPES
from src.modules.invoicing.models.payment_provider import PaymentLink, PaymentProvider
from src.modules.invoicing.schemas.payment_provider import (
    PaymentLinkCreate,
    PaymentLinkPublic,
    PaymentLinkRead,
    PaymentProviderCreate,
    PaymentProviderRead,
    PaymentProviderUpdate,
    OnlinePaymentResult,
)

logger = logging.getLogger(__name__)

# Base URL placeholder — in production this comes from app settings
_PAYMENT_BASE_URL = "/pay"


class OnlinePaymentService:
    """Manages online payment links and provider configurations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Payment Link Operations ──────────────────────────────────────

    async def create_payment_link(
        self,
        move_id: uuid.UUID,
        provider_id: uuid.UUID | None = None,
        expires_in_days: int = 30,
    ) -> OnlinePaymentResult:
        """Generate a payment link for an invoice.

        Args:
            move_id: The invoice (move) to create a link for.
            provider_id: Specific provider to use. If None, picks the first
                         active provider that supports the invoice currency.
            expires_in_days: Number of days before the link expires.

        Returns:
            OnlinePaymentResult with the generated link details.

        Raises:
            NotFoundError: If the invoice or provider is not found.
            BusinessRuleError: If the invoice is not payable online.
        """
        # Fetch and validate the invoice
        move = await self._get_move_or_raise(move_id)
        self._validate_move_for_payment(move)

        # Resolve provider
        provider = await self._resolve_provider(provider_id, move.currency_code)

        # Generate token and URL
        token = self._generate_token()
        url = self._build_payment_url(token, provider)
        expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

        # Create the link record
        link = PaymentLink(
            move_id=move.id,
            provider_id=provider.id,
            token=token,
            amount=move.amount_residual,
            currency_code=move.currency_code,
            status="active",
            expires_at=expires_at,
            url=url,
        )
        self.db.add(link)
        await self.db.flush()
        await self.db.refresh(link)

        await event_bus.publish("payment_link.created", {
            "link_id": str(link.id),
            "move_id": str(move.id),
            "token": token,
            "amount": move.amount_residual,
            "currency_code": move.currency_code,
            "provider_type": provider.provider_type,
        })

        logger.info(
            "Created payment link %s for invoice %s (amount=%s %s)",
            token, move.name, move.amount_residual, move.currency_code,
        )

        return OnlinePaymentResult(
            success=True,
            payment_link_url=url,
            token=token,
            expires_at=expires_at,
        )

    async def get_payment_link(self, token: str) -> PaymentLinkPublic:
        """Retrieve a payment link by token for the customer-facing page.

        Args:
            token: The unique URL-safe token.

        Returns:
            PaymentLinkPublic with amount, currency, status, and provider type.

        Raises:
            NotFoundError: If no link with this token exists.
        """
        link = await self._get_link_by_token(token)

        # Check expiry
        if (
            link.status == "active"
            and link.expires_at
            and link.expires_at < datetime.utcnow()
        ):
            link.status = "expired"
            await self.db.flush()

        provider_type: str | None = None
        if link.provider:
            provider_type = link.provider.provider_type

        return PaymentLinkPublic(
            token=link.token,
            amount=link.amount,
            currency_code=link.currency_code,
            status=link.status,
            provider_type=provider_type,
        )

    async def process_payment_callback(
        self,
        token: str,
        external_payment_id: str,
        status: str,
    ) -> bool:
        """Process a callback from the payment provider after payment attempt.

        Args:
            token: The payment link token.
            external_payment_id: The provider's payment/transaction ID.
            status: Payment outcome — ``'paid'`` or ``'failed'``.

        Returns:
            True if payment was recorded successfully, False otherwise.

        Raises:
            NotFoundError: If the token is invalid.
            BusinessRuleError: If the link is not in a payable state.
        """
        link = await self._get_link_by_token(token)

        if link.status != "active":
            raise BusinessRuleError(
                f"Payment link is '{link.status}', cannot process payment"
            )

        if status == "paid":
            link.status = "paid"
            link.paid_at = datetime.utcnow()
            link.external_payment_id = external_payment_id
            await self.db.flush()

            await event_bus.publish("payment_link.paid", {
                "link_id": str(link.id),
                "move_id": str(link.move_id),
                "token": link.token,
                "amount": link.amount,
                "currency_code": link.currency_code,
                "external_payment_id": external_payment_id,
            })

            logger.info(
                "Payment link %s marked as paid (external_id=%s)",
                token, external_payment_id,
            )
            return True

        # Non-successful status — log but don't change link state
        logger.warning(
            "Payment callback for link %s returned status '%s'",
            token, status,
        )
        return False

    async def expire_old_links(self) -> int:
        """Mark all active links past their expiration date as expired.

        Returns:
            Number of links expired.
        """
        now = datetime.utcnow()
        stmt = (
            update(PaymentLink)
            .where(
                PaymentLink.status == "active",
                PaymentLink.expires_at.isnot(None),
                PaymentLink.expires_at < now,
            )
            .values(status="expired")
        )
        result = await self.db.execute(stmt)
        count = result.rowcount
        if count:
            logger.info("Expired %d stale payment link(s)", count)
        return count

    async def list_links_for_invoice(
        self, move_id: uuid.UUID,
    ) -> list[PaymentLinkRead]:
        """List all payment links for a given invoice.

        Args:
            move_id: The invoice ID.

        Returns:
            List of PaymentLinkRead ordered by creation date descending.
        """
        stmt = (
            select(PaymentLink)
            .where(PaymentLink.move_id == move_id)
            .order_by(PaymentLink.created_at.desc())
        )
        result = await self.db.execute(stmt)
        links = list(result.scalars().all())
        return [PaymentLinkRead.model_validate(link) for link in links]

    async def cancel_link(self, link_id: uuid.UUID) -> None:
        """Cancel an active payment link.

        Args:
            link_id: The payment link ID.

        Raises:
            NotFoundError: If the link does not exist.
            BusinessRuleError: If the link is already paid or cancelled.
        """
        stmt = select(PaymentLink).where(PaymentLink.id == link_id)
        result = await self.db.execute(stmt)
        link = result.scalar_one_or_none()
        if link is None:
            raise NotFoundError("PaymentLink", str(link_id))

        if link.status == "paid":
            raise BusinessRuleError("Cannot cancel a paid payment link")
        if link.status == "cancelled":
            raise BusinessRuleError("Payment link is already cancelled")

        link.status = "cancelled"
        await self.db.flush()

        logger.info("Cancelled payment link %s (token=%s)", link_id, link.token)

    # ── Provider Management ──────────────────────────────────────────

    async def list_providers(
        self, active_only: bool = True,
    ) -> list[PaymentProviderRead]:
        """List payment providers.

        Args:
            active_only: If True, only return active and enabled providers.

        Returns:
            List of PaymentProviderRead.
        """
        stmt = select(PaymentProvider)
        if active_only:
            stmt = stmt.where(
                PaymentProvider.is_active.is_(True),
                PaymentProvider.state.in_(("test", "enabled")),
            )
        stmt = stmt.order_by(PaymentProvider.name)
        result = await self.db.execute(stmt)
        providers = list(result.scalars().all())
        return [PaymentProviderRead.model_validate(p) for p in providers]

    async def create_provider(
        self, data: PaymentProviderCreate,
    ) -> PaymentProviderRead:
        """Create a new payment provider configuration.

        Args:
            data: Provider details.

        Returns:
            The created provider with masked secrets.
        """
        provider = PaymentProvider(
            name=data.name,
            provider_type=data.provider_type,
            company_id=data.company_id,
            api_key=data.api_key,
            secret_key=data.secret_key,
            webhook_secret=data.webhook_secret,
            publishable_key=data.publishable_key,
            merchant_id=data.merchant_id,
            environment=data.environment,
            supported_currencies=data.supported_currencies,
            payment_journal_id=data.payment_journal_id,
            fees_journal_id=data.fees_journal_id,
            settings=data.settings,
        )
        self.db.add(provider)
        await self.db.flush()
        await self.db.refresh(provider)

        logger.info(
            "Created payment provider '%s' (type=%s)",
            provider.name, provider.provider_type,
        )
        return PaymentProviderRead.model_validate(provider)

    async def update_provider(
        self,
        provider_id: uuid.UUID,
        data: PaymentProviderUpdate,
    ) -> PaymentProviderRead:
        """Update an existing payment provider.

        Args:
            provider_id: The provider to update.
            data: Fields to update (only non-None values are applied).

        Returns:
            The updated provider with masked secrets.

        Raises:
            NotFoundError: If the provider does not exist.
        """
        stmt = select(PaymentProvider).where(PaymentProvider.id == provider_id)
        result = await self.db.execute(stmt)
        provider = result.scalar_one_or_none()
        if provider is None:
            raise NotFoundError("PaymentProvider", str(provider_id))

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                setattr(provider, field, value)

        await self.db.flush()
        await self.db.refresh(provider)

        logger.info("Updated payment provider '%s' (%s)", provider.name, provider_id)
        return PaymentProviderRead.model_validate(provider)

    # ── Private Helpers ──────────────────────────────────────────────

    async def _get_move_or_raise(self, move_id: uuid.UUID) -> Move:
        """Fetch an invoice move or raise NotFoundError."""
        stmt = select(Move).where(Move.id == move_id)
        result = await self.db.execute(stmt)
        move = result.scalar_one_or_none()
        if move is None:
            raise NotFoundError("Invoice", str(move_id))
        return move

    def _validate_move_for_payment(self, move: Move) -> None:
        """Ensure the move is eligible for online payment."""
        if move.move_type not in INVOICE_TYPES:
            raise BusinessRuleError(
                f"Only invoices can have payment links, got move_type='{move.move_type}'"
            )
        if move.state != "posted":
            raise BusinessRuleError(
                "Cannot create payment link for a non-posted invoice"
            )
        if move.payment_state == "paid":
            raise BusinessRuleError("Invoice is already fully paid")
        if move.amount_residual <= 0:
            raise BusinessRuleError("Invoice has no outstanding amount")

    async def _resolve_provider(
        self,
        provider_id: uuid.UUID | None,
        currency_code: str,
    ) -> PaymentProvider:
        """Resolve a provider by ID, or pick the first active one for the currency."""
        if provider_id:
            stmt = select(PaymentProvider).where(PaymentProvider.id == provider_id)
            result = await self.db.execute(stmt)
            provider = result.scalar_one_or_none()
            if provider is None:
                raise NotFoundError("PaymentProvider", str(provider_id))
            if not provider.is_active or provider.state == "disabled":
                raise BusinessRuleError(
                    f"Payment provider '{provider.name}' is not active"
                )
            return provider

        # Auto-select: find first active provider supporting the currency
        stmt = (
            select(PaymentProvider)
            .where(
                PaymentProvider.is_active.is_(True),
                PaymentProvider.state.in_(("test", "enabled")),
            )
            .order_by(PaymentProvider.name)
        )
        result = await self.db.execute(stmt)
        providers = list(result.scalars().all())

        for provider in providers:
            if (
                provider.supported_currencies is None
                or currency_code in provider.supported_currencies
            ):
                return provider

        raise BusinessRuleError(
            f"No active payment provider found for currency '{currency_code}'"
        )

    def _generate_token(self) -> str:
        """Generate a cryptographically secure URL-safe token."""
        return secrets.token_urlsafe(32)

    def _build_payment_url(self, token: str, provider: PaymentProvider) -> str:
        """Build the customer-facing payment URL.

        In production, the base URL would come from application settings.
        """
        return f"{_PAYMENT_BASE_URL}/{token}"
