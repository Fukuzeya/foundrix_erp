"""Invoicing module API router.

All endpoints delegate to service layer — zero business logic in routes.

Endpoints organized by domain:
- Customer Invoices: /invoices
- Vendor Bills: /vendor-bills
- Credit Notes: /credit-notes
- Register Payment: /invoices/register-payment
- Recurring Templates: /recurring-templates
- Follow-Up Levels: /followup-levels
- Partner Follow-Up: /partner-followups
- Credit Control: /credit-controls
- Incoterms: /incoterms
- PDF & Email: /invoices/{id}/pdf, /invoices/{id}/send-email, etc.
- Invoice Templates: /invoice-templates
- Reporting & Analysis: /reports/*
- Sequence Management: /sequences/*
- Multi-Currency: /currencies, /invoices/{id}/convert, etc.
- 3-Way Matching: /matching/*
- Batch Payments: /batch-payments/*
- SEPA & Check Printing: /batch-payments/{id}/sepa-*, /sepa/*
- E-Invoicing: /einvoice/*
- Compliance: /compliance/*
- Online Payments: /payment-links/*, /payment-providers/*
- Vendor Bill Import: /vendor-imports/*
- VAT Autocomplete: /vat/*
- Multi-Company: /multi-company/*
- Fiscal Position: /fiscal-position/*
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_tenant_session
from src.core.auth.models import User
from src.core.auth.permissions import require_permissions
from src.modules.invoicing.schemas.invoice import (
    CreateCustomerInvoice,
    CreateVendorBill,
    CreateCreditNote,
    DuplicateInvoice,
    RegisterPaymentRequest,
    InvoiceSummary,
)
from src.modules.invoicing.schemas.recurring import (
    RecurringTemplateCreate,
    RecurringTemplateRead,
    RecurringTemplateUpdate,
)
from src.modules.invoicing.schemas.followup import (
    FollowUpLevelCreate,
    FollowUpLevelRead,
    FollowUpLevelUpdate,
    PartnerFollowUpRead,
    PartnerFollowUpUpdate,
    FollowUpAction,
)
from src.modules.invoicing.schemas.credit_control import (
    CreditControlCreate,
    CreditControlRead,
    CreditControlUpdate,
    CreditCheckResult,
)
from src.modules.invoicing.schemas.incoterm import (
    IncotermCreate,
    IncotermRead,
    IncotermUpdate,
)

router = APIRouter(tags=["invoicing"])


# ══════════════════════════════════════════════════════════════════════
# CUSTOMER INVOICES
# ══════════════════════════════════════════════════════════════════════


@router.post("/invoices", response_model=InvoiceSummary, status_code=201)
async def create_customer_invoice(
    data: CreateCustomerInvoice,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.create")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.invoice_service import InvoiceService
    svc = InvoiceService(db)
    move = await svc.create_customer_invoice(data)
    await db.commit()
    await db.refresh(move)
    return move


@router.post("/invoices/{invoice_id}/confirm", response_model=InvoiceSummary)
async def confirm_invoice(
    invoice_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.post")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.invoice_service import InvoiceService
    svc = InvoiceService(db)
    move = await svc.confirm_invoice(invoice_id)
    await db.commit()
    await db.refresh(move)
    return move


@router.post("/invoices/{invoice_id}/cancel", response_model=InvoiceSummary)
async def cancel_invoice(
    invoice_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.post")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.invoice_service import InvoiceService
    svc = InvoiceService(db)
    move = await svc.cancel_invoice(invoice_id)
    await db.commit()
    await db.refresh(move)
    return move


@router.post("/invoices/{invoice_id}/reset-to-draft", response_model=InvoiceSummary)
async def reset_invoice_to_draft(
    invoice_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.post")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.invoice_service import InvoiceService
    svc = InvoiceService(db)
    move = await svc.reset_to_draft(invoice_id)
    await db.commit()
    await db.refresh(move)
    return move


@router.post("/invoices/duplicate", response_model=InvoiceSummary, status_code=201)
async def duplicate_invoice(
    data: DuplicateInvoice,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.create")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.invoice_service import InvoiceService
    svc = InvoiceService(db)
    move = await svc.duplicate_invoice(data)
    await db.commit()
    await db.refresh(move)
    return move


# ══════════════════════════════════════════════════════════════════════
# VENDOR BILLS
# ══════════════════════════════════════════════════════════════════════


@router.post("/vendor-bills", response_model=InvoiceSummary, status_code=201)
async def create_vendor_bill(
    data: CreateVendorBill,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.bill.create")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.invoice_service import InvoiceService
    svc = InvoiceService(db)
    move = await svc.create_vendor_bill(data)
    await db.commit()
    await db.refresh(move)
    return move


# ══════════════════════════════════════════════════════════════════════
# CREDIT NOTES
# ══════════════════════════════════════════════════════════════════════


@router.post("/credit-notes", response_model=InvoiceSummary, status_code=201)
async def create_credit_note(
    data: CreateCreditNote,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.post")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.invoice_service import InvoiceService
    svc = InvoiceService(db)
    move = await svc.create_credit_note(data)
    await db.commit()
    await db.refresh(move)
    return move


# ══════════════════════════════════════════════════════════════════════
# REGISTER PAYMENT
# ══════════════════════════════════════════════════════════════════════


@router.post("/invoices/register-payment")
async def register_payment(
    data: RegisterPaymentRequest,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.create")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.invoice_service import InvoiceService
    svc = InvoiceService(db)
    result = await svc.register_payment(data)
    await db.commit()
    return {"status": "ok", "payment_id": str(result.id)}


# ══════════════════════════════════════════════════════════════════════
# RECURRING TEMPLATES
# ══════════════════════════════════════════════════════════════════════


@router.get("/recurring-templates", response_model=list[RecurringTemplateRead])
async def list_recurring_templates(
    active_only: bool = Query(True),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.recurring.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.recurring_service import RecurringInvoiceService
    svc = RecurringInvoiceService(db)
    return await svc.list_templates(active_only=active_only)


@router.post("/recurring-templates", response_model=RecurringTemplateRead, status_code=201)
async def create_recurring_template(
    data: RecurringTemplateCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.recurring.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.recurring_service import RecurringInvoiceService
    svc = RecurringInvoiceService(db)
    template = await svc.create_template(data)
    await db.commit()
    await db.refresh(template)
    return template


@router.get("/recurring-templates/{template_id}", response_model=RecurringTemplateRead)
async def get_recurring_template(
    template_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.recurring.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.recurring_service import RecurringInvoiceService
    svc = RecurringInvoiceService(db)
    return await svc.get_template(template_id)


@router.patch("/recurring-templates/{template_id}", response_model=RecurringTemplateRead)
async def update_recurring_template(
    template_id: uuid.UUID,
    data: RecurringTemplateUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.recurring.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.recurring_service import RecurringInvoiceService
    svc = RecurringInvoiceService(db)
    template = await svc.update_template(template_id, data)
    await db.commit()
    await db.refresh(template)
    return template


@router.post("/recurring-templates/{template_id}/deactivate", response_model=RecurringTemplateRead)
async def deactivate_recurring_template(
    template_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.recurring.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.recurring_service import RecurringInvoiceService
    svc = RecurringInvoiceService(db)
    template = await svc.deactivate_template(template_id)
    await db.commit()
    return template


@router.post("/recurring-templates/generate")
async def generate_recurring_invoices(
    as_of: date | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.recurring.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.recurring_service import RecurringInvoiceService
    svc = RecurringInvoiceService(db)
    results = await svc.generate_due_invoices(as_of)
    await db.commit()
    return {"generated": results, "count": len(results)}


# ══════════════════════════════════════════════════════════════════════
# FOLLOW-UP LEVELS
# ══════════════════════════════════════════════════════════════════════


@router.get("/followup-levels", response_model=list[FollowUpLevelRead])
async def list_followup_levels(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.followup.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.followup_service import FollowUpService
    svc = FollowUpService(db)
    return await svc.list_levels()


@router.post("/followup-levels", response_model=FollowUpLevelRead, status_code=201)
async def create_followup_level(
    data: FollowUpLevelCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.followup.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.followup_service import FollowUpService
    svc = FollowUpService(db)
    level = await svc.create_level(data)
    await db.commit()
    return level


@router.patch("/followup-levels/{level_id}", response_model=FollowUpLevelRead)
async def update_followup_level(
    level_id: uuid.UUID,
    data: FollowUpLevelUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.followup.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.followup_service import FollowUpService
    svc = FollowUpService(db)
    level = await svc.update_level(level_id, data)
    await db.commit()
    return level


# ══════════════════════════════════════════════════════════════════════
# PARTNER FOLLOW-UPS
# ══════════════════════════════════════════════════════════════════════


@router.get("/partner-followups/{partner_id}", response_model=PartnerFollowUpRead)
async def get_partner_followup(
    partner_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.followup.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.followup_service import FollowUpService
    svc = FollowUpService(db)
    return await svc.get_partner_followup(partner_id)


@router.patch("/partner-followups/{partner_id}", response_model=PartnerFollowUpRead)
async def update_partner_followup(
    partner_id: uuid.UUID,
    data: PartnerFollowUpUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.followup.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.followup_service import FollowUpService
    svc = FollowUpService(db)
    followup = await svc.update_partner_followup(partner_id, data)
    await db.commit()
    return followup


@router.post("/partner-followups/process", response_model=list[FollowUpAction])
async def process_followups(
    as_of: date | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.followup.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.followup_service import FollowUpService
    svc = FollowUpService(db)
    results = await svc.process_followups(as_of)
    await db.commit()
    return results


# ══════════════════════════════════════════════════════════════════════
# CREDIT CONTROL
# ══════════════════════════════════════════════════════════════════════


@router.get("/credit-controls/on-hold", response_model=list[CreditControlRead])
async def list_on_hold_partners(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.credit.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.credit_control_service import CreditControlService
    svc = CreditControlService(db)
    return await svc.list_on_hold_partners()


@router.get("/credit-controls/{partner_id}", response_model=CreditControlRead)
async def get_credit_control(
    partner_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.credit.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.credit_control_service import CreditControlService
    svc = CreditControlService(db)
    return await svc.get_credit_control(partner_id)


@router.post("/credit-controls", response_model=CreditControlRead, status_code=201)
async def create_credit_control(
    data: CreditControlCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.credit.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.credit_control_service import CreditControlService
    svc = CreditControlService(db)
    control = await svc.create_credit_control(data)
    await db.commit()
    return control


@router.patch("/credit-controls/{partner_id}", response_model=CreditControlRead)
async def update_credit_control(
    partner_id: uuid.UUID,
    data: CreditControlUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.credit.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.credit_control_service import CreditControlService
    svc = CreditControlService(db)
    control = await svc.update_credit_control(partner_id, data)
    await db.commit()
    return control


@router.post("/credit-controls/{partner_id}/check", response_model=CreditCheckResult)
async def check_credit(
    partner_id: uuid.UUID,
    additional_amount: float = Query(default=0.0, ge=0),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.credit.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.credit_control_service import CreditControlService
    svc = CreditControlService(db)
    return await svc.check_credit(partner_id, additional_amount=additional_amount)


# ══════════════════════════════════════════════════════════════════════
# INCOTERMS
# ══════════════════════════════════════════════════════════════════════


@router.get("/incoterms", response_model=list[IncotermRead])
async def list_incoterms(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.incoterm_service import IncotermService
    svc = IncotermService(db)
    return await svc.list_active()


@router.post("/incoterms", response_model=IncotermRead, status_code=201)
async def create_incoterm(
    data: IncotermCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.incoterm_service import IncotermService
    svc = IncotermService(db)
    incoterm = await svc.create(data)
    await db.commit()
    return incoterm


@router.get("/incoterms/{incoterm_id}", response_model=IncotermRead)
async def get_incoterm(
    incoterm_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.incoterm_service import IncotermService
    svc = IncotermService(db)
    return await svc.get(incoterm_id)


@router.patch("/incoterms/{incoterm_id}", response_model=IncotermRead)
async def update_incoterm(
    incoterm_id: uuid.UUID,
    data: IncotermUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.incoterm_service import IncotermService
    svc = IncotermService(db)
    incoterm = await svc.update(incoterm_id, data)
    await db.commit()
    return incoterm


# ══════════════════════════════════════════════════════════════════════
# PDF & EMAIL
# ══════════════════════════════════════════════════════════════════════


@router.post("/invoices/batch-pdf")
async def generate_batch_pdf(
    invoice_ids: list[uuid.UUID],
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    import io
    from starlette.responses import StreamingResponse
    from src.modules.invoicing.services.pdf_service import InvoicePDFService
    svc = InvoicePDFService(db)
    pdf_bytes = await svc.generate_batch_pdf(invoice_ids)
    return StreamingResponse(
        content=io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=batch_invoices.pdf"},
    )


@router.post("/invoices/{invoice_id}/pdf")
async def generate_invoice_pdf(
    invoice_id: uuid.UUID,
    template_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    import io
    from starlette.responses import StreamingResponse
    from src.modules.invoicing.services.pdf_service import InvoicePDFService
    svc = InvoicePDFService(db)
    pdf_bytes = await svc.generate_pdf(invoice_id, template_id=template_id)
    return StreamingResponse(
        content=io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=invoice_{invoice_id}.pdf"},
    )


@router.post("/invoices/{invoice_id}/send-email")
async def send_invoice_email(
    invoice_id: uuid.UUID,
    recipient_email: str,
    cc: str | None = None,
    subject: str | None = None,
    body_text: str | None = None,
    attach_pdf: bool = True,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.send")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.email_service import InvoiceEmailService
    svc = InvoiceEmailService(db)
    result = await svc.send_invoice_email(
        invoice_id,
        recipient_email=recipient_email,
        cc=cc,
        subject=subject,
        body_text=body_text,
        attach_pdf=attach_pdf,
    )
    return result


@router.post("/invoices/{invoice_id}/send-reminder")
async def send_payment_reminder(
    invoice_id: uuid.UUID,
    recipient_email: str,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.send")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.email_service import InvoiceEmailService
    svc = InvoiceEmailService(db)
    result = await svc.send_payment_reminder(invoice_id, recipient_email=recipient_email)
    return result


# ══════════════════════════════════════════════════════════════════════
# INVOICE TEMPLATES
# ══════════════════════════════════════════════════════════════════════


@router.get("/invoice-templates")
async def list_templates(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.invoice_template import InvoiceTemplateRead
    from src.modules.invoicing.services.invoice_template_service import InvoiceTemplateService
    svc = InvoiceTemplateService(db)
    return await svc.list_templates()


@router.post("/invoice-templates", status_code=201)
async def create_template(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.invoice_template import (
        InvoiceTemplateCreate,
        InvoiceTemplateRead,
    )
    from src.modules.invoicing.services.invoice_template_service import InvoiceTemplateService
    payload = InvoiceTemplateCreate(**data)
    svc = InvoiceTemplateService(db)
    template = await svc.create_template(payload)
    await db.commit()
    await db.refresh(template)
    return template


@router.patch("/invoice-templates/{template_id}")
async def update_template(
    template_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.invoice_template import (
        InvoiceTemplateUpdate,
        InvoiceTemplateRead,
    )
    from src.modules.invoicing.services.invoice_template_service import InvoiceTemplateService
    payload = InvoiceTemplateUpdate(**data)
    svc = InvoiceTemplateService(db)
    template = await svc.update_template(template_id, payload)
    await db.commit()
    await db.refresh(template)
    return template


# ══════════════════════════════════════════════════════════════════════
# REPORTING & ANALYSIS
# ══════════════════════════════════════════════════════════════════════


@router.get("/reports/invoice-analysis")
async def get_invoice_analysis(
    date_from: date,
    date_to: date,
    move_type: str | None = Query(None),
    partner_id: uuid.UUID | None = Query(None),
    group_by: str = Query("month"),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.invoice import InvoiceAnalysis
    from src.modules.invoicing.services.reporting_service import InvoiceReportingService
    svc = InvoiceReportingService(db)
    return await svc.get_invoice_analysis(
        date_from=date_from,
        date_to=date_to,
        move_type=move_type,
        partner_id=partner_id,
        group_by=group_by,
    )


@router.get("/reports/aging")
async def get_aging_report(
    as_of: date | None = Query(None),
    partner_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.invoice import AgingBucket
    from src.modules.invoicing.services.reporting_service import InvoiceReportingService
    svc = InvoiceReportingService(db)
    return await svc.get_aging_report(as_of=as_of, partner_id=partner_id)


@router.get("/reports/top-customers")
async def get_top_customers(
    limit: int = Query(10),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.invoice import TopPartnerEntry
    from src.modules.invoicing.services.reporting_service import InvoiceReportingService
    svc = InvoiceReportingService(db)
    return await svc.get_top_customers(limit=limit, date_from=date_from, date_to=date_to)


@router.get("/reports/top-vendors")
async def get_top_vendors(
    limit: int = Query(10),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.invoice import TopPartnerEntry
    from src.modules.invoicing.services.reporting_service import InvoiceReportingService
    svc = InvoiceReportingService(db)
    return await svc.get_top_vendors(limit=limit, date_from=date_from, date_to=date_to)


@router.get("/reports/payment-performance")
async def get_payment_performance(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.invoice import PaymentPerformance
    from src.modules.invoicing.services.reporting_service import InvoiceReportingService
    svc = InvoiceReportingService(db)
    return await svc.get_payment_performance(date_from=date_from, date_to=date_to)


@router.get("/reports/revenue-trend")
async def get_revenue_trend(
    months: int = Query(12),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.invoice import RevenueTrendEntry
    from src.modules.invoicing.services.reporting_service import InvoiceReportingService
    svc = InvoiceReportingService(db)
    return await svc.get_revenue_trend(months=months)


@router.get("/reports/outstanding-summary")
async def get_outstanding_summary(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.invoice import OutstandingSummary
    from src.modules.invoicing.services.reporting_service import InvoiceReportingService
    svc = InvoiceReportingService(db)
    return await svc.get_outstanding_summary()


# ══════════════════════════════════════════════════════════════════════
# SEQUENCE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════


@router.get("/sequences/{journal_id}/info")
async def get_sequence_info(
    journal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.sequence_service import SequenceService
    svc = SequenceService(db)
    return await svc.get_sequence_info(journal_id)


@router.get("/sequences/{journal_id}/gaps")
async def detect_gaps(
    journal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.sequence_service import SequenceService
    svc = SequenceService(db)
    return await svc.detect_gaps(journal_id)


@router.post("/sequences/{journal_id}/validate")
async def validate_sequence_integrity(
    journal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.sequence_service import SequenceService
    svc = SequenceService(db)
    return await svc.validate_sequence_integrity(journal_id)


@router.post("/sequences/{journal_id}/resequence")
async def resequence_drafts(
    journal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.sequence_service import SequenceService
    svc = SequenceService(db)
    result = await svc.resequence_drafts(journal_id)
    await db.commit()
    return result


# ══════════════════════════════════════════════════════════════════════
# MULTI-CURRENCY
# ══════════════════════════════════════════════════════════════════════


@router.get("/currencies")
async def get_available_currencies(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.currency_integration_service import InvoiceCurrencyService
    svc = InvoiceCurrencyService(db)
    return await svc.get_available_currencies()


@router.get("/currencies/rate")
async def get_rate_for_invoice(
    currency_code: str,
    invoice_date: date,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.currency_integration_service import InvoiceCurrencyService
    svc = InvoiceCurrencyService(db)
    return await svc.get_rate_for_invoice(currency_code=currency_code, invoice_date=invoice_date)


@router.post("/invoices/{invoice_id}/convert")
async def convert_invoice_amounts(
    invoice_id: uuid.UUID,
    target_currency: str = Query(...),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.currency_integration_service import InvoiceCurrencyService
    svc = InvoiceCurrencyService(db)
    return await svc.convert_invoice_amounts(invoice_id, target_currency=target_currency)


@router.get("/invoices/{invoice_id}/exchange-difference")
async def compute_exchange_difference(
    invoice_id: uuid.UUID,
    settlement_date: date | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.currency_integration_service import InvoiceCurrencyService
    svc = InvoiceCurrencyService(db)
    return await svc.compute_exchange_difference(invoice_id, settlement_date=settlement_date)


# ══════════════════════════════════════════════════════════════════════
# 3-WAY MATCHING
# ══════════════════════════════════════════════════════════════════════


@router.post("/matching/match-bill")
async def match_bill(
    bill_id: uuid.UUID,
    po_id: uuid.UUID | None = None,
    receipt_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.matching.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.matching_service import ThreeWayMatchingService
    svc = ThreeWayMatchingService(db)
    result = await svc.match_bill(bill_id=bill_id, po_id=po_id, receipt_id=receipt_id)
    await db.commit()
    return result


@router.post("/matching/auto-match/{bill_id}")
async def auto_match_bill(
    bill_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.matching.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.matching_service import ThreeWayMatchingService
    svc = ThreeWayMatchingService(db)
    result = await svc.auto_match_bill(bill_id)
    await db.commit()
    return result


@router.post("/matching/{match_id}/validate")
async def validate_match(
    match_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.matching.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.matching_service import ThreeWayMatchingService
    svc = ThreeWayMatchingService(db)
    result = await svc.validate_match(match_id)
    await db.commit()
    return result


@router.post("/matching/{match_id}/override")
async def override_exception(
    match_id: uuid.UUID,
    reason: str,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.matching.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.matching_service import ThreeWayMatchingService
    svc = ThreeWayMatchingService(db)
    result = await svc.override_exception(match_id, reason=reason, user_id=user.id)
    await db.commit()
    return result


@router.get("/matching/unmatched")
async def get_unmatched_bills(
    partner_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.matching.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.matching_service import ThreeWayMatchingService
    svc = ThreeWayMatchingService(db)
    return await svc.get_unmatched_bills(partner_id=partner_id)


@router.get("/matching/exceptions")
async def get_matching_exceptions(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.matching.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.matching_service import ThreeWayMatchingService
    svc = ThreeWayMatchingService(db)
    return await svc.get_matching_exceptions()


@router.get("/matching/summary")
async def get_matching_summary(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.matching.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.matching import MatchingSummary
    from src.modules.invoicing.services.matching_service import ThreeWayMatchingService
    svc = ThreeWayMatchingService(db)
    return await svc.get_matching_summary()


@router.get("/matching/bill/{bill_id}")
async def get_match_status(
    bill_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.matching.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.matching import BillMatchRead
    from src.modules.invoicing.services.matching_service import ThreeWayMatchingService
    svc = ThreeWayMatchingService(db)
    return await svc.get_match_status(bill_id)


# ══════════════════════════════════════════════════════════════════════
# BATCH PAYMENTS
# ══════════════════════════════════════════════════════════════════════


@router.get("/batch-payments")
async def list_batches(
    state: str | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.batch_payment import BatchPaymentSummary
    from src.modules.invoicing.services.batch_payment_service import BatchPaymentService
    svc = BatchPaymentService(db)
    return await svc.list_batches(state=state)


@router.post("/batch-payments", status_code=201)
async def create_batch(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.batch_payment import BatchPaymentCreate, BatchPaymentRead
    from src.modules.invoicing.services.batch_payment_service import BatchPaymentService
    payload = BatchPaymentCreate(**data)
    svc = BatchPaymentService(db)
    batch = await svc.create_batch(payload)
    await db.commit()
    await db.refresh(batch)
    return batch


@router.get("/batch-payments/{batch_id}")
async def get_batch(
    batch_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.batch_payment import BatchPaymentRead
    from src.modules.invoicing.services.batch_payment_service import BatchPaymentService
    svc = BatchPaymentService(db)
    return await svc.get_batch(batch_id)


@router.post("/batch-payments/{batch_id}/lines")
async def add_line(
    batch_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.batch_payment import BatchPaymentLineCreate
    from src.modules.invoicing.services.batch_payment_service import BatchPaymentService
    payload = BatchPaymentLineCreate(**data)
    svc = BatchPaymentService(db)
    line = await svc.add_line(batch_id, payload)
    await db.commit()
    await db.refresh(line)
    return line


@router.post("/batch-payments/{batch_id}/add-invoices")
async def add_invoices_to_batch(
    batch_id: uuid.UUID,
    invoice_ids: list[uuid.UUID],
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.batch_payment_service import BatchPaymentService
    svc = BatchPaymentService(db)
    result = await svc.add_invoices_to_batch(batch_id, invoice_ids)
    await db.commit()
    return result


@router.delete("/batch-payments/{batch_id}/lines/{line_id}")
async def remove_line(
    batch_id: uuid.UUID,
    line_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.batch_payment_service import BatchPaymentService
    svc = BatchPaymentService(db)
    await svc.remove_line(batch_id, line_id)
    await db.commit()
    return {"status": "ok"}


@router.post("/batch-payments/{batch_id}/confirm")
async def confirm_batch(
    batch_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.batch_payment_service import BatchPaymentService
    svc = BatchPaymentService(db)
    result = await svc.confirm_batch(batch_id)
    await db.commit()
    return result


@router.post("/batch-payments/{batch_id}/execute")
async def execute_batch(
    batch_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.batch_payment_service import BatchPaymentService
    svc = BatchPaymentService(db)
    result = await svc.execute_batch(batch_id)
    await db.commit()
    return result


@router.post("/batch-payments/{batch_id}/cancel")
async def cancel_batch(
    batch_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.batch_payment_service import BatchPaymentService
    svc = BatchPaymentService(db)
    result = await svc.cancel_batch(batch_id)
    await db.commit()
    return result


# ══════════════════════════════════════════════════════════════════════
# SEPA & CHECK PRINTING
# ══════════════════════════════════════════════════════════════════════


@router.post("/batch-payments/{batch_id}/sepa-credit")
async def generate_sepa_credit_transfer(
    batch_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    import io
    from starlette.responses import StreamingResponse
    from src.modules.invoicing.services.sepa_service import SEPAService
    svc = SEPAService(db)
    xml_bytes = await svc.generate_sepa_credit_transfer(batch_id)
    return StreamingResponse(
        content=io.BytesIO(xml_bytes),
        media_type="application/xml",
        headers={"Content-Disposition": f"attachment; filename=sepa_credit_{batch_id}.xml"},
    )


@router.post("/batch-payments/{batch_id}/sepa-debit")
async def generate_sepa_direct_debit(
    batch_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    import io
    from starlette.responses import StreamingResponse
    from src.modules.invoicing.services.sepa_service import SEPAService
    svc = SEPAService(db)
    xml_bytes = await svc.generate_sepa_direct_debit(batch_id)
    return StreamingResponse(
        content=io.BytesIO(xml_bytes),
        media_type="application/xml",
        headers={"Content-Disposition": f"attachment; filename=sepa_debit_{batch_id}.xml"},
    )


@router.post("/batch-payments/{batch_id}/checks")
async def generate_check_pdf(
    batch_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    import io
    from starlette.responses import StreamingResponse
    from src.modules.invoicing.services.check_service import CheckPrintService
    svc = CheckPrintService(db)
    pdf_bytes = await svc.generate_check_pdf(batch_id)
    return StreamingResponse(
        content=io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=checks_{batch_id}.pdf"},
    )


@router.post("/sepa/validate-iban")
async def validate_iban(
    iban: str,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.sepa_service import SEPAService
    svc = SEPAService(db)
    return await svc.validate_iban(iban)


@router.post("/sepa/validate-bic")
async def validate_bic(
    bic: str,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.sepa_service import SEPAService
    svc = SEPAService(db)
    return await svc.validate_bic(bic)


# ══════════════════════════════════════════════════════════════════════
# E-INVOICING
# ══════════════════════════════════════════════════════════════════════


@router.post("/einvoice/generate")
async def generate_einvoice(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.einvoice.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.einvoice import (
        EInvoiceGenerateRequest,
        EInvoiceGenerateResponse,
    )
    from src.modules.invoicing.services.einvoice_service import EInvoiceService
    payload = EInvoiceGenerateRequest(**data)
    svc = EInvoiceService(db)
    result = await svc.generate(payload)
    await db.commit()
    return result


@router.get("/einvoice/configs")
async def list_einvoice_configs(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.einvoice import EInvoiceConfigRead
    from src.modules.invoicing.services.einvoice_service import EInvoiceService
    svc = EInvoiceService(db)
    return await svc.list_configs()


@router.post("/einvoice/configs", status_code=201)
async def create_einvoice_config(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.einvoice import EInvoiceConfigCreate, EInvoiceConfigRead
    from src.modules.invoicing.services.einvoice_service import EInvoiceService
    payload = EInvoiceConfigCreate(**data)
    svc = EInvoiceService(db)
    config = await svc.create_config(payload)
    await db.commit()
    await db.refresh(config)
    return config


@router.patch("/einvoice/configs/{config_id}")
async def update_einvoice_config(
    config_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.einvoice import EInvoiceConfigUpdate, EInvoiceConfigRead
    from src.modules.invoicing.services.einvoice_service import EInvoiceService
    payload = EInvoiceConfigUpdate(**data)
    svc = EInvoiceService(db)
    config = await svc.update_config(config_id, payload)
    await db.commit()
    await db.refresh(config)
    return config


@router.post("/einvoice/{move_id}/send-peppol")
async def send_to_peppol(
    move_id: uuid.UUID,
    config_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.einvoice.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.einvoice_service import EInvoiceService
    svc = EInvoiceService(db)
    result = await svc.send_to_peppol(move_id, config_id=config_id)
    await db.commit()
    return result


@router.get("/einvoice/{move_id}/status")
async def get_invoice_einvoice_status(
    move_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.einvoice.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.einvoice import EInvoiceLogRead
    from src.modules.invoicing.services.einvoice_service import EInvoiceService
    svc = EInvoiceService(db)
    return await svc.get_invoice_einvoice_status(move_id)


# ══════════════════════════════════════════════════════════════════════
# COMPLIANCE
# ══════════════════════════════════════════════════════════════════════


@router.post("/compliance/{move_id}/validate")
async def validate_invoice_compliance(
    move_id: uuid.UUID,
    country_code: str = Query(...),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.compliance import ComplianceResult
    from src.modules.invoicing.services.compliance_service import InvoiceComplianceService
    svc = InvoiceComplianceService(db)
    return await svc.validate_invoice_compliance(move_id, country_code=country_code)


@router.get("/compliance/requirements/{country_code}")
async def get_country_requirements(
    country_code: str,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.compliance import CountryRequirements
    from src.modules.invoicing.services.compliance_service import InvoiceComplianceService
    svc = InvoiceComplianceService(db)
    return await svc.get_country_requirements(country_code)


@router.post("/compliance/structured-communication")
async def generate_structured_communication(
    country_code: str = Query(...),
    invoice_number: str = Query(...),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.compliance_service import InvoiceComplianceService
    svc = InvoiceComplianceService(db)
    return await svc.generate_structured_communication(
        country_code=country_code, invoice_number=invoice_number,
    )


@router.post("/compliance/validate-vat")
async def validate_vat_number(
    vat_number: str = Query(...),
    country_code: str | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.compliance_service import InvoiceComplianceService
    svc = InvoiceComplianceService(db)
    return await svc.validate_vat_number(vat_number=vat_number, country_code=country_code)


# ══════════════════════════════════════════════════════════════════════
# ONLINE PAYMENTS
# ══════════════════════════════════════════════════════════════════════


@router.post("/payment-links")
async def create_payment_link(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.payment_provider import (
        PaymentLinkCreate,
        OnlinePaymentResult,
    )
    from src.modules.invoicing.services.online_payment_service import OnlinePaymentService
    payload = PaymentLinkCreate(**data)
    svc = OnlinePaymentService(db)
    result = await svc.create_payment_link(payload)
    await db.commit()
    return result


@router.post("/payment-links/expire")
async def expire_old_links(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.online_payment_service import OnlinePaymentService
    svc = OnlinePaymentService(db)
    result = await svc.expire_old_links()
    await db.commit()
    return result


@router.get("/payment-links/invoice/{invoice_id}")
async def list_links_for_invoice(
    invoice_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.payment_provider import PaymentLinkRead
    from src.modules.invoicing.services.online_payment_service import OnlinePaymentService
    svc = OnlinePaymentService(db)
    return await svc.list_links_for_invoice(invoice_id)


@router.get("/payment-links/{token}/public")
async def get_payment_link_public(
    token: str,
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.payment_provider import PaymentLinkPublic
    from src.modules.invoicing.services.online_payment_service import OnlinePaymentService
    svc = OnlinePaymentService(db)
    return await svc.get_payment_link_public(token)


@router.post("/payment-links/{token}/callback")
async def process_payment_callback(
    token: str,
    external_payment_id: str,
    status: str,
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.online_payment_service import OnlinePaymentService
    svc = OnlinePaymentService(db)
    result = await svc.process_payment_callback(
        token, external_payment_id=external_payment_id, status=status,
    )
    await db.commit()
    return result


@router.delete("/payment-links/{link_id}")
async def cancel_link(
    link_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.payment.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.online_payment_service import OnlinePaymentService
    svc = OnlinePaymentService(db)
    await svc.cancel_link(link_id)
    await db.commit()
    return {"status": "ok"}


@router.get("/payment-providers")
async def list_providers(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.payment_provider import PaymentProviderRead
    from src.modules.invoicing.services.online_payment_service import OnlinePaymentService
    svc = OnlinePaymentService(db)
    return await svc.list_providers()


@router.post("/payment-providers", status_code=201)
async def create_provider(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.payment_provider import (
        PaymentProviderCreate,
        PaymentProviderRead,
    )
    from src.modules.invoicing.services.online_payment_service import OnlinePaymentService
    payload = PaymentProviderCreate(**data)
    svc = OnlinePaymentService(db)
    provider = await svc.create_provider(payload)
    await db.commit()
    await db.refresh(provider)
    return provider


@router.patch("/payment-providers/{provider_id}")
async def update_provider(
    provider_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.payment_provider import (
        PaymentProviderUpdate,
        PaymentProviderRead,
    )
    from src.modules.invoicing.services.online_payment_service import OnlinePaymentService
    payload = PaymentProviderUpdate(**data)
    svc = OnlinePaymentService(db)
    provider = await svc.update_provider(provider_id, payload)
    await db.commit()
    await db.refresh(provider)
    return provider


# ══════════════════════════════════════════════════════════════════════
# VENDOR BILL IMPORT
# ══════════════════════════════════════════════════════════════════════


@router.post("/vendor-imports/upload")
async def import_from_upload(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.bill.create")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.vendor_import_service import VendorBillImportService
    svc = VendorBillImportService(db)
    result = await svc.import_from_upload(file)
    await db.commit()
    return result


@router.post("/vendor-imports/{import_id}/parse")
async def parse_bill_data(
    import_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.bill.create")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.vendor_import_service import VendorBillImportService
    svc = VendorBillImportService(db)
    result = await svc.parse_bill_data(import_id)
    await db.commit()
    return result


@router.post("/vendor-imports/{import_id}/create-bill")
async def create_bill_from_import(
    import_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.bill.create")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.vendor_import_service import VendorBillImportService
    svc = VendorBillImportService(db)
    result = await svc.create_bill_from_import(import_id)
    await db.commit()
    return result


@router.get("/vendor-imports/summary")
async def get_import_summary(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.bill.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.vendor_import import ImportSummary
    from src.modules.invoicing.services.vendor_import_service import VendorBillImportService
    svc = VendorBillImportService(db)
    return await svc.get_import_summary()


@router.get("/vendor-imports/email-aliases")
async def list_email_aliases(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.vendor_import_service import VendorBillImportService
    svc = VendorBillImportService(db)
    return await svc.list_email_aliases()


@router.post("/vendor-imports/email-aliases")
async def create_email_alias(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.vendor_import import VendorBillEmailAliasCreate
    from src.modules.invoicing.services.vendor_import_service import VendorBillImportService
    payload = VendorBillEmailAliasCreate(**data)
    svc = VendorBillImportService(db)
    alias = await svc.create_email_alias(payload)
    await db.commit()
    await db.refresh(alias)
    return alias


@router.patch("/vendor-imports/email-aliases/{alias_id}")
async def update_email_alias(
    alias_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.vendor_import import VendorBillEmailAliasUpdate
    from src.modules.invoicing.services.vendor_import_service import VendorBillImportService
    payload = VendorBillEmailAliasUpdate(**data)
    svc = VendorBillImportService(db)
    alias = await svc.update_email_alias(alias_id, payload)
    await db.commit()
    await db.refresh(alias)
    return alias


@router.get("/vendor-imports", response_model=list)
async def list_imports(
    status: str | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.bill.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.vendor_import import VendorBillImportRead
    from src.modules.invoicing.services.vendor_import_service import VendorBillImportService
    svc = VendorBillImportService(db)
    return await svc.list_imports(status=status)


@router.get("/vendor-imports/{import_id}")
async def get_import(
    import_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.bill.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.vendor_import import VendorBillImportRead
    from src.modules.invoicing.services.vendor_import_service import VendorBillImportService
    svc = VendorBillImportService(db)
    return await svc.get_import(import_id)


# ══════════════════════════════════════════════════════════════════════
# VAT AUTOCOMPLETE
# ══════════════════════════════════════════════════════════════════════


@router.get("/vat/lookup")
async def lookup_vat(
    vat_number: str = Query(...),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.vat import VATLookupResult
    from src.modules.invoicing.services.vat_service import VATAutocompleteService
    svc = VATAutocompleteService(db)
    return await svc.lookup_vat(vat_number)


@router.get("/vat/autocomplete")
async def autocomplete_partner(
    vat_number: str = Query(...),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.vat import PartnerSuggestion
    from src.modules.invoicing.services.vat_service import VATAutocompleteService
    svc = VATAutocompleteService(db)
    return await svc.autocomplete_partner(vat_number)


# ══════════════════════════════════════════════════════════════════════
# MULTI-COMPANY
# ══════════════════════════════════════════════════════════════════════


@router.post("/multi-company/mirror/{move_id}")
async def mirror_invoice(
    move_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.multicompany.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.multi_company_service import MultiCompanyService
    svc = MultiCompanyService(db)
    result = await svc.mirror_invoice(move_id)
    await db.commit()
    return result


@router.post("/multi-company/sync")
async def sync_pending_transactions(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.multicompany.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.multi_company_service import MultiCompanyService
    svc = MultiCompanyService(db)
    result = await svc.sync_pending_transactions()
    await db.commit()
    return result


@router.delete("/multi-company/transactions/{transaction_id}")
async def cancel_mirror(
    transaction_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.multicompany.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.multi_company_service import MultiCompanyService
    svc = MultiCompanyService(db)
    await svc.cancel_mirror(transaction_id)
    await db.commit()
    return {"status": "ok"}


@router.get("/multi-company/balance")
async def get_inter_company_balance(
    company_a_id: uuid.UUID = Query(...),
    company_b_id: uuid.UUID = Query(...),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.multicompany.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.multi_company_service import MultiCompanyService
    svc = MultiCompanyService(db)
    return await svc.get_inter_company_balance(company_a_id=company_a_id, company_b_id=company_b_id)


@router.get("/multi-company/rules")
async def list_intercompany_rules(
    company_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.multicompany.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.multi_company import InterCompanyRuleRead
    from src.modules.invoicing.services.multi_company_service import MultiCompanyService
    svc = MultiCompanyService(db)
    return await svc.list_rules(company_id=company_id)


@router.post("/multi-company/rules", status_code=201)
async def create_intercompany_rule(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.multicompany.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.multi_company import (
        InterCompanyRuleCreate,
        InterCompanyRuleRead,
    )
    from src.modules.invoicing.services.multi_company_service import MultiCompanyService
    payload = InterCompanyRuleCreate(**data)
    svc = MultiCompanyService(db)
    rule = await svc.create_rule(payload)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch("/multi-company/rules/{rule_id}")
async def update_intercompany_rule(
    rule_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.multicompany.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.multi_company import (
        InterCompanyRuleUpdate,
        InterCompanyRuleRead,
    )
    from src.modules.invoicing.services.multi_company_service import MultiCompanyService
    payload = InterCompanyRuleUpdate(**data)
    svc = MultiCompanyService(db)
    rule = await svc.update_rule(rule_id, payload)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.post("/multi-company/rules/{rule_id}/deactivate")
async def deactivate_intercompany_rule(
    rule_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.multicompany.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.multi_company_service import MultiCompanyService
    svc = MultiCompanyService(db)
    result = await svc.deactivate_rule(rule_id)
    await db.commit()
    return result


@router.get("/multi-company/transactions")
async def list_intercompany_transactions(
    company_id: uuid.UUID | None = Query(None),
    state: str | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.multicompany.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.multi_company import InterCompanyTransactionRead
    from src.modules.invoicing.services.multi_company_service import MultiCompanyService
    svc = MultiCompanyService(db)
    return await svc.list_transactions(company_id=company_id, state=state)


@router.get("/multi-company/summary")
async def get_intercompany_summary(
    company_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.multicompany.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.multi_company import InterCompanySummary
    from src.modules.invoicing.services.multi_company_service import MultiCompanyService
    svc = MultiCompanyService(db)
    return await svc.get_summary(company_id=company_id)


# ══════════════════════════════════════════════════════════════════════
# FISCAL POSITION
# ══════════════════════════════════════════════════════════════════════


@router.post("/fiscal-position/apply")
async def apply_fiscal_position(
    fiscal_position_id: uuid.UUID,
    invoice_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.fiscal_position_service import FiscalPositionIntegrationService
    svc = FiscalPositionIntegrationService(db)
    result = await svc.apply_fiscal_position(
        fiscal_position_id=fiscal_position_id, invoice_id=invoice_id,
    )
    await db.commit()
    return result


@router.post("/fiscal-position/suggest")
async def suggest_fiscal_position(
    partner_id: uuid.UUID = Query(...),
    country_code: str | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.fiscal_position import FiscalPositionSuggestion
    from src.modules.invoicing.services.fiscal_position_service import FiscalPositionIntegrationService
    svc = FiscalPositionIntegrationService(db)
    return await svc.suggest_fiscal_position(partner_id=partner_id, country_code=country_code)


@router.post("/fiscal-position/apply-taxes")
async def apply_taxes_to_invoice(
    invoice_id: uuid.UUID,
    fiscal_position_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.invoice.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.services.fiscal_position_service import FiscalPositionIntegrationService
    svc = FiscalPositionIntegrationService(db)
    result = await svc.apply_taxes_to_invoice(
        invoice_id=invoice_id, fiscal_position_id=fiscal_position_id,
    )
    await db.commit()
    return result


@router.get("/fiscal-position/oss-info")
async def get_oss_info(
    country_code: str = Query(...),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("invoicing.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.invoicing.schemas.fiscal_position import OSSInfo
    from src.modules.invoicing.services.fiscal_position_service import FiscalPositionIntegrationService
    svc = FiscalPositionIntegrationService(db)
    return await svc.get_oss_info(country_code=country_code)
