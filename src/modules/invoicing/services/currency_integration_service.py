"""Invoice currency integration service — wires the core currency module into invoicing workflows.

Provides multi-currency operations for invoices: conversion, exchange difference
computation, rate lookups, and currency validation. Delegates rate management to
the core CurrencyService and reads invoice data via MoveRepository.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.currency.models import Currency, CurrencyRate
from src.core.currency.schemas import CurrencyConvertRequest
from src.core.currency.service import CurrencyService
from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.modules.accounting.models.move import Move, MoveLine, INVOICE_TYPES
from src.modules.accounting.repositories.move_repo import MoveRepository

logger = logging.getLogger(__name__)


# ── Response dataclasses ──────────────────────────────────────────────────────


@dataclass
class ConvertedLineAmount:
    """A single invoice line with its amounts converted to the target currency."""

    line_id: uuid.UUID
    name: str | None
    original_currency: str
    target_currency: str
    quantity: float
    price_unit_original: float
    price_unit_converted: float
    price_subtotal_original: float
    price_subtotal_converted: float
    price_total_original: float
    price_total_converted: float
    conversion_rate: float


@dataclass
class ConvertedInvoice:
    """Invoice header amounts converted to a target currency."""

    move_id: uuid.UUID
    invoice_name: str | None
    original_currency: str
    target_currency: str
    conversion_rate: float
    conversion_date: date
    amount_untaxed: float
    amount_tax: float
    amount_total: float
    amount_residual: float
    lines: list[ConvertedLineAmount] = field(default_factory=list)


@dataclass
class ExchangeDifference:
    """Exchange gain/loss between invoice date and payment/settlement date."""

    move_id: uuid.UUID
    invoice_name: str | None
    currency_code: str
    invoice_date: date
    settlement_date: date
    invoice_date_rate: float
    settlement_date_rate: float
    amount_total: float
    amount_company_at_invoice: float
    amount_company_at_settlement: float
    exchange_difference: float  # positive = gain, negative = loss


# ── Service ───────────────────────────────────────────────────────────────────


class InvoiceCurrencyService:
    """Multi-currency operations for the invoicing module.

    Wraps the core CurrencyService and enriches it with invoice-aware
    conversions, exchange-difference computation, and rate lookups.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.currency_svc = CurrencyService(db)
        self.move_repo = MoveRepository(db)

    # ── Public API ─────────────────────────────────────────────────────

    async def convert_invoice_amounts(
        self,
        move_id: uuid.UUID,
        target_currency_code: str,
    ) -> ConvertedInvoice:
        """Convert all line amounts on an invoice to *target_currency_code*
        using the exchange rate applicable on the invoice date (or today).

        Returns a ``ConvertedInvoice`` with both original and converted values.
        """
        move = await self._get_invoice_or_raise(move_id)
        await self.validate_currency(target_currency_code)

        source_code = move.currency_code
        invoice_date = move.invoice_date or move.date
        conversion = await self.currency_svc.convert(
            CurrencyConvertRequest(
                amount=1.0,
                from_currency=source_code,
                to_currency=target_currency_code,
                date=invoice_date,
            )
        )
        rate = conversion.rate

        converted_lines: list[ConvertedLineAmount] = []
        for line in move.lines:
            if line.display_type != "product":
                continue
            converted_lines.append(
                ConvertedLineAmount(
                    line_id=line.id,
                    name=line.name,
                    original_currency=source_code,
                    target_currency=target_currency_code.upper(),
                    quantity=line.quantity,
                    price_unit_original=line.price_unit,
                    price_unit_converted=round(line.price_unit * rate, 6),
                    price_subtotal_original=line.price_subtotal,
                    price_subtotal_converted=round(line.price_subtotal * rate, 6),
                    price_total_original=line.price_total,
                    price_total_converted=round(line.price_total * rate, 6),
                    conversion_rate=rate,
                )
            )

        return ConvertedInvoice(
            move_id=move.id,
            invoice_name=move.name,
            original_currency=source_code,
            target_currency=target_currency_code.upper(),
            conversion_rate=rate,
            conversion_date=invoice_date,
            amount_untaxed=round(move.amount_untaxed * rate, 2),
            amount_tax=round(move.amount_tax * rate, 2),
            amount_total=round(move.amount_total * rate, 2),
            amount_residual=round(move.amount_residual * rate, 2),
            lines=converted_lines,
        )

    async def get_invoice_in_currency(
        self,
        move_id: uuid.UUID,
        currency_code: str,
    ) -> ConvertedInvoice:
        """Convenience wrapper — returns invoice amounts converted to
        *currency_code*.  Identical to ``convert_invoice_amounts`` but with
        a more intention-revealing name for read-only consumption.
        """
        return await self.convert_invoice_amounts(move_id, currency_code)

    async def compute_exchange_difference(
        self,
        move_id: uuid.UUID,
        settlement_date: date | None = None,
    ) -> ExchangeDifference:
        """Compute the exchange gain or loss between the invoice date rate and
        the *settlement_date* rate (defaults to today).

        A positive ``exchange_difference`` indicates a gain; negative indicates
        a loss (from the perspective of the company currency).
        """
        move = await self._get_invoice_or_raise(move_id)
        currency_code = move.currency_code
        inv_date = move.invoice_date or move.date
        settle_date = settlement_date or date.today()

        if inv_date > settle_date:
            raise BusinessRuleError(
                "Settlement date cannot be earlier than the invoice date"
            )

        difference = await self.currency_svc.compute_exchange_difference(
            amount=move.amount_total,
            currency_code=currency_code,
            original_date=inv_date,
            settlement_date=settle_date,
        )

        # Fetch individual rate values for the response
        inv_rate_obj = await self.currency_svc.get_rate(currency_code, inv_date)
        settle_rate_obj = await self.currency_svc.get_rate(currency_code, settle_date)
        inv_rate = inv_rate_obj.rate if inv_rate_obj else 1.0
        settle_rate = settle_rate_obj.rate if settle_rate_obj else 1.0

        amount_company_at_invoice = (
            round(move.amount_total / inv_rate, 2) if inv_rate != 0 else 0.0
        )
        amount_company_at_settlement = (
            round(move.amount_total / settle_rate, 2) if settle_rate != 0 else 0.0
        )

        return ExchangeDifference(
            move_id=move.id,
            invoice_name=move.name,
            currency_code=currency_code,
            invoice_date=inv_date,
            settlement_date=settle_date,
            invoice_date_rate=inv_rate,
            settlement_date_rate=settle_rate,
            amount_total=move.amount_total,
            amount_company_at_invoice=amount_company_at_invoice,
            amount_company_at_settlement=amount_company_at_settlement,
            exchange_difference=difference,
        )

    async def update_currency_rates(self) -> list[Currency]:
        """Trigger a rate refresh by listing active currencies.

        Delegates to the core CurrencyService.  In a production setup this
        would call an external rates provider; for now it returns the set of
        active currencies whose rates can be managed through the core service.
        """
        currencies = await self.currency_svc.list_currencies(active_only=True)
        logger.info("Currency rate refresh requested for %d active currencies", len(currencies))
        return currencies

    async def get_available_currencies(self) -> list[Currency]:
        """Return all active currencies."""
        return await self.currency_svc.list_currencies(active_only=True)

    async def validate_currency(self, currency_code: str) -> Currency:
        """Verify that *currency_code* exists and is active.

        Returns the ``Currency`` instance on success; raises
        ``NotFoundError`` if it does not exist or ``BusinessRuleError`` if
        inactive.
        """
        currency = await self.currency_svc.get_by_code(currency_code)
        if currency is None:
            raise NotFoundError("Currency", currency_code)
        if not currency.is_active:
            raise BusinessRuleError(
                f"Currency '{currency_code}' is inactive and cannot be used for invoicing"
            )
        return currency

    async def get_rate_for_invoice(
        self,
        currency_code: str,
        invoice_date: date | None = None,
    ) -> CurrencyRate:
        """Get the exchange rate applicable for an invoice on *invoice_date*.

        Falls back to the most recent available rate on or before that date.
        Raises ``NotFoundError`` if no rate exists for the currency.
        """
        await self.validate_currency(currency_code)
        target_date = invoice_date or date.today()
        rate = await self.currency_svc.get_rate(currency_code, target_date)
        if rate is None:
            raise NotFoundError(
                "CurrencyRate",
                f"{currency_code} on or before {target_date}",
            )
        return rate

    # ── Private helpers ────────────────────────────────────────────────

    async def _get_invoice_or_raise(self, move_id: uuid.UUID) -> Move:
        """Fetch a move and verify it is an invoice-type document."""
        move = await self.move_repo.get_by_id(move_id)
        if move is None:
            raise NotFoundError("Invoice", str(move_id))
        if move.move_type not in INVOICE_TYPES:
            raise BusinessRuleError(
                f"Move '{move.name}' is of type '{move.move_type}', not an invoice"
            )
        return move
