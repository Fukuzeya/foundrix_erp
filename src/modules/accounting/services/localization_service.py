"""Fiscal Localization Package service.

Manages country-specific accounting setup packages: listing, installing,
and seeding default packages for common jurisdictions. Installation creates
actual Account, Tax, and FiscalPosition records from template data.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import ConflictError, NotFoundError
from src.modules.accounting.models.account import ACCOUNT_TYPE_GROUPS, Account
from src.modules.accounting.models.localization import (
    LocalizationInstallLog,
    LocalizationPackage,
)
from src.modules.accounting.models.payment_term import FiscalPosition
from src.modules.accounting.models.tax import Tax
from src.modules.accounting.schemas.localization import (
    LocalizationInstallRequest,
    LocalizationInstallResult,
    LocalizationInstallLogRead,
    LocalizationPackageRead,
    LocalizationPackageSummary,
)

logger = logging.getLogger(__name__)


class LocalizationService:
    """Service for managing fiscal localization packages."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Public API ────────────────────────────────────────────────────

    async def list_available_packages(self) -> list[LocalizationPackageSummary]:
        """Return summaries of all active localization packages."""
        stmt = (
            select(LocalizationPackage)
            .where(LocalizationPackage.is_active.is_(True))
            .order_by(LocalizationPackage.country_name)
        )
        result = await self.db.execute(stmt)
        packages = result.scalars().all()
        return [LocalizationPackageSummary.model_validate(p) for p in packages]

    async def get_package(self, country_code: str) -> LocalizationPackageRead:
        """Return full details for a localization package by country code."""
        pkg = await self._get_package_by_code(country_code.upper())
        return LocalizationPackageRead.model_validate(pkg)

    async def install_package(
        self, request: LocalizationInstallRequest,
    ) -> LocalizationInstallResult:
        """Install a localization package, creating accounts, taxes, and fiscal positions.

        Each component (chart, taxes, fiscal positions) can be individually
        toggled via the request flags. The installation is logged regardless
        of outcome.
        """
        pkg = await self._get_package_by_code(request.country_code)

        errors: list[str] = []
        accounts_created = 0
        taxes_created = 0
        fps_created = 0

        # Install chart of accounts
        if request.install_chart and pkg.chart_template_data:
            try:
                accounts_created = await self._create_accounts_from_template(
                    pkg.chart_template_data, request.company_id,
                )
            except Exception as exc:
                logger.exception("Failed to install chart of accounts for %s", request.country_code)
                errors.append(f"Chart of accounts: {exc}")

        # Install taxes
        if request.install_taxes and pkg.tax_template_data:
            try:
                taxes_created = await self._create_taxes_from_template(
                    pkg.tax_template_data, request.company_id,
                )
            except Exception as exc:
                logger.exception("Failed to install taxes for %s", request.country_code)
                errors.append(f"Taxes: {exc}")

        # Install fiscal positions
        if request.install_fiscal_positions and pkg.fiscal_position_data:
            try:
                fps_created = await self._create_fiscal_positions_from_template(
                    pkg.fiscal_position_data, request.company_id,
                )
            except Exception as exc:
                logger.exception("Failed to install fiscal positions for %s", request.country_code)
                errors.append(f"Fiscal positions: {exc}")

        # Determine status
        if errors and (accounts_created + taxes_created + fps_created == 0):
            status = "failed"
        elif errors:
            status = "partial"
        else:
            status = "completed"

        # Log the installation
        log = LocalizationInstallLog(
            package_id=pkg.id,
            company_id=request.company_id,
            accounts_created=accounts_created,
            taxes_created=taxes_created,
            fiscal_positions_created=fps_created,
            status=status,
            error_message="; ".join(errors) if errors else None,
        )
        self.db.add(log)
        await self.db.flush()

        return LocalizationInstallResult(
            accounts_created=accounts_created,
            taxes_created=taxes_created,
            fiscal_positions_created=fps_created,
            status=status,
            errors=errors,
        )

    async def get_install_history(
        self, company_id: uuid.UUID | None = None,
    ) -> list[LocalizationInstallLogRead]:
        """Return installation logs, optionally filtered by company."""
        stmt = select(LocalizationInstallLog).order_by(
            LocalizationInstallLog.installed_at.desc(),
        )
        if company_id is not None:
            stmt = stmt.where(LocalizationInstallLog.company_id == company_id)
        result = await self.db.execute(stmt)
        logs = result.scalars().all()
        return [LocalizationInstallLogRead.model_validate(log) for log in logs]

    async def seed_default_packages(self) -> int:
        """Create built-in localization packages for common countries.

        Returns the number of packages created (skips already-existing ones).
        """
        created = 0
        for pkg_data in _DEFAULT_PACKAGES:
            code = pkg_data["country_code"]
            existing = await self.db.execute(
                select(LocalizationPackage).where(
                    LocalizationPackage.country_code == code,
                )
            )
            if existing.scalar_one_or_none() is not None:
                continue

            pkg = LocalizationPackage(**pkg_data)
            self.db.add(pkg)
            created += 1

        if created:
            await self.db.flush()
            logger.info("Seeded %d localization packages", created)

        return created

    # ── Internal helpers ──────────────────────────────────────────────

    async def _get_package_by_code(self, country_code: str) -> LocalizationPackage:
        """Fetch a package by country code or raise NotFoundError."""
        stmt = select(LocalizationPackage).where(
            LocalizationPackage.country_code == country_code,
        )
        result = await self.db.execute(stmt)
        pkg = result.scalar_one_or_none()
        if pkg is None:
            raise NotFoundError("LocalizationPackage", country_code)
        return pkg

    async def _create_accounts_from_template(
        self,
        template_data: dict[str, Any],
        company_id: uuid.UUID | None,
    ) -> int:
        """Create Account records from chart template data.

        Template data structure:
            {"accounts": [{"code": "1000", "name": "Cash", ...}, ...]}
        """
        accounts = template_data.get("accounts", [])
        created = 0
        for entry in accounts:
            account_type = entry.get("account_type", "asset_current")
            internal_group = ACCOUNT_TYPE_GROUPS.get(account_type, "asset")

            # Skip if account code already exists
            existing = await self.db.execute(
                select(Account).where(Account.code == entry["code"])
            )
            if existing.scalar_one_or_none() is not None:
                continue

            account = Account(
                code=entry["code"],
                name=entry["name"],
                account_type=account_type,
                internal_group=internal_group,
                reconcile=entry.get("reconcile", False),
                include_initial_balance=account_type in {
                    "asset_receivable", "asset_cash", "asset_current",
                    "asset_non_current", "asset_prepayments", "asset_fixed",
                    "liability_payable", "liability_credit_card",
                    "liability_current", "liability_non_current", "equity",
                },
            )
            self.db.add(account)
            created += 1

        if created:
            await self.db.flush()
        return created

    async def _create_taxes_from_template(
        self,
        template_data: dict[str, Any],
        company_id: uuid.UUID | None,
    ) -> int:
        """Create Tax records from tax template data.

        Template data structure:
            {"taxes": [{"name": "VAT 20%", "type_tax_use": "sale", ...}, ...]}
        """
        taxes = template_data.get("taxes", [])
        created = 0
        for entry in taxes:
            tax = Tax(
                name=entry["name"],
                type_tax_use=entry.get("type_tax_use", "sale"),
                amount_type=entry.get("amount_type", "percent"),
                amount=entry.get("amount", 0.0),
                description=entry.get("description"),
                sequence=entry.get("sequence", 1),
            )
            self.db.add(tax)
            created += 1

        if created:
            await self.db.flush()
        return created

    async def _create_fiscal_positions_from_template(
        self,
        template_data: dict[str, Any],
        company_id: uuid.UUID | None,
    ) -> int:
        """Create FiscalPosition records from fiscal position template data.

        Template data structure:
            {"fiscal_positions": [{"name": "Intra-EU", ...}, ...]}
        """
        positions = template_data.get("fiscal_positions", [])
        created = 0
        for entry in positions:
            fp = FiscalPosition(
                name=entry["name"],
                auto_apply=entry.get("auto_apply", False),
                country_code=entry.get("country_code"),
                description=entry.get("description"),
                sequence=entry.get("sequence", 10),
            )
            self.db.add(fp)
            created += 1

        if created:
            await self.db.flush()
        return created


# ══════════════════════════════════════════════════════════════════════
# Default localization packages
# ══════════════════════════════════════════════════════════════════════


