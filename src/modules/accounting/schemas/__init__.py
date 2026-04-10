"""Accounting module Pydantic schemas."""

from src.modules.accounting.schemas.account import (
    AccountTagCreate, AccountTagRead,
    AccountCreate, AccountUpdate, AccountRead, AccountReadBrief, AccountFilter,
)
from src.modules.accounting.schemas.journal import (
    JournalCreate, JournalUpdate, JournalRead, JournalReadBrief,
)
from src.modules.accounting.schemas.tax import (
    TaxRepartitionLineCreate, TaxRepartitionLineRead,
    TaxCreate, TaxUpdate, TaxRead, TaxReadBrief,
    TaxComputeRequest, TaxComputeResult,
)
from src.modules.accounting.schemas.move import (
    MoveLineCreate, MoveLineUpdate, MoveLineRead, MoveLineReadBrief,
    MoveCreate, MoveUpdate, MoveRead, MoveReadBrief, MoveFilter,
)
from src.modules.accounting.schemas.payment import (
    PaymentCreate, PaymentUpdate, PaymentRead, PaymentReadBrief, PaymentFilter,
    BatchPaymentCreate, BatchPaymentRead,
)
from src.modules.accounting.schemas.payment_term import (
    PaymentTermLineCreate, PaymentTermLineRead,
    PaymentTermCreate, PaymentTermUpdate, PaymentTermRead,
    FiscalPositionTaxCreate, FiscalPositionTaxRead,
    FiscalPositionAccountCreate, FiscalPositionAccountRead,
    FiscalPositionCreate, FiscalPositionUpdate, FiscalPositionRead,
)
from src.modules.accounting.schemas.reconciliation import (
    ReconcileModelLineCreate, ReconcileModelLineRead,
    ReconcileModelCreate, ReconcileModelUpdate, ReconcileModelRead,
    PartialReconcileRead, FullReconcileRead,
)
from src.modules.accounting.schemas.fiscal_year import (
    FiscalYearCreate, FiscalYearUpdate, FiscalYearRead,
)
from src.modules.accounting.schemas.analytic import (
    AnalyticPlanCreate, AnalyticPlanUpdate, AnalyticPlanRead,
    AnalyticAccountCreate, AnalyticAccountUpdate, AnalyticAccountRead,
    AnalyticAccountReadBrief,
    BudgetLineCreate, BudgetLineRead,
    BudgetCreate, BudgetUpdate, BudgetRead,
)
from src.modules.accounting.schemas.bank_statement import (
    BankStatementLineCreate, BankStatementLineRead,
    BankStatementCreate, BankStatementUpdate, BankStatementRead,
    BankStatementReadBrief,
)
from src.modules.accounting.schemas.asset import (
    AssetGroupCreate, AssetGroupUpdate, AssetGroupRead,
    AssetDepreciationLineRead,
    AssetCreate, AssetUpdate, AssetRead, AssetReadBrief,
)
from src.modules.accounting.schemas.localization import (
    ChartTemplateEntry, TaxTemplateEntry,
    LocalizationPackageSummary, LocalizationPackageRead,
    LocalizationInstallRequest, LocalizationInstallResult,
    LocalizationInstallLogRead,
)

__all__ = [
    # Account
    "AccountTagCreate", "AccountTagRead",
    "AccountCreate", "AccountUpdate", "AccountRead", "AccountReadBrief", "AccountFilter",
    # Journal
    "JournalCreate", "JournalUpdate", "JournalRead", "JournalReadBrief",
    # Tax
    "TaxRepartitionLineCreate", "TaxRepartitionLineRead",
    "TaxCreate", "TaxUpdate", "TaxRead", "TaxReadBrief",
    "TaxComputeRequest", "TaxComputeResult",
    # Move
    "MoveLineCreate", "MoveLineUpdate", "MoveLineRead", "MoveLineReadBrief",
    "MoveCreate", "MoveUpdate", "MoveRead", "MoveReadBrief", "MoveFilter",
    # Payment
    "PaymentCreate", "PaymentUpdate", "PaymentRead", "PaymentReadBrief", "PaymentFilter",
    "BatchPaymentCreate", "BatchPaymentRead",
    # Payment Term & Fiscal Position
    "PaymentTermLineCreate", "PaymentTermLineRead",
    "PaymentTermCreate", "PaymentTermUpdate", "PaymentTermRead",
    "FiscalPositionTaxCreate", "FiscalPositionTaxRead",
    "FiscalPositionAccountCreate", "FiscalPositionAccountRead",
    "FiscalPositionCreate", "FiscalPositionUpdate", "FiscalPositionRead",
    # Reconciliation
    "ReconcileModelLineCreate", "ReconcileModelLineRead",
    "ReconcileModelCreate", "ReconcileModelUpdate", "ReconcileModelRead",
    "PartialReconcileRead", "FullReconcileRead",
    # Fiscal Year
    "FiscalYearCreate", "FiscalYearUpdate", "FiscalYearRead",
    # Analytic
    "AnalyticPlanCreate", "AnalyticPlanUpdate", "AnalyticPlanRead",
    "AnalyticAccountCreate", "AnalyticAccountUpdate", "AnalyticAccountRead",
    "AnalyticAccountReadBrief",
    "BudgetLineCreate", "BudgetLineRead",
    "BudgetCreate", "BudgetUpdate", "BudgetRead",
    # Bank Statement
    "BankStatementLineCreate", "BankStatementLineRead",
    "BankStatementCreate", "BankStatementUpdate", "BankStatementRead",
    "BankStatementReadBrief",
    # Asset
    "AssetGroupCreate", "AssetGroupUpdate", "AssetGroupRead",
    "AssetDepreciationLineRead",
    "AssetCreate", "AssetUpdate", "AssetRead", "AssetReadBrief",
    # Localization
    "ChartTemplateEntry", "TaxTemplateEntry",
    "LocalizationPackageSummary", "LocalizationPackageRead",
    "LocalizationInstallRequest", "LocalizationInstallResult",
    "LocalizationInstallLogRead",
]
