"""Currency service — exchange rate management, conversion, gain/loss computation."""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, ConflictError, NotFoundError
from src.core.currency.models import Currency, CurrencyRate
from src.core.currency.schemas import (
    CurrencyCreate,
    CurrencyUpdate,
    CurrencyRateCreate,
    CurrencyRateUpdate,
    CurrencyConvertRequest,
    CurrencyConvertResponse,
)

logger = logging.getLogger(__name__)


class CurrencyService:
    """Manages currencies, exchange rates, and multi-currency conversion."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Currency CRUD ─────────────────────────────────────────────────

    async def list_currencies(self, active_only: bool = True) -> list[Currency]:
        """List all currencies."""
        query = select(Currency).order_by(Currency.code)
        if active_only:
            query = query.where(Currency.is_active.is_(True))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_currency(self, currency_id: uuid.UUID) -> Currency:
        """Get a currency by ID."""
        result = await self.db.execute(select(Currency).where(Currency.id == currency_id))
        currency = result.scalar_one_or_none()
        if not currency:
            raise NotFoundError("Currency", str(currency_id))
        return currency

    async def get_by_code(self, code: str) -> Currency | None:
        """Get a currency by ISO code."""
        result = await self.db.execute(select(Currency).where(Currency.code == code.upper()))
        return result.scalar_one_or_none()

    async def create_currency(self, data: CurrencyCreate) -> Currency:
        """Create a currency with unique code enforcement."""
        existing = await self.get_by_code(data.code)
        if existing:
            raise ConflictError(f"Currency '{data.code}' already exists")

        currency = Currency(**data.model_dump())
        currency.code = currency.code.upper()
        self.db.add(currency)
        await self.db.flush()
        await self.db.refresh(currency)
        return currency

    async def update_currency(self, currency_id: uuid.UUID, data: CurrencyUpdate) -> Currency:
        """Update a currency."""
        currency = await self.get_currency(currency_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(currency, key, value)
        await self.db.flush()
        await self.db.refresh(currency)
        return currency

    # ── Exchange Rates ────────────────────────────────────────────────

    async def get_rate(self, currency_code: str, on_date: date | None = None) -> CurrencyRate | None:
        """Get the exchange rate for a currency on a given date (or latest)."""
        target_date = on_date or date.today()
        currency = await self.get_by_code(currency_code)
        if not currency:
            return None

        # Get the rate on or before the target date
        result = await self.db.execute(
            select(CurrencyRate)
            .where(
                CurrencyRate.currency_id == currency.id,
                CurrencyRate.date <= target_date,
            )
            .order_by(CurrencyRate.date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def set_rate(self, data: CurrencyRateCreate) -> CurrencyRate:
        """Set an exchange rate for a currency on a date. Upserts if rate exists for that date."""
        currency = await self.get_currency(data.currency_id)

        # Check if rate already exists for this date
        result = await self.db.execute(
            select(CurrencyRate).where(
                CurrencyRate.currency_id == data.currency_id,
                CurrencyRate.date == data.date,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.rate = data.rate
            existing.inverse_rate = round(1.0 / data.rate, 10) if data.rate != 0 else 0
            await self.db.flush()
            await self.db.refresh(existing)
            return existing

        rate = CurrencyRate(
            currency_id=data.currency_id,
            date=data.date,
            rate=data.rate,
            inverse_rate=round(1.0 / data.rate, 10) if data.rate != 0 else 0,
        )
        self.db.add(rate)
        await self.db.flush()
        await self.db.refresh(rate)
        return rate

    async def update_rate(self, rate_id: uuid.UUID, data: CurrencyRateUpdate) -> CurrencyRate:
        """Update an existing exchange rate."""
        result = await self.db.execute(select(CurrencyRate).where(CurrencyRate.id == rate_id))
        rate = result.scalar_one_or_none()
        if not rate:
            raise NotFoundError("CurrencyRate", str(rate_id))

        rate.rate = data.rate
        rate.inverse_rate = round(1.0 / data.rate, 10) if data.rate != 0 else 0
        await self.db.flush()
        await self.db.refresh(rate)
        return rate

    async def get_rates_for_currency(
        self, currency_id: uuid.UUID, date_from: date | None = None, date_to: date | None = None,
    ) -> list[CurrencyRate]:
        """List exchange rates for a currency within a date range."""
        query = (
            select(CurrencyRate)
            .where(CurrencyRate.currency_id == currency_id)
            .order_by(CurrencyRate.date.desc())
        )
        if date_from:
            query = query.where(CurrencyRate.date >= date_from)
        if date_to:
            query = query.where(CurrencyRate.date <= date_to)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    # ── Conversion ────────────────────────────────────────────────────

    async def convert(self, data: CurrencyConvertRequest) -> CurrencyConvertResponse:
        """Convert an amount between two currencies."""
        target_date = data.date or date.today()

        if data.from_currency.upper() == data.to_currency.upper():
            return CurrencyConvertResponse(
                amount=data.amount,
                from_currency=data.from_currency.upper(),
                to_currency=data.to_currency.upper(),
                converted_amount=data.amount,
                rate=1.0,
                date=target_date,
            )

        from_rate = await self._get_rate_value(data.from_currency, target_date)
        to_rate = await self._get_rate_value(data.to_currency, target_date)

        # Convert: amount in from_currency → company currency → to_currency
        # If from_rate = how many from_currency per 1 company currency
        # Then amount_in_company = amount / from_rate
        # Then amount_in_to = amount_in_company * to_rate
        if from_rate == 0:
            raise BusinessRuleError(f"Exchange rate for {data.from_currency} is zero")

        conversion_rate = to_rate / from_rate
        converted = round(data.amount * conversion_rate, 6)

        return CurrencyConvertResponse(
            amount=data.amount,
            from_currency=data.from_currency.upper(),
            to_currency=data.to_currency.upper(),
            converted_amount=converted,
            rate=round(conversion_rate, 10),
            date=target_date,
        )

    async def compute_exchange_difference(
        self,
        amount: float,
        currency_code: str,
        original_date: date,
        settlement_date: date,
    ) -> float:
        """Compute the exchange gain/loss between two dates for a given amount."""
        original_rate = await self._get_rate_value(currency_code, original_date)
        settlement_rate = await self._get_rate_value(currency_code, settlement_date)

        if original_rate == 0:
            return 0.0

        # Amount in company currency at original date
        original_company = amount / original_rate
        # Amount in company currency at settlement date
        settlement_company = amount / settlement_rate if settlement_rate != 0 else 0

        # Positive = gain, Negative = loss
        return round(settlement_company - original_company, 2)

    async def _get_rate_value(self, currency_code: str, on_date: date) -> float:
        """Get the rate value for a currency, defaulting to 1.0 for company currency."""
        rate = await self.get_rate(currency_code, on_date)
        if rate:
            return rate.rate
        # If no rate found, check if currency exists
        currency = await self.get_by_code(currency_code)
        if not currency:
            raise NotFoundError("Currency", currency_code)
        # No rate defined yet — default to 1.0 (assumed company currency)
        return 1.0