def _us_chart() -> dict:
    """US GAAP chart of accounts."""
    return {"accounts": [
        # ── Assets ────────────────────────────────────────────────
        {"code": "1000", "name": "Cash", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        {"code": "1010", "name": "Petty Cash", "account_type": "asset_cash", "internal_group": "asset"},
        {"code": "1050", "name": "Short-Term Investments", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1100", "name": "Accounts Receivable", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "1150", "name": "Allowance for Doubtful Accounts", "account_type": "asset_receivable", "internal_group": "asset"},
        {"code": "1200", "name": "Inventory", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1250", "name": "Prepaid Expenses", "account_type": "asset_prepayments", "internal_group": "asset"},
        {"code": "1300", "name": "Prepaid Insurance", "account_type": "asset_prepayments", "internal_group": "asset"},
        {"code": "1500", "name": "Furniture and Fixtures", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1510", "name": "Equipment", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1520", "name": "Vehicles", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1550", "name": "Buildings", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1560", "name": "Land", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1600", "name": "Accumulated Depreciation - Equipment", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1610", "name": "Accumulated Depreciation - Vehicles", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1620", "name": "Accumulated Depreciation - Buildings", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1700", "name": "Intangible Assets", "account_type": "asset_non_current", "internal_group": "asset"},
        # ── Liabilities ───────────────────────────────────────────
        {"code": "2000", "name": "Accounts Payable", "account_type": "liability_payable", "internal_group": "liability", "reconcile": True},
        {"code": "2050", "name": "Credit Card Payable", "account_type": "liability_credit_card", "internal_group": "liability"},
        {"code": "2100", "name": "Accrued Liabilities", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2150", "name": "Wages Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2200", "name": "Sales Tax Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2250", "name": "Income Tax Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2300", "name": "Unearned Revenue", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2500", "name": "Notes Payable (Long-Term)", "account_type": "liability_non_current", "internal_group": "liability"},
        {"code": "2600", "name": "Mortgage Payable", "account_type": "liability_non_current", "internal_group": "liability"},
        # ── Equity ────────────────────────────────────────────────
        {"code": "3000", "name": "Common Stock", "account_type": "equity", "internal_group": "equity"},
        {"code": "3100", "name": "Retained Earnings", "account_type": "equity", "internal_group": "equity"},
        {"code": "3200", "name": "Owner's Equity", "account_type": "equity", "internal_group": "equity"},
        {"code": "3300", "name": "Dividends", "account_type": "equity", "internal_group": "equity"},
        # ── Income ────────────────────────────────────────────────
        {"code": "4000", "name": "Sales Revenue", "account_type": "income", "internal_group": "income"},
        {"code": "4100", "name": "Service Revenue", "account_type": "income", "internal_group": "income"},
        {"code": "4200", "name": "Interest Income", "account_type": "income_other", "internal_group": "income"},
        {"code": "4300", "name": "Other Income", "account_type": "income_other", "internal_group": "income"},
        {"code": "4400", "name": "Gain on Sale of Assets", "account_type": "income_other", "internal_group": "income"},
        # ── Expenses ──────────────────────────────────────────────
        {"code": "5000", "name": "Cost of Goods Sold", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "5100", "name": "Purchases", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "6000", "name": "Salaries Expense", "account_type": "expense", "internal_group": "expense"},
        {"code": "6100", "name": "Rent Expense", "account_type": "expense", "internal_group": "expense"},
        {"code": "6200", "name": "Utilities Expense", "account_type": "expense", "internal_group": "expense"},
        {"code": "6300", "name": "Insurance Expense", "account_type": "expense", "internal_group": "expense"},
        {"code": "6400", "name": "Office Supplies Expense", "account_type": "expense", "internal_group": "expense"},
        {"code": "6500", "name": "Depreciation Expense", "account_type": "expense_depreciation", "internal_group": "expense"},
        {"code": "6600", "name": "Advertising Expense", "account_type": "expense", "internal_group": "expense"},
        {"code": "6700", "name": "Professional Fees", "account_type": "expense", "internal_group": "expense"},
        {"code": "6800", "name": "Travel Expense", "account_type": "expense", "internal_group": "expense"},
        {"code": "6900", "name": "Miscellaneous Expense", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "7000", "name": "Interest Expense", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "7100", "name": "Bank Charges", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "9000", "name": "Income Tax Expense", "account_type": "expense", "internal_group": "expense"},
    ]}


def _us_taxes() -> dict:
    """US sales tax and use tax templates."""
    return {"taxes": [
        {"name": "Sales Tax 0%", "type_tax_use": "sale", "amount_type": "percent", "amount": 0.0, "description": "Exempt sales", "tax_group": "sales_tax"},
        {"name": "Sales Tax 6%", "type_tax_use": "sale", "amount_type": "percent", "amount": 6.0, "description": "State sales tax", "tax_group": "sales_tax"},
        {"name": "Sales Tax 7%", "type_tax_use": "sale", "amount_type": "percent", "amount": 7.0, "description": "State sales tax", "tax_group": "sales_tax"},
        {"name": "Sales Tax 8%", "type_tax_use": "sale", "amount_type": "percent", "amount": 8.0, "description": "Combined state/local sales tax", "tax_group": "sales_tax"},
        {"name": "Sales Tax 8.875%", "type_tax_use": "sale", "amount_type": "percent", "amount": 8.875, "description": "NY combined sales tax", "tax_group": "sales_tax"},
        {"name": "Use Tax 6%", "type_tax_use": "purchase", "amount_type": "percent", "amount": 6.0, "description": "State use tax", "tax_group": "use_tax"},
        {"name": "Use Tax 7%", "type_tax_use": "purchase", "amount_type": "percent", "amount": 7.0, "description": "State use tax", "tax_group": "use_tax"},
        {"name": "Use Tax 8%", "type_tax_use": "purchase", "amount_type": "percent", "amount": 8.0, "description": "Combined state/local use tax", "tax_group": "use_tax"},
    ]}


def _uk_chart() -> dict:
    """UK GAAP chart of accounts."""
    return {"accounts": [
        # ── Assets ────────────────────────────────────────────────
        {"code": "1001", "name": "Bank Current Account", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        {"code": "1002", "name": "Bank Savings Account", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        {"code": "1010", "name": "Petty Cash", "account_type": "asset_cash", "internal_group": "asset"},
        {"code": "1100", "name": "Trade Debtors", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "1101", "name": "Other Debtors", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "1200", "name": "Stock", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1300", "name": "Prepayments", "account_type": "asset_prepayments", "internal_group": "asset"},
        {"code": "1400", "name": "VAT Input (Receivable)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1500", "name": "Plant and Machinery", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1501", "name": "Furniture and Fittings", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1502", "name": "Motor Vehicles", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1503", "name": "Office Equipment", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1504", "name": "Computer Equipment", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1600", "name": "Accumulated Depreciation", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1700", "name": "Goodwill", "account_type": "asset_non_current", "internal_group": "asset"},
        {"code": "1800", "name": "Investments", "account_type": "asset_non_current", "internal_group": "asset"},
        # ── Liabilities ───────────────────────────────────────────
        {"code": "2100", "name": "Trade Creditors", "account_type": "liability_payable", "internal_group": "liability", "reconcile": True},
        {"code": "2101", "name": "Other Creditors", "account_type": "liability_payable", "internal_group": "liability", "reconcile": True},
        {"code": "2200", "name": "VAT Output (Payable)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2201", "name": "PAYE Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2202", "name": "National Insurance Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2210", "name": "Corporation Tax Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2300", "name": "Accruals", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2400", "name": "Deferred Income", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2500", "name": "Bank Loan", "account_type": "liability_non_current", "internal_group": "liability"},
        {"code": "2600", "name": "Directors Loan Account", "account_type": "liability_current", "internal_group": "liability"},
        # ── Equity ────────────────────────────────────────────────
        {"code": "3000", "name": "Share Capital", "account_type": "equity", "internal_group": "equity"},
        {"code": "3100", "name": "Retained Earnings", "account_type": "equity", "internal_group": "equity"},
        {"code": "3200", "name": "Share Premium", "account_type": "equity", "internal_group": "equity"},
        {"code": "3300", "name": "Dividends", "account_type": "equity", "internal_group": "equity"},
        # ── Income ────────────────────────────────────────────────
        {"code": "4000", "name": "Sales - Products", "account_type": "income", "internal_group": "income"},
        {"code": "4100", "name": "Sales - Services", "account_type": "income", "internal_group": "income"},
        {"code": "4200", "name": "Interest Received", "account_type": "income_other", "internal_group": "income"},
        {"code": "4300", "name": "Other Income", "account_type": "income_other", "internal_group": "income"},
        # ── Expenses ──────────────────────────────────────────────
        {"code": "5000", "name": "Cost of Sales", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "5100", "name": "Purchases", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "6000", "name": "Wages and Salaries", "account_type": "expense", "internal_group": "expense"},
        {"code": "6010", "name": "Employer's NI Contributions", "account_type": "expense", "internal_group": "expense"},
        {"code": "6020", "name": "Pension Costs", "account_type": "expense", "internal_group": "expense"},
        {"code": "6100", "name": "Rent and Rates", "account_type": "expense", "internal_group": "expense"},
        {"code": "6200", "name": "Light and Heat", "account_type": "expense", "internal_group": "expense"},
        {"code": "6300", "name": "Insurance", "account_type": "expense", "internal_group": "expense"},
        {"code": "6400", "name": "Repairs and Maintenance", "account_type": "expense", "internal_group": "expense"},
        {"code": "6500", "name": "Depreciation", "account_type": "expense_depreciation", "internal_group": "expense"},
        {"code": "6600", "name": "Advertising and Marketing", "account_type": "expense", "internal_group": "expense"},
        {"code": "6700", "name": "Professional Fees", "account_type": "expense", "internal_group": "expense"},
        {"code": "6800", "name": "Travel and Subsistence", "account_type": "expense", "internal_group": "expense"},
        {"code": "6900", "name": "Telephone and Internet", "account_type": "expense", "internal_group": "expense"},
        {"code": "7000", "name": "Office Stationery", "account_type": "expense", "internal_group": "expense"},
        {"code": "7100", "name": "Bank Charges", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "7200", "name": "Interest Paid", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "7500", "name": "Sundry Expenses", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "9000", "name": "Corporation Tax", "account_type": "expense", "internal_group": "expense"},
    ]}


def _uk_taxes() -> dict:
    """UK VAT tax templates."""
    return {"taxes": [
        {"name": "VAT 0% (Zero-rated)", "type_tax_use": "sale", "amount_type": "percent", "amount": 0.0, "description": "Zero-rated VAT", "tax_group": "vat"},
        {"name": "VAT 5% (Reduced)", "type_tax_use": "sale", "amount_type": "percent", "amount": 5.0, "description": "Reduced rate VAT", "tax_group": "vat"},
        {"name": "VAT 20% (Standard)", "type_tax_use": "sale", "amount_type": "percent", "amount": 20.0, "description": "Standard rate VAT", "tax_group": "vat"},
        {"name": "VAT 0% (Zero-rated) - Purchases", "type_tax_use": "purchase", "amount_type": "percent", "amount": 0.0, "description": "Zero-rated input VAT", "tax_group": "vat"},
        {"name": "VAT 5% (Reduced) - Purchases", "type_tax_use": "purchase", "amount_type": "percent", "amount": 5.0, "description": "Reduced rate input VAT", "tax_group": "vat"},
        {"name": "VAT 20% (Standard) - Purchases", "type_tax_use": "purchase", "amount_type": "percent", "amount": 20.0, "description": "Standard rate input VAT", "tax_group": "vat"},
    ]}


def _de_chart() -> dict:
    """German SKR03 chart of accounts."""
    return {"accounts": [
        # ── Assets ────────────────────────────────────────────────
        {"code": "0100", "name": "Grundstuecke (Land)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "0200", "name": "Technische Anlagen (Technical Equipment)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "0300", "name": "Maschinen (Machinery)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "0400", "name": "Betriebsausstattung (Operating Equipment)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "0500", "name": "Fuhrpark (Vehicles)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "0600", "name": "Bueroeinrichtung (Office Furniture)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "0700", "name": "GWG (Low-Value Assets)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "0800", "name": "Immaterielle Vermoegensgegenstaende (Intangibles)", "account_type": "asset_non_current", "internal_group": "asset"},
        {"code": "0900", "name": "Kumulierte Abschreibungen (Accumulated Depreciation)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1000", "name": "Kasse (Cash)", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        {"code": "1200", "name": "Bank", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        {"code": "1300", "name": "Wertpapiere (Securities)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1400", "name": "Forderungen aus Lieferungen (Trade Receivables)", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "1500", "name": "Sonstige Forderungen (Other Receivables)", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "1600", "name": "Vorsteuer (Input VAT)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1700", "name": "Vorraete - Rohstoffe (Raw Materials)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1800", "name": "Vorraete - Fertigerzeugnisse (Finished Goods)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1900", "name": "Aktive Rechnungsabgrenzung (Prepayments)", "account_type": "asset_prepayments", "internal_group": "asset"},
        # ── Liabilities ───────────────────────────────────────────
        {"code": "1600", "name": "Verbindlichkeiten aus L+L (Trade Payables)", "account_type": "liability_payable", "internal_group": "liability", "reconcile": True},
        {"code": "1700", "name": "Sonstige Verbindlichkeiten (Other Payables)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "1710", "name": "Umsatzsteuer (Output VAT)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "1720", "name": "Lohnsteuer (Payroll Tax)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "1730", "name": "Sozialversicherung (Social Insurance)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "1740", "name": "Koerperschaftsteuer (Corporate Tax Payable)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "1750", "name": "Rueckstellungen (Provisions)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "1800", "name": "Bankdarlehen (Bank Loans)", "account_type": "liability_non_current", "internal_group": "liability"},
        {"code": "1900", "name": "Passive Rechnungsabgrenzung (Deferred Revenue)", "account_type": "liability_current", "internal_group": "liability"},
        # ── Equity ────────────────────────────────────────────────
        {"code": "2000", "name": "Stammkapital (Share Capital)", "account_type": "equity", "internal_group": "equity"},
        {"code": "2100", "name": "Kapitalruecklagen (Capital Reserves)", "account_type": "equity", "internal_group": "equity"},
        {"code": "2200", "name": "Gewinnvortrag (Retained Earnings)", "account_type": "equity", "internal_group": "equity"},
        {"code": "2300", "name": "Jahresueberschuss (Net Income)", "account_type": "equity", "internal_group": "equity"},
        # ── Income ────────────────────────────────────────────────
        {"code": "8000", "name": "Erloese 19% USt (Revenue 19%)", "account_type": "income", "internal_group": "income"},
        {"code": "8100", "name": "Erloese 7% USt (Revenue 7%)", "account_type": "income", "internal_group": "income"},
        {"code": "8200", "name": "Erloese steuerfrei (Revenue Exempt)", "account_type": "income", "internal_group": "income"},
        {"code": "8300", "name": "Sonstige Ertraege (Other Income)", "account_type": "income_other", "internal_group": "income"},
        {"code": "8400", "name": "Zinsertraege (Interest Income)", "account_type": "income_other", "internal_group": "income"},
        # ── Expenses ──────────────────────────────────────────────
        {"code": "3000", "name": "Wareneinkauf (Purchases)", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "3100", "name": "Bezugskosten (Freight-In)", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "4000", "name": "Loehne und Gehaelter (Wages and Salaries)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4100", "name": "Soziale Abgaben (Social Contributions)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4200", "name": "Miete (Rent)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4300", "name": "Versicherungen (Insurance)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4400", "name": "Kfz-Kosten (Vehicle Costs)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4500", "name": "Werbekosten (Advertising)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4600", "name": "Reisekosten (Travel)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4700", "name": "Porto und Telefon (Post and Telecom)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4800", "name": "Abschreibungen (Depreciation)", "account_type": "expense_depreciation", "internal_group": "expense"},
        {"code": "4900", "name": "Sonstige Aufwendungen (Miscellaneous)", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "7000", "name": "Zinsaufwand (Interest Expense)", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "7100", "name": "Bankgebuehren (Bank Charges)", "account_type": "expense_other", "internal_group": "expense"},
    ]}


def _de_taxes() -> dict:
    """German Umsatzsteuer (VAT) templates."""
    return {"taxes": [
        {"name": "USt 0% (Steuerfrei)", "type_tax_use": "sale", "amount_type": "percent", "amount": 0.0, "description": "Tax-exempt", "tax_group": "ust"},
        {"name": "USt 7% (Ermaessigt)", "type_tax_use": "sale", "amount_type": "percent", "amount": 7.0, "description": "Reduced rate", "tax_group": "ust"},
        {"name": "USt 19% (Normal)", "type_tax_use": "sale", "amount_type": "percent", "amount": 19.0, "description": "Standard rate", "tax_group": "ust"},
        {"name": "VSt 0% (Steuerfrei)", "type_tax_use": "purchase", "amount_type": "percent", "amount": 0.0, "description": "Tax-exempt input", "tax_group": "vst"},
        {"name": "VSt 7% (Ermaessigt)", "type_tax_use": "purchase", "amount_type": "percent", "amount": 7.0, "description": "Reduced rate input", "tax_group": "vst"},
        {"name": "VSt 19% (Normal)", "type_tax_use": "purchase", "amount_type": "percent", "amount": 19.0, "description": "Standard rate input", "tax_group": "vst"},
    ]}


def _fr_chart() -> dict:
    """French PCG (Plan Comptable General) chart of accounts."""
    return {"accounts": [
        # ── Assets (Classe 2, 3, 4, 5) ────────────────────────────
        {"code": "211", "name": "Terrains (Land)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "213", "name": "Constructions (Buildings)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "215", "name": "Installations techniques (Technical Installations)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "218", "name": "Autres immobilisations corporelles (Other Fixed)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "205", "name": "Logiciels (Software)", "account_type": "asset_non_current", "internal_group": "asset"},
        {"code": "207", "name": "Fonds de commerce (Goodwill)", "account_type": "asset_non_current", "internal_group": "asset"},
        {"code": "280", "name": "Amortissements (Accumulated Depreciation)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "310", "name": "Matieres premieres (Raw Materials)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "355", "name": "Produits finis (Finished Goods)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "370", "name": "Marchandises (Merchandise)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "411", "name": "Clients (Trade Receivables)", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "416", "name": "Clients douteux (Doubtful Receivables)", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "445620", "name": "TVA deductible (Input VAT)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "486", "name": "Charges constatees d'avance (Prepayments)", "account_type": "asset_prepayments", "internal_group": "asset"},
        {"code": "512", "name": "Banque (Bank)", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        {"code": "530", "name": "Caisse (Cash)", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        # ── Liabilities ───────────────────────────────────────────
        {"code": "401", "name": "Fournisseurs (Trade Payables)", "account_type": "liability_payable", "internal_group": "liability", "reconcile": True},
        {"code": "421", "name": "Personnel - Remunerations dues (Wages Payable)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "431", "name": "Securite sociale (Social Security Payable)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "445710", "name": "TVA collectee (Output VAT)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "444", "name": "Impot sur les benefices (Corporate Tax)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "164", "name": "Emprunts bancaires (Bank Loans)", "account_type": "liability_non_current", "internal_group": "liability"},
        {"code": "487", "name": "Produits constates d'avance (Deferred Revenue)", "account_type": "liability_current", "internal_group": "liability"},
        # ── Equity ────────────────────────────────────────────────
        {"code": "101", "name": "Capital social (Share Capital)", "account_type": "equity", "internal_group": "equity"},
        {"code": "106", "name": "Reserves (Reserves)", "account_type": "equity", "internal_group": "equity"},
        {"code": "110", "name": "Report a nouveau (Retained Earnings)", "account_type": "equity", "internal_group": "equity"},
        {"code": "120", "name": "Resultat de l'exercice (Net Income)", "account_type": "equity", "internal_group": "equity"},
        # ── Income ────────────────────────────────────────────────
        {"code": "701", "name": "Ventes de produits finis (Product Sales)", "account_type": "income", "internal_group": "income"},
        {"code": "706", "name": "Prestations de services (Service Revenue)", "account_type": "income", "internal_group": "income"},
        {"code": "707", "name": "Ventes de marchandises (Merchandise Sales)", "account_type": "income", "internal_group": "income"},
        {"code": "764", "name": "Revenus des valeurs mobilieres (Investment Income)", "account_type": "income_other", "internal_group": "income"},
        {"code": "775", "name": "Produits de cessions (Gains on Disposal)", "account_type": "income_other", "internal_group": "income"},
        # ── Expenses ──────────────────────────────────────────────
        {"code": "601", "name": "Achats de matieres premieres (Raw Material Purchases)", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "607", "name": "Achats de marchandises (Merchandise Purchases)", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "613", "name": "Loyers (Rent)", "account_type": "expense", "internal_group": "expense"},
        {"code": "616", "name": "Assurances (Insurance)", "account_type": "expense", "internal_group": "expense"},
        {"code": "621", "name": "Personnel exterieur (Outsourced Staff)", "account_type": "expense", "internal_group": "expense"},
        {"code": "625", "name": "Deplacements (Travel)", "account_type": "expense", "internal_group": "expense"},
        {"code": "626", "name": "Frais postaux et telecom (Post and Telecom)", "account_type": "expense", "internal_group": "expense"},
        {"code": "627", "name": "Services bancaires (Banking Services)", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "641", "name": "Remunerations du personnel (Wages)", "account_type": "expense", "internal_group": "expense"},
        {"code": "645", "name": "Charges sociales (Social Charges)", "account_type": "expense", "internal_group": "expense"},
        {"code": "681", "name": "Dotations amortissements (Depreciation)", "account_type": "expense_depreciation", "internal_group": "expense"},
        {"code": "661", "name": "Interets (Interest Expense)", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "695", "name": "Impot sur les benefices (Income Tax)", "account_type": "expense", "internal_group": "expense"},
    ]}


def _fr_taxes() -> dict:
    """French TVA (VAT) templates."""
    return {"taxes": [
        {"name": "TVA 0% (Exonere)", "type_tax_use": "sale", "amount_type": "percent", "amount": 0.0, "description": "Exempt", "tax_group": "tva"},
        {"name": "TVA 5.5% (Reduit)", "type_tax_use": "sale", "amount_type": "percent", "amount": 5.5, "description": "Reduced rate", "tax_group": "tva"},
        {"name": "TVA 10% (Intermediaire)", "type_tax_use": "sale", "amount_type": "percent", "amount": 10.0, "description": "Intermediate rate", "tax_group": "tva"},
        {"name": "TVA 20% (Normal)", "type_tax_use": "sale", "amount_type": "percent", "amount": 20.0, "description": "Standard rate", "tax_group": "tva"},
        {"name": "TVA 0% (Exonere) - Achats", "type_tax_use": "purchase", "amount_type": "percent", "amount": 0.0, "description": "Exempt input", "tax_group": "tva"},
        {"name": "TVA 5.5% (Reduit) - Achats", "type_tax_use": "purchase", "amount_type": "percent", "amount": 5.5, "description": "Reduced rate input", "tax_group": "tva"},
        {"name": "TVA 10% (Intermediaire) - Achats", "type_tax_use": "purchase", "amount_type": "percent", "amount": 10.0, "description": "Intermediate rate input", "tax_group": "tva"},
        {"name": "TVA 20% (Normal) - Achats", "type_tax_use": "purchase", "amount_type": "percent", "amount": 20.0, "description": "Standard rate input", "tax_group": "tva"},
    ]}


def _es_chart() -> dict:
    """Spanish PGC (Plan General de Contabilidad) chart of accounts."""
    return {"accounts": [
        # ── Assets ────────────────────────────────────────────────
        {"code": "210", "name": "Terrenos (Land)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "211", "name": "Construcciones (Buildings)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "213", "name": "Maquinaria (Machinery)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "216", "name": "Mobiliario (Furniture)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "217", "name": "Equipos informaticos (IT Equipment)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "218", "name": "Elementos de transporte (Vehicles)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "203", "name": "Propiedad industrial (Industrial Property)", "account_type": "asset_non_current", "internal_group": "asset"},
        {"code": "206", "name": "Aplicaciones informaticas (Software)", "account_type": "asset_non_current", "internal_group": "asset"},
        {"code": "281", "name": "Amortizacion acumulada (Accumulated Depreciation)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "300", "name": "Mercaderias (Merchandise)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "310", "name": "Materias primas (Raw Materials)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "430", "name": "Clientes (Trade Receivables)", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "440", "name": "Deudores varios (Other Receivables)", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "472", "name": "HP IVA soportado (Input VAT)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "480", "name": "Gastos anticipados (Prepayments)", "account_type": "asset_prepayments", "internal_group": "asset"},
        {"code": "570", "name": "Caja (Cash)", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        {"code": "572", "name": "Bancos (Bank)", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        # ── Liabilities ───────────────────────────────────────────
        {"code": "400", "name": "Proveedores (Trade Payables)", "account_type": "liability_payable", "internal_group": "liability", "reconcile": True},
        {"code": "410", "name": "Acreedores (Other Payables)", "account_type": "liability_payable", "internal_group": "liability", "reconcile": True},
        {"code": "465", "name": "Remuneraciones pendientes (Wages Payable)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "475", "name": "HP acreedora por IVA (Output VAT)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "476", "name": "Organismos Seguridad Social (Social Security)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "473", "name": "HP retenciones (Tax Withholding)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "170", "name": "Deudas a largo plazo (Long-Term Debt)", "account_type": "liability_non_current", "internal_group": "liability"},
        {"code": "485", "name": "Ingresos anticipados (Deferred Revenue)", "account_type": "liability_current", "internal_group": "liability"},
        # ── Equity ────────────────────────────────────────────────
        {"code": "100", "name": "Capital social (Share Capital)", "account_type": "equity", "internal_group": "equity"},
        {"code": "112", "name": "Reserva legal (Legal Reserve)", "account_type": "equity", "internal_group": "equity"},
        {"code": "113", "name": "Reservas voluntarias (Voluntary Reserves)", "account_type": "equity", "internal_group": "equity"},
        {"code": "129", "name": "Resultado del ejercicio (Net Income)", "account_type": "equity", "internal_group": "equity"},
        # ── Income ────────────────────────────────────────────────
        {"code": "700", "name": "Ventas de mercaderias (Merchandise Sales)", "account_type": "income", "internal_group": "income"},
        {"code": "705", "name": "Prestaciones de servicios (Service Revenue)", "account_type": "income", "internal_group": "income"},
        {"code": "769", "name": "Otros ingresos financieros (Other Financial Income)", "account_type": "income_other", "internal_group": "income"},
        {"code": "771", "name": "Beneficios inmovilizado (Gains on Fixed Assets)", "account_type": "income_other", "internal_group": "income"},
        # ── Expenses ──────────────────────────────────────────────
        {"code": "600", "name": "Compras de mercaderias (Merchandise Purchases)", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "601", "name": "Compras de materias primas (Raw Material Purchases)", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "621", "name": "Arrendamientos (Rent)", "account_type": "expense", "internal_group": "expense"},
        {"code": "622", "name": "Reparaciones (Repairs)", "account_type": "expense", "internal_group": "expense"},
        {"code": "625", "name": "Seguros (Insurance)", "account_type": "expense", "internal_group": "expense"},
        {"code": "626", "name": "Servicios bancarios (Banking Services)", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "627", "name": "Publicidad (Advertising)", "account_type": "expense", "internal_group": "expense"},
        {"code": "628", "name": "Suministros (Utilities)", "account_type": "expense", "internal_group": "expense"},
        {"code": "629", "name": "Otros servicios (Other Services)", "account_type": "expense", "internal_group": "expense"},
        {"code": "640", "name": "Sueldos y salarios (Wages and Salaries)", "account_type": "expense", "internal_group": "expense"},
        {"code": "642", "name": "Seguridad social empresa (Employer Social Security)", "account_type": "expense", "internal_group": "expense"},
        {"code": "681", "name": "Amortizacion inmovilizado (Depreciation)", "account_type": "expense_depreciation", "internal_group": "expense"},
        {"code": "662", "name": "Intereses de deudas (Interest Expense)", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "630", "name": "Impuesto sobre beneficios (Income Tax)", "account_type": "expense", "internal_group": "expense"},
    ]}


def _es_taxes() -> dict:
    """Spanish IVA (VAT) templates."""
    return {"taxes": [
        {"name": "IVA 0% (Exento)", "type_tax_use": "sale", "amount_type": "percent", "amount": 0.0, "description": "Exempt", "tax_group": "iva"},
        {"name": "IVA 4% (Super reducido)", "type_tax_use": "sale", "amount_type": "percent", "amount": 4.0, "description": "Super-reduced rate", "tax_group": "iva"},
        {"name": "IVA 10% (Reducido)", "type_tax_use": "sale", "amount_type": "percent", "amount": 10.0, "description": "Reduced rate", "tax_group": "iva"},
        {"name": "IVA 21% (General)", "type_tax_use": "sale", "amount_type": "percent", "amount": 21.0, "description": "Standard rate", "tax_group": "iva"},
        {"name": "IVA 0% (Exento) - Compras", "type_tax_use": "purchase", "amount_type": "percent", "amount": 0.0, "description": "Exempt input", "tax_group": "iva"},
        {"name": "IVA 4% (Super reducido) - Compras", "type_tax_use": "purchase", "amount_type": "percent", "amount": 4.0, "description": "Super-reduced rate input", "tax_group": "iva"},
        {"name": "IVA 10% (Reducido) - Compras", "type_tax_use": "purchase", "amount_type": "percent", "amount": 10.0, "description": "Reduced rate input", "tax_group": "iva"},
        {"name": "IVA 21% (General) - Compras", "type_tax_use": "purchase", "amount_type": "percent", "amount": 21.0, "description": "Standard rate input", "tax_group": "iva"},
    ]}


def _it_chart() -> dict:
    """Italian Piano dei Conti chart of accounts."""
    return {"accounts": [
        # ── Assets ────────────────────────────────────────────────
        {"code": "06.01", "name": "Terreni (Land)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "06.02", "name": "Fabbricati (Buildings)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "06.03", "name": "Impianti e macchinari (Plant and Machinery)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "06.04", "name": "Attrezzature (Equipment)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "06.05", "name": "Automezzi (Vehicles)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "06.06", "name": "Mobili e arredi (Furniture)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "06.10", "name": "Fondo ammortamento (Accumulated Depreciation)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "04.01", "name": "Brevetti (Patents)", "account_type": "asset_non_current", "internal_group": "asset"},
        {"code": "04.02", "name": "Software", "account_type": "asset_non_current", "internal_group": "asset"},
        {"code": "04.03", "name": "Avviamento (Goodwill)", "account_type": "asset_non_current", "internal_group": "asset"},
        {"code": "14.01", "name": "Merci c/acquisti (Merchandise)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "14.02", "name": "Materie prime (Raw Materials)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "10.01", "name": "Crediti verso clienti (Trade Receivables)", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "10.05", "name": "Crediti diversi (Other Receivables)", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "10.10", "name": "IVA a credito (Input VAT)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "10.20", "name": "Risconti attivi (Prepayments)", "account_type": "asset_prepayments", "internal_group": "asset"},
        {"code": "18.01", "name": "Cassa (Cash)", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        {"code": "18.02", "name": "Banca c/c (Bank)", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        # ── Liabilities ───────────────────────────────────────────
        {"code": "20.01", "name": "Debiti verso fornitori (Trade Payables)", "account_type": "liability_payable", "internal_group": "liability", "reconcile": True},
        {"code": "20.05", "name": "Debiti diversi (Other Payables)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "20.10", "name": "Debiti per retribuzioni (Wages Payable)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "20.15", "name": "Debiti previdenziali (Social Security Payable)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "20.20", "name": "IVA a debito (Output VAT)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "20.25", "name": "Debiti tributari (Tax Payable)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "20.30", "name": "TFR (Severance Pay Fund)", "account_type": "liability_non_current", "internal_group": "liability"},
        {"code": "20.40", "name": "Mutui passivi (Mortgages)", "account_type": "liability_non_current", "internal_group": "liability"},
        {"code": "20.50", "name": "Risconti passivi (Deferred Revenue)", "account_type": "liability_current", "internal_group": "liability"},
        # ── Equity ────────────────────────────────────────────────
        {"code": "22.01", "name": "Capitale sociale (Share Capital)", "account_type": "equity", "internal_group": "equity"},
        {"code": "22.02", "name": "Riserva legale (Legal Reserve)", "account_type": "equity", "internal_group": "equity"},
        {"code": "22.03", "name": "Utili portati a nuovo (Retained Earnings)", "account_type": "equity", "internal_group": "equity"},
        {"code": "22.10", "name": "Utile d'esercizio (Net Income)", "account_type": "equity", "internal_group": "equity"},
        # ── Income ────────────────────────────────────────────────
        {"code": "40.01", "name": "Ricavi di vendita (Sales Revenue)", "account_type": "income", "internal_group": "income"},
        {"code": "40.02", "name": "Ricavi per servizi (Service Revenue)", "account_type": "income", "internal_group": "income"},
        {"code": "40.10", "name": "Proventi finanziari (Financial Income)", "account_type": "income_other", "internal_group": "income"},
        {"code": "40.20", "name": "Plusvalenze (Capital Gains)", "account_type": "income_other", "internal_group": "income"},
        # ── Expenses ──────────────────────────────────────────────
        {"code": "50.01", "name": "Acquisti merci (Merchandise Purchases)", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "50.02", "name": "Acquisti materie prime (Raw Materials)", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "50.10", "name": "Affitti passivi (Rent)", "account_type": "expense", "internal_group": "expense"},
        {"code": "50.15", "name": "Assicurazioni (Insurance)", "account_type": "expense", "internal_group": "expense"},
        {"code": "50.20", "name": "Manutenzioni (Maintenance)", "account_type": "expense", "internal_group": "expense"},
        {"code": "50.25", "name": "Utenze (Utilities)", "account_type": "expense", "internal_group": "expense"},
        {"code": "50.30", "name": "Pubblicita (Advertising)", "account_type": "expense", "internal_group": "expense"},
        {"code": "50.35", "name": "Spese postali e telefoniche (Post and Telecom)", "account_type": "expense", "internal_group": "expense"},
        {"code": "50.40", "name": "Spese bancarie (Bank Charges)", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "50.50", "name": "Salari e stipendi (Wages)", "account_type": "expense", "internal_group": "expense"},
        {"code": "50.55", "name": "Contributi previdenziali (Social Contributions)", "account_type": "expense", "internal_group": "expense"},
        {"code": "50.60", "name": "Ammortamenti (Depreciation)", "account_type": "expense_depreciation", "internal_group": "expense"},
        {"code": "50.70", "name": "Interessi passivi (Interest Expense)", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "50.90", "name": "Imposte sul reddito (Income Tax)", "account_type": "expense", "internal_group": "expense"},
    ]}


def _it_taxes() -> dict:
    """Italian IVA (VAT) templates."""
    return {"taxes": [
        {"name": "IVA 0% (Esente)", "type_tax_use": "sale", "amount_type": "percent", "amount": 0.0, "description": "Exempt", "tax_group": "iva"},
        {"name": "IVA 4% (Minima)", "type_tax_use": "sale", "amount_type": "percent", "amount": 4.0, "description": "Minimum rate", "tax_group": "iva"},
        {"name": "IVA 10% (Ridotta)", "type_tax_use": "sale", "amount_type": "percent", "amount": 10.0, "description": "Reduced rate", "tax_group": "iva"},
        {"name": "IVA 22% (Ordinaria)", "type_tax_use": "sale", "amount_type": "percent", "amount": 22.0, "description": "Standard rate", "tax_group": "iva"},
        {"name": "IVA 0% (Esente) - Acquisti", "type_tax_use": "purchase", "amount_type": "percent", "amount": 0.0, "description": "Exempt input", "tax_group": "iva"},
        {"name": "IVA 4% (Minima) - Acquisti", "type_tax_use": "purchase", "amount_type": "percent", "amount": 4.0, "description": "Minimum rate input", "tax_group": "iva"},
        {"name": "IVA 10% (Ridotta) - Acquisti", "type_tax_use": "purchase", "amount_type": "percent", "amount": 10.0, "description": "Reduced rate input", "tax_group": "iva"},
        {"name": "IVA 22% (Ordinaria) - Acquisti", "type_tax_use": "purchase", "amount_type": "percent", "amount": 22.0, "description": "Standard rate input", "tax_group": "iva"},
    ]}


def _be_chart() -> dict:
    """Belgian PCMN (Plan Comptable Minimum Normalise) chart of accounts."""
    return {"accounts": [
        # ── Assets ────────────────────────────────────────────────
        {"code": "220", "name": "Terrains (Land)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "221", "name": "Constructions (Buildings)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "230", "name": "Installations (Installations)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "240", "name": "Mobilier (Furniture)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "241", "name": "Materiel roulant (Vehicles)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "243", "name": "Materiel informatique (IT Equipment)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "280", "name": "Amortissements (Depreciation)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "204", "name": "Logiciels (Software)", "account_type": "asset_non_current", "internal_group": "asset"},
        {"code": "207", "name": "Goodwill", "account_type": "asset_non_current", "internal_group": "asset"},
        {"code": "340", "name": "Marchandises (Merchandise)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "300", "name": "Matieres premieres (Raw Materials)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "400", "name": "Clients (Trade Receivables)", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "411", "name": "TVA a recuperer (Input VAT)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "490", "name": "Charges a reporter (Prepayments)", "account_type": "asset_prepayments", "internal_group": "asset"},
        {"code": "550", "name": "Banque (Bank)", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        {"code": "570", "name": "Caisse (Cash)", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        {"code": "416", "name": "Creances diverses (Other Receivables)", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        # ── Liabilities ───────────────────────────────────────────
        {"code": "440", "name": "Fournisseurs (Trade Payables)", "account_type": "liability_payable", "internal_group": "liability", "reconcile": True},
        {"code": "451", "name": "TVA a payer (Output VAT)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "453", "name": "Precompte professionnel (Withholding Tax)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "454", "name": "ONSS (Social Security)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "455", "name": "Remunerations (Wages Payable)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "450", "name": "Impots (Tax Payable)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "170", "name": "Emprunts (Loans)", "account_type": "liability_non_current", "internal_group": "liability"},
        {"code": "492", "name": "Produits a reporter (Deferred Revenue)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "489", "name": "Autres dettes (Other Payables)", "account_type": "liability_current", "internal_group": "liability"},
        # ── Equity ────────────────────────────────────────────────
        {"code": "100", "name": "Capital souscrit (Share Capital)", "account_type": "equity", "internal_group": "equity"},
        {"code": "130", "name": "Reserve legale (Legal Reserve)", "account_type": "equity", "internal_group": "equity"},
        {"code": "133", "name": "Reserves disponibles (Available Reserves)", "account_type": "equity", "internal_group": "equity"},
        {"code": "140", "name": "Benefice reporte (Retained Earnings)", "account_type": "equity", "internal_group": "equity"},
        # ── Income ────────────────────────────────────────────────
        {"code": "700", "name": "Ventes de marchandises (Merchandise Sales)", "account_type": "income", "internal_group": "income"},
        {"code": "705", "name": "Prestations de services (Service Revenue)", "account_type": "income", "internal_group": "income"},
        {"code": "750", "name": "Produits financiers (Financial Income)", "account_type": "income_other", "internal_group": "income"},
        {"code": "764", "name": "Autres produits (Other Income)", "account_type": "income_other", "internal_group": "income"},
        # ── Expenses ──────────────────────────────────────────────
        {"code": "600", "name": "Achats de marchandises (Purchases)", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "601", "name": "Achats de matieres (Raw Materials)", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "610", "name": "Loyers (Rent)", "account_type": "expense", "internal_group": "expense"},
        {"code": "611", "name": "Entretien et reparations (Maintenance)", "account_type": "expense", "internal_group": "expense"},
        {"code": "612", "name": "Assurances (Insurance)", "account_type": "expense", "internal_group": "expense"},
        {"code": "613", "name": "Publicite (Advertising)", "account_type": "expense", "internal_group": "expense"},
        {"code": "614", "name": "Transports (Transportation)", "account_type": "expense", "internal_group": "expense"},
        {"code": "615", "name": "Frais de bureau (Office Expenses)", "account_type": "expense", "internal_group": "expense"},
        {"code": "620", "name": "Remunerations (Wages)", "account_type": "expense", "internal_group": "expense"},
        {"code": "621", "name": "Charges sociales (Social Charges)", "account_type": "expense", "internal_group": "expense"},
        {"code": "630", "name": "Amortissements (Depreciation)", "account_type": "expense_depreciation", "internal_group": "expense"},
        {"code": "650", "name": "Charges financieres (Financial Charges)", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "656", "name": "Frais bancaires (Bank Charges)", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "670", "name": "Impots (Taxes)", "account_type": "expense", "internal_group": "expense"},
    ]}


def _be_taxes() -> dict:
    """Belgian BTW/TVA (VAT) templates."""
    return {"taxes": [
        {"name": "BTW 0% (Vrijgesteld)", "type_tax_use": "sale", "amount_type": "percent", "amount": 0.0, "description": "Exempt", "tax_group": "btw"},
        {"name": "BTW 6%", "type_tax_use": "sale", "amount_type": "percent", "amount": 6.0, "description": "Reduced rate", "tax_group": "btw"},
        {"name": "BTW 12%", "type_tax_use": "sale", "amount_type": "percent", "amount": 12.0, "description": "Intermediate rate", "tax_group": "btw"},
        {"name": "BTW 21%", "type_tax_use": "sale", "amount_type": "percent", "amount": 21.0, "description": "Standard rate", "tax_group": "btw"},
        {"name": "BTW 0% (Vrijgesteld) - Aankopen", "type_tax_use": "purchase", "amount_type": "percent", "amount": 0.0, "description": "Exempt input", "tax_group": "btw"},
        {"name": "BTW 6% - Aankopen", "type_tax_use": "purchase", "amount_type": "percent", "amount": 6.0, "description": "Reduced rate input", "tax_group": "btw"},
        {"name": "BTW 12% - Aankopen", "type_tax_use": "purchase", "amount_type": "percent", "amount": 12.0, "description": "Intermediate rate input", "tax_group": "btw"},
        {"name": "BTW 21% - Aankopen", "type_tax_use": "purchase", "amount_type": "percent", "amount": 21.0, "description": "Standard rate input", "tax_group": "btw"},
    ]}


def _nl_chart() -> dict:
    """Dutch GAAP chart of accounts."""
    return {"accounts": [
        # ── Assets ────────────────────────────────────────────────
        {"code": "0100", "name": "Grond (Land)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "0200", "name": "Gebouwen (Buildings)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "0300", "name": "Machines (Machinery)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "0400", "name": "Inventaris (Equipment)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "0500", "name": "Vervoermiddelen (Vehicles)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "0600", "name": "Computerapparatuur (IT Equipment)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "0900", "name": "Afschrijvingen (Accumulated Depreciation)", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "0700", "name": "Software", "account_type": "asset_non_current", "internal_group": "asset"},
        {"code": "0800", "name": "Goodwill", "account_type": "asset_non_current", "internal_group": "asset"},
        {"code": "3000", "name": "Voorraad handelsgoederen (Merchandise)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "3100", "name": "Grondstoffen (Raw Materials)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1300", "name": "Debiteuren (Trade Receivables)", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "1350", "name": "Overige vorderingen (Other Receivables)", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "1510", "name": "Te vorderen BTW (Input VAT)", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1700", "name": "Vooruitbetaalde bedragen (Prepayments)", "account_type": "asset_prepayments", "internal_group": "asset"},
        {"code": "1000", "name": "Kas (Cash)", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        {"code": "1100", "name": "Bank", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        # ── Liabilities ───────────────────────────────────────────
        {"code": "1600", "name": "Crediteuren (Trade Payables)", "account_type": "liability_payable", "internal_group": "liability", "reconcile": True},
        {"code": "1520", "name": "Af te dragen BTW (Output VAT)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "1530", "name": "Loonheffing (Payroll Tax)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "1540", "name": "Sociale lasten (Social Security)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "1550", "name": "Nettolonen (Net Wages Payable)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "1560", "name": "Vennootschapsbelasting (Corporate Tax)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "0950", "name": "Langlopende leningen (Long-Term Loans)", "account_type": "liability_non_current", "internal_group": "liability"},
        {"code": "1750", "name": "Vooruit ontvangen (Deferred Revenue)", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "1650", "name": "Overige schulden (Other Payables)", "account_type": "liability_current", "internal_group": "liability"},
        # ── Equity ────────────────────────────────────────────────
        {"code": "0500", "name": "Aandelenkapitaal (Share Capital)", "account_type": "equity", "internal_group": "equity"},
        {"code": "0510", "name": "Wettelijke reserves (Legal Reserves)", "account_type": "equity", "internal_group": "equity"},
        {"code": "0520", "name": "Overige reserves (Other Reserves)", "account_type": "equity", "internal_group": "equity"},
        {"code": "0530", "name": "Resultaat lopend jaar (Net Income)", "account_type": "equity", "internal_group": "equity"},
        # ── Income ────────────────────────────────────────────────
        {"code": "8000", "name": "Omzet handelsgoederen (Merchandise Sales)", "account_type": "income", "internal_group": "income"},
        {"code": "8100", "name": "Omzet diensten (Service Revenue)", "account_type": "income", "internal_group": "income"},
        {"code": "8400", "name": "Rentebaten (Interest Income)", "account_type": "income_other", "internal_group": "income"},
        {"code": "8500", "name": "Overige opbrengsten (Other Income)", "account_type": "income_other", "internal_group": "income"},
        # ── Expenses ──────────────────────────────────────────────
        {"code": "7000", "name": "Inkopen handelsgoederen (Purchases)", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "7100", "name": "Inkopen grondstoffen (Raw Materials)", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "4000", "name": "Lonen en salarissen (Wages)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4100", "name": "Sociale lasten (Social Charges)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4200", "name": "Pensioenlasten (Pension)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4300", "name": "Huur (Rent)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4400", "name": "Verzekeringen (Insurance)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4500", "name": "Energie (Utilities)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4600", "name": "Reclame (Advertising)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4700", "name": "Kantoorkosten (Office Supplies)", "account_type": "expense", "internal_group": "expense"},
        {"code": "4800", "name": "Afschrijvingen (Depreciation)", "account_type": "expense_depreciation", "internal_group": "expense"},
        {"code": "4900", "name": "Overige bedrijfskosten (Other Expenses)", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "4910", "name": "Bankkosten (Bank Charges)", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "4920", "name": "Rentelasten (Interest Expense)", "account_type": "expense_other", "internal_group": "expense"},
    ]}


def _nl_taxes() -> dict:
    """Dutch BTW (VAT) templates."""
    return {"taxes": [
        {"name": "BTW 0% (Vrijgesteld)", "type_tax_use": "sale", "amount_type": "percent", "amount": 0.0, "description": "Exempt", "tax_group": "btw"},
        {"name": "BTW 9% (Laag)", "type_tax_use": "sale", "amount_type": "percent", "amount": 9.0, "description": "Reduced rate", "tax_group": "btw"},
        {"name": "BTW 21% (Hoog)", "type_tax_use": "sale", "amount_type": "percent", "amount": 21.0, "description": "Standard rate", "tax_group": "btw"},
        {"name": "BTW 0% (Vrijgesteld) - Inkopen", "type_tax_use": "purchase", "amount_type": "percent", "amount": 0.0, "description": "Exempt input", "tax_group": "btw"},
        {"name": "BTW 9% (Laag) - Inkopen", "type_tax_use": "purchase", "amount_type": "percent", "amount": 9.0, "description": "Reduced rate input", "tax_group": "btw"},
        {"name": "BTW 21% (Hoog) - Inkopen", "type_tax_use": "purchase", "amount_type": "percent", "amount": 21.0, "description": "Standard rate input", "tax_group": "btw"},
    ]}


def _ca_chart() -> dict:
    """Canadian GAAP chart of accounts."""
    return {"accounts": [
        # ── Assets ────────────────────────────────────────────────
        {"code": "1000", "name": "Cash", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        {"code": "1010", "name": "Petty Cash", "account_type": "asset_cash", "internal_group": "asset"},
        {"code": "1050", "name": "Bank - CAD", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        {"code": "1060", "name": "Bank - USD", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        {"code": "1100", "name": "Accounts Receivable", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "1150", "name": "Allowance for Doubtful Accounts", "account_type": "asset_receivable", "internal_group": "asset"},
        {"code": "1200", "name": "Inventory", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1250", "name": "Prepaid Expenses", "account_type": "asset_prepayments", "internal_group": "asset"},
        {"code": "1300", "name": "GST/HST Receivable", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1310", "name": "PST Receivable", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1500", "name": "Land", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1510", "name": "Buildings", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1520", "name": "Equipment", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1530", "name": "Furniture and Fixtures", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1540", "name": "Computer Equipment", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1550", "name": "Vehicles", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1600", "name": "Accumulated Depreciation", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1700", "name": "Intangible Assets", "account_type": "asset_non_current", "internal_group": "asset"},
        # ── Liabilities ───────────────────────────────────────────
        {"code": "2000", "name": "Accounts Payable", "account_type": "liability_payable", "internal_group": "liability", "reconcile": True},
        {"code": "2050", "name": "Credit Card Payable", "account_type": "liability_credit_card", "internal_group": "liability"},
        {"code": "2100", "name": "GST/HST Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2110", "name": "PST Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2200", "name": "Wages Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2210", "name": "CPP Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2220", "name": "EI Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2230", "name": "Income Tax Deductions Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2300", "name": "Corporate Income Tax Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2400", "name": "Unearned Revenue", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2500", "name": "Long-Term Debt", "account_type": "liability_non_current", "internal_group": "liability"},
        # ── Equity ────────────────────────────────────────────────
        {"code": "3000", "name": "Share Capital", "account_type": "equity", "internal_group": "equity"},
        {"code": "3100", "name": "Retained Earnings", "account_type": "equity", "internal_group": "equity"},
        {"code": "3200", "name": "Dividends Declared", "account_type": "equity", "internal_group": "equity"},
        # ── Income ────────────────────────────────────────────────
        {"code": "4000", "name": "Sales Revenue", "account_type": "income", "internal_group": "income"},
        {"code": "4100", "name": "Service Revenue", "account_type": "income", "internal_group": "income"},
        {"code": "4200", "name": "Interest Income", "account_type": "income_other", "internal_group": "income"},
        {"code": "4300", "name": "Other Income", "account_type": "income_other", "internal_group": "income"},
        {"code": "4400", "name": "Foreign Exchange Gain", "account_type": "income_other", "internal_group": "income"},
        # ── Expenses ──────────────────────────────────────────────
        {"code": "5000", "name": "Cost of Goods Sold", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "5100", "name": "Purchases", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "6000", "name": "Salaries and Wages", "account_type": "expense", "internal_group": "expense"},
        {"code": "6010", "name": "Employee Benefits", "account_type": "expense", "internal_group": "expense"},
        {"code": "6020", "name": "CPP Expense (Employer)", "account_type": "expense", "internal_group": "expense"},
        {"code": "6030", "name": "EI Expense (Employer)", "account_type": "expense", "internal_group": "expense"},
        {"code": "6100", "name": "Rent", "account_type": "expense", "internal_group": "expense"},
        {"code": "6200", "name": "Utilities", "account_type": "expense", "internal_group": "expense"},
        {"code": "6300", "name": "Insurance", "account_type": "expense", "internal_group": "expense"},
        {"code": "6400", "name": "Office Supplies", "account_type": "expense", "internal_group": "expense"},
        {"code": "6500", "name": "CCA / Depreciation", "account_type": "expense_depreciation", "internal_group": "expense"},
        {"code": "6600", "name": "Advertising and Promotion", "account_type": "expense", "internal_group": "expense"},
        {"code": "6700", "name": "Professional Fees", "account_type": "expense", "internal_group": "expense"},
        {"code": "6800", "name": "Travel", "account_type": "expense", "internal_group": "expense"},
        {"code": "6900", "name": "Meals and Entertainment", "account_type": "expense", "internal_group": "expense"},
        {"code": "7000", "name": "Interest and Bank Charges", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "7100", "name": "Foreign Exchange Loss", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "9000", "name": "Income Tax Expense", "account_type": "expense", "internal_group": "expense"},
    ]}


def _ca_taxes() -> dict:
    """Canadian GST/HST/PST tax templates."""
    return {"taxes": [
        {"name": "GST 5%", "type_tax_use": "sale", "amount_type": "percent", "amount": 5.0, "description": "Goods and Services Tax", "tax_group": "gst"},
        {"name": "HST 13% (ON)", "type_tax_use": "sale", "amount_type": "percent", "amount": 13.0, "description": "Harmonized Sales Tax - Ontario", "tax_group": "hst"},
        {"name": "HST 15% (NB/NL/NS/PE)", "type_tax_use": "sale", "amount_type": "percent", "amount": 15.0, "description": "Harmonized Sales Tax - Atlantic", "tax_group": "hst"},
        {"name": "PST 7% (BC)", "type_tax_use": "sale", "amount_type": "percent", "amount": 7.0, "description": "Provincial Sales Tax - BC", "tax_group": "pst"},
        {"name": "PST 6% (SK)", "type_tax_use": "sale", "amount_type": "percent", "amount": 6.0, "description": "Provincial Sales Tax - Saskatchewan", "tax_group": "pst"},
        {"name": "QST 9.975% (QC)", "type_tax_use": "sale", "amount_type": "percent", "amount": 9.975, "description": "Quebec Sales Tax", "tax_group": "qst"},
        {"name": "GST 5% - Purchases", "type_tax_use": "purchase", "amount_type": "percent", "amount": 5.0, "description": "GST input tax credit", "tax_group": "gst"},
        {"name": "HST 13% (ON) - Purchases", "type_tax_use": "purchase", "amount_type": "percent", "amount": 13.0, "description": "HST input tax credit - Ontario", "tax_group": "hst"},
        {"name": "HST 15% (NB/NL/NS/PE) - Purchases", "type_tax_use": "purchase", "amount_type": "percent", "amount": 15.0, "description": "HST input tax credit - Atlantic", "tax_group": "hst"},
        {"name": "PST 7% (BC) - Purchases", "type_tax_use": "purchase", "amount_type": "percent", "amount": 7.0, "description": "PST - BC (generally not recoverable)", "tax_group": "pst"},
        {"name": "QST 9.975% (QC) - Purchases", "type_tax_use": "purchase", "amount_type": "percent", "amount": 9.975, "description": "QST input tax refund", "tax_group": "qst"},
    ]}


def _au_chart() -> dict:
    """Australian chart of accounts."""
    return {"accounts": [
        # ── Assets ────────────────────────────────────────────────
        {"code": "1-1000", "name": "Cash at Bank", "account_type": "asset_cash", "internal_group": "asset", "reconcile": True},
        {"code": "1-1010", "name": "Petty Cash", "account_type": "asset_cash", "internal_group": "asset"},
        {"code": "1-1050", "name": "Term Deposits", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1-1100", "name": "Trade Debtors", "account_type": "asset_receivable", "internal_group": "asset", "reconcile": True},
        {"code": "1-1150", "name": "Provision for Doubtful Debts", "account_type": "asset_receivable", "internal_group": "asset"},
        {"code": "1-1200", "name": "Inventory", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1-1250", "name": "Prepayments", "account_type": "asset_prepayments", "internal_group": "asset"},
        {"code": "1-1300", "name": "GST Receivable", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1-1400", "name": "Other Current Assets", "account_type": "asset_current", "internal_group": "asset"},
        {"code": "1-1500", "name": "Land", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1-1510", "name": "Buildings", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1-1520", "name": "Plant and Equipment", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1-1530", "name": "Motor Vehicles", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1-1540", "name": "Office Equipment", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1-1550", "name": "Computer Equipment", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1-1600", "name": "Accumulated Depreciation", "account_type": "asset_fixed", "internal_group": "asset"},
        {"code": "1-1700", "name": "Intangible Assets", "account_type": "asset_non_current", "internal_group": "asset"},
        {"code": "1-1800", "name": "Goodwill", "account_type": "asset_non_current", "internal_group": "asset"},
        # ── Liabilities ───────────────────────────────────────────
        {"code": "2-1000", "name": "Trade Creditors", "account_type": "liability_payable", "internal_group": "liability", "reconcile": True},
        {"code": "2-1050", "name": "Credit Card", "account_type": "liability_credit_card", "internal_group": "liability"},
        {"code": "2-1100", "name": "GST Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2-1150", "name": "PAYG Withholding Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2-1200", "name": "Superannuation Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2-1250", "name": "Wages Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2-1300", "name": "Income Tax Payable", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2-1400", "name": "Provision for Annual Leave", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2-1410", "name": "Provision for Long Service Leave", "account_type": "liability_non_current", "internal_group": "liability"},
        {"code": "2-1500", "name": "Unearned Revenue", "account_type": "liability_current", "internal_group": "liability"},
        {"code": "2-1600", "name": "Bank Loan", "account_type": "liability_non_current", "internal_group": "liability"},
        # ── Equity ────────────────────────────────────────────────
        {"code": "3-1000", "name": "Share Capital", "account_type": "equity", "internal_group": "equity"},
        {"code": "3-1100", "name": "Retained Earnings", "account_type": "equity", "internal_group": "equity"},
        {"code": "3-1200", "name": "Dividends", "account_type": "equity", "internal_group": "equity"},
        {"code": "3-1300", "name": "Current Year Earnings", "account_type": "equity", "internal_group": "equity"},
        # ── Income ────────────────────────────────────────────────
        {"code": "4-1000", "name": "Sales Revenue", "account_type": "income", "internal_group": "income"},
        {"code": "4-1100", "name": "Service Revenue", "account_type": "income", "internal_group": "income"},
        {"code": "4-1200", "name": "Interest Income", "account_type": "income_other", "internal_group": "income"},
        {"code": "4-1300", "name": "Other Income", "account_type": "income_other", "internal_group": "income"},
        # ── Expenses ──────────────────────────────────────────────
        {"code": "5-1000", "name": "Cost of Goods Sold", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "5-1100", "name": "Purchases", "account_type": "expense_direct_cost", "internal_group": "expense"},
        {"code": "6-1000", "name": "Wages and Salaries", "account_type": "expense", "internal_group": "expense"},
        {"code": "6-1010", "name": "Superannuation Expense", "account_type": "expense", "internal_group": "expense"},
        {"code": "6-1020", "name": "Workers Compensation", "account_type": "expense", "internal_group": "expense"},
        {"code": "6-1100", "name": "Rent", "account_type": "expense", "internal_group": "expense"},
        {"code": "6-1200", "name": "Electricity and Gas", "account_type": "expense", "internal_group": "expense"},
        {"code": "6-1300", "name": "Insurance", "account_type": "expense", "internal_group": "expense"},
        {"code": "6-1400", "name": "Repairs and Maintenance", "account_type": "expense", "internal_group": "expense"},
        {"code": "6-1500", "name": "Depreciation", "account_type": "expense_depreciation", "internal_group": "expense"},
        {"code": "6-1600", "name": "Advertising and Marketing", "account_type": "expense", "internal_group": "expense"},
        {"code": "6-1700", "name": "Professional Fees", "account_type": "expense", "internal_group": "expense"},
        {"code": "6-1800", "name": "Motor Vehicle Expenses", "account_type": "expense", "internal_group": "expense"},
        {"code": "6-1900", "name": "Telephone and Internet", "account_type": "expense", "internal_group": "expense"},
        {"code": "6-2000", "name": "Office Supplies", "account_type": "expense", "internal_group": "expense"},
        {"code": "6-2100", "name": "Travel Expenses", "account_type": "expense", "internal_group": "expense"},
        {"code": "6-2200", "name": "Bank Fees", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "6-2300", "name": "Interest Paid", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "6-2400", "name": "Sundry Expenses", "account_type": "expense_other", "internal_group": "expense"},
        {"code": "9-1000", "name": "Income Tax Expense", "account_type": "expense", "internal_group": "expense"},
    ]}


def _au_taxes() -> dict:
    """Australian GST templates."""
    return {"taxes": [
        {"name": "GST 10%", "type_tax_use": "sale", "amount_type": "percent", "amount": 10.0, "description": "Goods and Services Tax", "tax_group": "gst"},
        {"name": "GST Free", "type_tax_use": "sale", "amount_type": "percent", "amount": 0.0, "description": "GST-Free supply", "tax_group": "gst"},
        {"name": "Input Taxed", "type_tax_use": "sale", "amount_type": "percent", "amount": 0.0, "description": "Input taxed (no GST)", "tax_group": "gst"},
        {"name": "GST 10% - Purchases", "type_tax_use": "purchase", "amount_type": "percent", "amount": 10.0, "description": "GST on purchases", "tax_group": "gst"},
        {"name": "GST Free - Purchases", "type_tax_use": "purchase", "amount_type": "percent", "amount": 0.0, "description": "GST-Free purchases", "tax_group": "gst"},
        {"name": "No ABN Withholding", "type_tax_use": "purchase", "amount_type": "percent", "amount": 46.5, "description": "Withholding for suppliers without ABN", "tax_group": "withholding"},
    ]}


# ── EU Fiscal position templates ─────────────────────────────────────

def _eu_fiscal_positions() -> dict:
    """Standard EU fiscal position templates."""
    return {"fiscal_positions": [
        {
            "name": "Intra-EU B2B",
            "auto_apply": True,
            "description": "Reverse charge for intra-EU business-to-business transactions",
            "sequence": 10,
        },
        {
            "name": "Extra-EU (Export)",
            "auto_apply": True,
            "description": "Export outside the EU - zero-rated supplies",
            "sequence": 20,
        },
    ]}


def _non_eu_fiscal_positions() -> dict:
    """Standard fiscal positions for non-EU countries."""
    return {"fiscal_positions": [
        {
            "name": "Domestic",
            "auto_apply": False,
            "description": "Standard domestic transactions",
            "sequence": 10,
        },
        {
            "name": "Export",
            "auto_apply": True,
            "description": "Export transactions - zero-rated or exempt",
            "sequence": 20,
        },
    ]}


# ── Package definitions ──────────────────────────────────────────────

_DEFAULT_PACKAGES: list[dict] = [
    {
        "country_code": "US",
        "country_name": "United States",
        "currency_code": "USD",
        "version": "1.0",
        "description": "US GAAP chart of accounts with federal/state sales tax and use tax",
        "chart_template_data": _us_chart(),
        "tax_template_data": _us_taxes(),
        "fiscal_position_data": _non_eu_fiscal_positions(),
        "legal_statement_types": ["balance_sheet", "income_statement", "cash_flow_statement", "sales_tax_return"],
        "date_format": "%m/%d/%Y",
        "decimal_separator": ".",
        "thousands_separator": ",",
        "fiscal_year_start_month": 1,
        "fiscal_year_start_day": 1,
    },
    {
        "country_code": "GB",
        "country_name": "United Kingdom",
        "currency_code": "GBP",
        "version": "1.0",
        "description": "UK GAAP chart of accounts with VAT at 0%, 5%, and 20%",
        "chart_template_data": _uk_chart(),
        "tax_template_data": _uk_taxes(),
        "fiscal_position_data": _non_eu_fiscal_positions(),
        "legal_statement_types": ["vat_return", "balance_sheet", "profit_and_loss", "corporation_tax_return"],
        "date_format": "%d/%m/%Y",
        "decimal_separator": ".",
        "thousands_separator": ",",
        "fiscal_year_start_month": 4,
        "fiscal_year_start_day": 6,
    },
    {
        "country_code": "DE",
        "country_name": "Germany",
        "currency_code": "EUR",
        "version": "1.0",
        "description": "German SKR03 chart of accounts with Umsatzsteuer at 0%, 7%, and 19%",
        "chart_template_data": _de_chart(),
        "tax_template_data": _de_taxes(),
        "fiscal_position_data": _eu_fiscal_positions(),
        "legal_statement_types": ["umsatzsteuervoranmeldung", "bilanz", "guv", "e_bilanz"],
        "date_format": "%d.%m.%Y",
        "decimal_separator": ",",
        "thousands_separator": ".",
        "fiscal_year_start_month": 1,
        "fiscal_year_start_day": 1,
    },
    {
        "country_code": "FR",
        "country_name": "France",
        "currency_code": "EUR",
        "version": "1.0",
        "description": "French PCG chart of accounts with TVA at 0%, 5.5%, 10%, and 20%",
        "chart_template_data": _fr_chart(),
        "tax_template_data": _fr_taxes(),
        "fiscal_position_data": _eu_fiscal_positions(),
        "legal_statement_types": ["declaration_tva", "bilan", "compte_resultat", "liasse_fiscale"],
        "date_format": "%d/%m/%Y",
        "decimal_separator": ",",
        "thousands_separator": " ",
        "fiscal_year_start_month": 1,
        "fiscal_year_start_day": 1,
    },
    {
        "country_code": "ES",
        "country_name": "Spain",
        "currency_code": "EUR",
        "version": "1.0",
        "description": "Spanish PGC chart of accounts with IVA at 0%, 4%, 10%, and 21%",
        "chart_template_data": _es_chart(),
        "tax_template_data": _es_taxes(),
        "fiscal_position_data": _eu_fiscal_positions(),
        "legal_statement_types": ["modelo_303", "modelo_390", "balance_situacion", "cuenta_perdidas_ganancias"],
        "date_format": "%d/%m/%Y",
        "decimal_separator": ",",
        "thousands_separator": ".",
        "fiscal_year_start_month": 1,
        "fiscal_year_start_day": 1,
    },
    {
        "country_code": "IT",
        "country_name": "Italy",
        "currency_code": "EUR",
        "version": "1.0",
        "description": "Italian Piano dei Conti with IVA at 0%, 4%, 10%, and 22%",
        "chart_template_data": _it_chart(),
        "tax_template_data": _it_taxes(),
        "fiscal_position_data": _eu_fiscal_positions(),
        "legal_statement_types": ["liquidazione_iva", "bilancio", "conto_economico", "fatturazione_elettronica"],
        "date_format": "%d/%m/%Y",
        "decimal_separator": ",",
        "thousands_separator": ".",
        "fiscal_year_start_month": 1,
        "fiscal_year_start_day": 1,
    },
    {
        "country_code": "BE",
        "country_name": "Belgium",
        "currency_code": "EUR",
        "version": "1.0",
        "description": "Belgian PCMN chart of accounts with BTW/TVA at 0%, 6%, 12%, and 21%",
        "chart_template_data": _be_chart(),
        "tax_template_data": _be_taxes(),
        "fiscal_position_data": _eu_fiscal_positions(),
        "legal_statement_types": ["btw_aangifte", "jaarrekening", "vennootschapsbelasting"],
        "date_format": "%d/%m/%Y",
        "decimal_separator": ",",
        "thousands_separator": ".",
        "fiscal_year_start_month": 1,
        "fiscal_year_start_day": 1,
    },
    {
        "country_code": "NL",
        "country_name": "Netherlands",
        "currency_code": "EUR",
        "version": "1.0",
        "description": "Dutch GAAP chart of accounts with BTW at 0%, 9%, and 21%",
        "chart_template_data": _nl_chart(),
        "tax_template_data": _nl_taxes(),
        "fiscal_position_data": _eu_fiscal_positions(),
        "legal_statement_types": ["btw_aangifte", "jaarrekening", "vennootschapsbelasting"],
        "date_format": "%d-%m-%Y",
        "decimal_separator": ",",
        "thousands_separator": ".",
        "fiscal_year_start_month": 1,
        "fiscal_year_start_day": 1,
    },
    {
        "country_code": "CA",
        "country_name": "Canada",
        "currency_code": "CAD",
        "version": "1.0",
        "description": "Canadian GAAP chart of accounts with GST/HST/PST/QST",
        "chart_template_data": _ca_chart(),
        "tax_template_data": _ca_taxes(),
        "fiscal_position_data": _non_eu_fiscal_positions(),
        "legal_statement_types": ["gst_hst_return", "balance_sheet", "income_statement", "t2_corporate_return"],
        "date_format": "%Y-%m-%d",
        "decimal_separator": ".",
        "thousands_separator": ",",
        "fiscal_year_start_month": 1,
        "fiscal_year_start_day": 1,
    },
    {
        "country_code": "AU",
        "country_name": "Australia",
        "currency_code": "AUD",
        "version": "1.0",
        "description": "Australian chart of accounts with GST at 10%",
        "chart_template_data": _au_chart(),
        "tax_template_data": _au_taxes(),
        "fiscal_position_data": _non_eu_fiscal_positions(),
        "legal_statement_types": ["bas", "balance_sheet", "profit_and_loss", "company_tax_return"],
        "date_format": "%d/%m/%Y",
        "decimal_separator": ".",
        "thousands_separator": ",",
        "fiscal_year_start_month": 7,
        "fiscal_year_start_day": 1,
    },
]
