"""Invoicing module manifest — discovered by the module registry at startup."""

from fastapi import APIRouter

from src.core.database.base import Base
from src.core.registry.module_base import ERPModule


class InvoicingModule(ERPModule):
    name = "invoicing"
    version = "2.0.0"
    depends = ["core", "contacts", "accounting"]
    description = (
        "Full-featured invoicing — customer invoices, vendor bills, credit notes, "
        "recurring invoices, payment follow-ups, credit control, incoterms, "
        "PDF generation, email sending, 3-way matching, batch payments, "
        "SEPA/check printing, e-invoicing (Peppol/UBL/Factur-X/XRechnung), "
        "online payment links, vendor bill import/OCR, VAT autocomplete, "
        "multi-company rules, fiscal position integration, compliance, reporting"
    )

    def get_router(self) -> APIRouter:
        from src.modules.invoicing.router import router
        return router

    def get_models(self) -> list[type[Base]]:
        from src.modules.invoicing.models import (
            Incoterm,
            RecurringTemplate, RecurringTemplateLine,
            FollowUpLevel, PartnerFollowUp,
            CreditControl,
            InvoiceTemplate,
            MatchingRule, PurchaseOrderReference, PurchaseOrderLine,
            ReceiptReference, ReceiptLine, BillMatch,
            InvoiceBatchPayment, BatchPaymentLine,
            EInvoiceConfig, EInvoiceLog,
            PaymentProvider, PaymentLink,
            VendorBillImport, VendorBillEmailAlias,
            InterCompanyRule, InterCompanyTransaction,
        )

        return [
            Incoterm,
            RecurringTemplate, RecurringTemplateLine,
            FollowUpLevel, PartnerFollowUp,
            CreditControl,
            InvoiceTemplate,
            MatchingRule, PurchaseOrderReference, PurchaseOrderLine,
            ReceiptReference, ReceiptLine, BillMatch,
            InvoiceBatchPayment, BatchPaymentLine,
            EInvoiceConfig, EInvoiceLog,
            PaymentProvider, PaymentLink,
            VendorBillImport, VendorBillEmailAlias,
            InterCompanyRule, InterCompanyTransaction,
        ]

    def get_permissions(self) -> list[dict]:
        return [
            # Customer Invoices
            {"codename": "invoicing.invoice.create", "description": "Create customer invoices"},
            {"codename": "invoicing.invoice.read", "description": "View invoices"},
            {"codename": "invoicing.invoice.post", "description": "Confirm, cancel, and reverse invoices"},
            {"codename": "invoicing.invoice.send", "description": "Send invoices and reminders by email"},
            {"codename": "invoicing.invoice.manage", "description": "Manage invoice fiscal positions and taxes"},
            # Vendor Bills
            {"codename": "invoicing.bill.create", "description": "Create vendor bills and import"},
            {"codename": "invoicing.bill.read", "description": "View vendor bills and imports"},
            # Payments (invoice-level)
            {"codename": "invoicing.payment.create", "description": "Register payments against invoices"},
            {"codename": "invoicing.payment.read", "description": "View batch payments and payment links"},
            {"codename": "invoicing.payment.manage", "description": "Manage batch payments, SEPA, checks, payment links"},
            # Recurring
            {"codename": "invoicing.recurring.read", "description": "View recurring invoice templates"},
            {"codename": "invoicing.recurring.manage", "description": "Manage recurring templates and generate invoices"},
            # Follow-ups
            {"codename": "invoicing.followup.read", "description": "View follow-up levels and partner follow-ups"},
            {"codename": "invoicing.followup.manage", "description": "Manage follow-up levels and process follow-ups"},
            # Credit Control
            {"codename": "invoicing.credit.read", "description": "View credit limits and check credit"},
            {"codename": "invoicing.credit.manage", "description": "Manage credit limits and holds"},
            # 3-Way Matching
            {"codename": "invoicing.matching.read", "description": "View bill matching status and exceptions"},
            {"codename": "invoicing.matching.manage", "description": "Match bills, validate, and override exceptions"},
            # E-Invoicing
            {"codename": "invoicing.einvoice.read", "description": "View e-invoice status and logs"},
            {"codename": "invoicing.einvoice.manage", "description": "Generate and send e-invoices"},
            # Multi-Company
            {"codename": "invoicing.multicompany.read", "description": "View inter-company rules and transactions"},
            {"codename": "invoicing.multicompany.manage", "description": "Manage inter-company rules and mirror invoices"},
            # Reports
            {"codename": "invoicing.report.read", "description": "View invoice analysis and reports"},
            # Config (incoterms, templates, providers, e-invoice configs)
            {"codename": "invoicing.config.read", "description": "View invoicing configuration"},
            {"codename": "invoicing.config.manage", "description": "Manage invoicing configuration"},
        ]

    def on_startup(self) -> None:
        pass
