"""Accounting module manifest — discovered by the module registry at startup."""

from fastapi import APIRouter

from src.core.database.base import Base
from src.core.registry.module_base import ERPModule


class AccountingModule(ERPModule):
    name = "accounting"
    version = "1.0.0"
    depends = ["core", "contacts", "product"]
    description = (
        "Double-entry accounting — chart of accounts, journals, invoices, "
        "payments, taxes, reconciliation, assets, analytics, financial reports"
    )

    def get_router(self) -> APIRouter:
        from src.modules.accounting.router import router
        return router

    def get_models(self) -> list[type[Base]]:
        from src.modules.accounting.models.account import Account, AccountTag
        from src.modules.accounting.models.journal import Journal
        from src.modules.accounting.models.tax import Tax, TaxRepartitionLine
        from src.modules.accounting.models.move import Move, MoveLine
        from src.modules.accounting.models.payment import (
            Payment, PaymentMethod, BatchPayment,
        )
        from src.modules.accounting.models.payment_term import (
            PaymentTerm, PaymentTermLine,
            FiscalPosition, FiscalPositionTax, FiscalPositionAccount,
        )
        from src.modules.accounting.models.reconciliation import (
            FullReconcile, PartialReconcile,
            ReconcileModel, ReconcileModelLine,
        )
        from src.modules.accounting.models.fiscal_year import FiscalYear
        from src.modules.accounting.models.analytic import (
            AnalyticPlan, AnalyticAccount, AnalyticLine,
            Budget, BudgetLine,
        )
        from src.modules.accounting.models.bank_statement import (
            BankStatement, BankStatementLine,
        )
        from src.modules.accounting.models.asset import (
            AssetGroup, Asset, AssetDepreciationLine,
        )
        from src.modules.accounting.models.localization import (
            LocalizationPackage, LocalizationInstallLog,
        )

        return [
            # Chart of accounts
            AccountTag,
            Account,
            # Journals
            Journal,
            # Taxes
            Tax,
            TaxRepartitionLine,
            # Journal entries & invoices
            Move,
            MoveLine,
            # Payments
            PaymentMethod,
            Payment,
            BatchPayment,
            # Payment terms & fiscal positions
            PaymentTerm,
            PaymentTermLine,
            FiscalPosition,
            FiscalPositionTax,
            FiscalPositionAccount,
            # Reconciliation
            FullReconcile,
            PartialReconcile,
            ReconcileModel,
            ReconcileModelLine,
            # Fiscal years
            FiscalYear,
            # Analytics & budgets
            AnalyticPlan,
            AnalyticAccount,
            AnalyticLine,
            Budget,
            BudgetLine,
            # Bank statements
            BankStatement,
            BankStatementLine,
            # Assets
            AssetGroup,
            Asset,
            AssetDepreciationLine,
            # Localization
            LocalizationPackage,
            LocalizationInstallLog,
        ]

    def get_permissions(self) -> list[dict]:
        return [
            # Chart of Accounts
            {"codename": "accounting.account.read", "description": "View chart of accounts"},
            {"codename": "accounting.account.manage", "description": "Manage chart of accounts"},
            # Journals
            {"codename": "accounting.journal.read", "description": "View journals"},
            {"codename": "accounting.journal.manage", "description": "Manage journals"},
            # Journal Entries / Invoices
            {"codename": "accounting.move.create", "description": "Create journal entries and invoices"},
            {"codename": "accounting.move.read", "description": "View journal entries and invoices"},
            {"codename": "accounting.move.update", "description": "Edit draft journal entries"},
            {"codename": "accounting.move.post", "description": "Post, cancel, and reverse entries"},
            # Taxes
            {"codename": "accounting.tax.read", "description": "View and compute taxes"},
            {"codename": "accounting.tax.manage", "description": "Manage taxes and repartition lines"},
            # Payments
            {"codename": "accounting.payment.create", "description": "Register payments"},
            {"codename": "accounting.payment.read", "description": "View payments"},
            {"codename": "accounting.payment.post", "description": "Confirm and cancel payments"},
            # Payment Terms & Fiscal Positions (shared config permission)
            {"codename": "accounting.config.read", "description": "View payment terms and fiscal positions"},
            {"codename": "accounting.config.manage", "description": "Manage payment terms and fiscal positions"},
            # Reconciliation
            {"codename": "accounting.reconcile.read", "description": "View reconciliation suggestions"},
            {"codename": "accounting.reconcile.manage", "description": "Reconcile and unreconcile entries"},
            # Fiscal Years
            {"codename": "accounting.fiscal.read", "description": "View fiscal years"},
            {"codename": "accounting.fiscal.manage", "description": "Manage and close fiscal years"},
            # Analytics & Budgets
            {"codename": "accounting.analytic.read", "description": "View analytic accounts and budgets"},
            {"codename": "accounting.analytic.manage", "description": "Manage analytic plans, accounts, and budgets"},
            # Assets
            {"codename": "accounting.asset.read", "description": "View fixed assets"},
            {"codename": "accounting.asset.manage", "description": "Manage assets and depreciation"},
            # Bank Statements
            {"codename": "accounting.bank.read", "description": "View bank statements"},
            {"codename": "accounting.bank.manage", "description": "Manage bank statements"},
            # Reports
            {"codename": "accounting.report.read", "description": "View financial reports"},
            # Localization
            {"codename": "accounting.localization.read", "description": "View localization packages"},
            {"codename": "accounting.localization.manage", "description": "Install and manage localization packages"},
        ]

    def on_startup(self) -> None:
        from src.core.events import event_bus

        # Cross-module event subscriptions can be registered here
        # e.g. event_bus.subscribe("sale.order.confirmed", handle_sale_confirmed)
        pass
