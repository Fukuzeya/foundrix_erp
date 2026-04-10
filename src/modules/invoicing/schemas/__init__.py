"""Invoicing module Pydantic schemas."""

from src.modules.invoicing.schemas.invoice import (
    InvoiceLineInput,
    CreateCustomerInvoice,
    CreateVendorBill,
    CreateCreditNote,
    DuplicateInvoice,
    RegisterPaymentRequest,
    InvoiceSummary,
    InvoiceAnalysis,
    AgingBucket,
    TopPartnerEntry,
    PaymentPerformance,
    RevenueTrendEntry,
    OutstandingSummary,
)
from src.modules.invoicing.schemas.incoterm import (
    IncotermCreate, IncotermRead, IncotermUpdate,
)
from src.modules.invoicing.schemas.recurring import (
    RecurringTemplateCreate, RecurringTemplateRead, RecurringTemplateUpdate,
)
from src.modules.invoicing.schemas.followup import (
    FollowUpLevelCreate, FollowUpLevelRead, FollowUpLevelUpdate,
    PartnerFollowUpRead, PartnerFollowUpUpdate, FollowUpAction,
)
from src.modules.invoicing.schemas.credit_control import (
    CreditControlCreate, CreditControlRead, CreditControlUpdate, CreditCheckResult,
)
from src.modules.invoicing.schemas.invoice_template import (
    InvoiceTemplateCreate, InvoiceTemplateRead, InvoiceTemplateUpdate,
)
from src.modules.invoicing.schemas.matching import (
    PurchaseOrderCreate, PurchaseOrderRead, PurchaseOrderUpdate,
    ReceiptCreate, ReceiptRead,
    BillMatchRead, MatchResult, MatchingSummary,
)
from src.modules.invoicing.schemas.batch_payment import (
    BatchPaymentCreate, BatchPaymentRead, BatchPaymentSummary,
    BatchPaymentLineCreate, BatchPaymentLineRead,
)
from src.modules.invoicing.schemas.einvoice import (
    EInvoiceConfigCreate, EInvoiceConfigRead, EInvoiceConfigUpdate,
    EInvoiceLogRead, EInvoiceGenerateRequest, EInvoiceGenerateResponse,
    EInvoiceStatus,
)
from src.modules.invoicing.schemas.compliance import (
    ComplianceResult, CountryRequirements, VATValidationResult,
)
from src.modules.invoicing.schemas.payment_provider import (
    PaymentProviderCreate, PaymentProviderRead, PaymentProviderUpdate,
    PaymentLinkCreate, PaymentLinkRead, PaymentLinkPublic, OnlinePaymentResult,
)
from src.modules.invoicing.schemas.vendor_import import (
    VendorBillImportCreate, VendorBillImportRead, ImportSummary,
    ParsedBillData, ParsedBillLine,
    VendorBillEmailAliasCreate, VendorBillEmailAliasRead, VendorBillEmailAliasUpdate,
)
from src.modules.invoicing.schemas.vat import VATLookupResult, PartnerSuggestion
from src.modules.invoicing.schemas.multi_company import (
    InterCompanyRuleCreate, InterCompanyRuleRead, InterCompanyRuleUpdate,
    InterCompanyTransactionRead, InterCompanySyncResult, InterCompanySummary,
)
from src.modules.invoicing.schemas.fiscal_position import (
    FiscalPositionMapping, FiscalPositionSuggestion,
    InvoiceTaxApplication, OSSInfo,
)

__all__ = [
    # Invoice core
    "InvoiceLineInput", "CreateCustomerInvoice", "CreateVendorBill",
    "CreateCreditNote", "DuplicateInvoice", "RegisterPaymentRequest",
    "InvoiceSummary", "InvoiceAnalysis",
    # Reports
    "AgingBucket", "TopPartnerEntry", "PaymentPerformance",
    "RevenueTrendEntry", "OutstandingSummary",
    # Incoterms
    "IncotermCreate", "IncotermRead", "IncotermUpdate",
    # Recurring
    "RecurringTemplateCreate", "RecurringTemplateRead", "RecurringTemplateUpdate",
    # Follow-up
    "FollowUpLevelCreate", "FollowUpLevelRead", "FollowUpLevelUpdate",
    "PartnerFollowUpRead", "PartnerFollowUpUpdate", "FollowUpAction",
    # Credit control
    "CreditControlCreate", "CreditControlRead", "CreditControlUpdate",
    "CreditCheckResult",
    # Invoice templates
    "InvoiceTemplateCreate", "InvoiceTemplateRead", "InvoiceTemplateUpdate",
    # 3-way matching
    "PurchaseOrderCreate", "PurchaseOrderRead", "PurchaseOrderUpdate",
    "ReceiptCreate", "ReceiptRead",
    "BillMatchRead", "MatchResult", "MatchingSummary",
    # Batch payments
    "BatchPaymentCreate", "BatchPaymentRead", "BatchPaymentSummary",
    "BatchPaymentLineCreate", "BatchPaymentLineRead",
    # E-invoicing
    "EInvoiceConfigCreate", "EInvoiceConfigRead", "EInvoiceConfigUpdate",
    "EInvoiceLogRead", "EInvoiceGenerateRequest", "EInvoiceGenerateResponse",
    "EInvoiceStatus",
    # Compliance
    "ComplianceResult", "CountryRequirements", "VATValidationResult",
    # Payment providers
    "PaymentProviderCreate", "PaymentProviderRead", "PaymentProviderUpdate",
    "PaymentLinkCreate", "PaymentLinkRead", "PaymentLinkPublic", "OnlinePaymentResult",
    # Vendor import
    "VendorBillImportCreate", "VendorBillImportRead", "ImportSummary",
    "ParsedBillData", "ParsedBillLine",
    "VendorBillEmailAliasCreate", "VendorBillEmailAliasRead", "VendorBillEmailAliasUpdate",
    # VAT
    "VATLookupResult", "PartnerSuggestion",
    # Multi-company
    "InterCompanyRuleCreate", "InterCompanyRuleRead", "InterCompanyRuleUpdate",
    "InterCompanyTransactionRead", "InterCompanySyncResult", "InterCompanySummary",
    # Fiscal position
    "FiscalPositionMapping", "FiscalPositionSuggestion",
    "InvoiceTaxApplication", "OSSInfo",
]
