"""Accounting module API router.

All endpoints delegate to service layer — zero business logic in routes.

Endpoints organized by domain:
- Chart of Accounts: /accounts
- Journals: /journals
- Journal Entries (Moves): /moves, /invoices
- Taxes: /taxes
- Payments: /payments
- Payment Terms & Fiscal Positions: /payment-terms, /fiscal-positions
- Fiscal Years: /fiscal-years
- Reconciliation: /reconciliation
- Assets: /assets
- Analytic: /analytic-plans, /analytic-accounts, /budgets
- Bank Statements: /bank-statements
- Reports: /reports
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_tenant_session
from src.core.auth.models import User
from src.core.auth.permissions import require_permissions
from src.core.pagination import PageParams, PaginatedResponse, paginate

router = APIRouter(tags=["accounting"])


# ══════════════════════════════════════════════════════════════════════
# CHART OF ACCOUNTS
# ══════════════════════════════════════════════════════════════════════


@router.get("/accounts")
async def list_accounts(
    search: str | None = Query(None),
    account_type: str | None = Query(None),
    internal_group: str | None = Query(None),
    reconcile: bool | None = Query(None),
    is_active: bool | None = Query(True),
    params: PageParams = Depends(),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.account.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.account_service import AccountService
    from src.modules.accounting.schemas.account import AccountReadBrief
    svc = AccountService(db)
    query = svc.build_filtered_query(
        search=search, account_type=account_type,
        internal_group=internal_group, reconcile=reconcile, is_active=is_active,
    )
    return await paginate(db, query, params, AccountReadBrief)


@router.post("/accounts", status_code=201)
async def create_account(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.account.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.account import AccountCreate, AccountRead
    from src.modules.accounting.services.account_service import AccountService
    validated = AccountCreate(**data)
    svc = AccountService(db)
    account = await svc.create_account(validated)
    await db.commit()
    return AccountRead.model_validate(account)


@router.get("/accounts/{account_id}")
async def get_account(
    account_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.account.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.account_service import AccountService
    from src.modules.accounting.schemas.account import AccountRead
    svc = AccountService(db)
    account = await svc.get_account(account_id)
    return AccountRead.model_validate(account)


@router.patch("/accounts/{account_id}")
async def update_account(
    account_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.account.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.account import AccountUpdate, AccountRead
    from src.modules.accounting.services.account_service import AccountService
    validated = AccountUpdate(**data)
    svc = AccountService(db)
    account = await svc.update_account(account_id, validated)
    await db.commit()
    return AccountRead.model_validate(account)


# ══════════════════════════════════════════════════════════════════════
# JOURNALS
# ══════════════════════════════════════════════════════════════════════


@router.get("/journals")
async def list_journals(
    journal_type: str | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.journal.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.journal_service import JournalService
    from src.modules.accounting.schemas.journal import JournalRead
    svc = JournalService(db)
    journals = await svc.list_journals(journal_type)
    return [JournalRead.model_validate(j) for j in journals]


@router.post("/journals", status_code=201)
async def create_journal(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.journal.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.journal import JournalCreate, JournalRead
    from src.modules.accounting.services.journal_service import JournalService
    validated = JournalCreate(**data)
    svc = JournalService(db)
    journal = await svc.create_journal(validated)
    await db.commit()
    return JournalRead.model_validate(journal)


@router.get("/journals/{journal_id}")
async def get_journal(
    journal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.journal.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.journal_service import JournalService
    from src.modules.accounting.schemas.journal import JournalRead
    svc = JournalService(db)
    journal = await svc.get_journal(journal_id)
    return JournalRead.model_validate(journal)


@router.patch("/journals/{journal_id}")
async def update_journal(
    journal_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.journal.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.journal import JournalUpdate, JournalRead
    from src.modules.accounting.services.journal_service import JournalService
    validated = JournalUpdate(**data)
    svc = JournalService(db)
    journal = await svc.update_journal(journal_id, validated)
    await db.commit()
    return JournalRead.model_validate(journal)


# ══════════════════════════════════════════════════════════════════════
# JOURNAL ENTRIES (MOVES)
# ══════════════════════════════════════════════════════════════════════


@router.get("/moves")
async def list_moves(
    search: str | None = Query(None),
    move_type: str | None = Query(None),
    state: str | None = Query(None),
    journal_id: uuid.UUID | None = Query(None),
    partner_id: uuid.UUID | None = Query(None),
    payment_state: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    params: PageParams = Depends(),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.move.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.move_service import MoveService
    from src.modules.accounting.schemas.move import MoveReadBrief
    svc = MoveService(db)
    query = svc.build_filtered_query(
        search=search, move_type=move_type, state=state,
        journal_id=journal_id, partner_id=partner_id,
        payment_state=payment_state, date_from=date_from, date_to=date_to,
    )
    return await paginate(db, query, params, MoveReadBrief)


@router.post("/moves", status_code=201)
async def create_move(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.move.create")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.move import MoveCreate, MoveRead
    from src.modules.accounting.services.move_service import MoveService
    validated = MoveCreate(**data)
    svc = MoveService(db)
    move = await svc.create_move(validated)
    await db.commit()
    await db.refresh(move)
    return MoveRead.model_validate(move)


@router.get("/moves/{move_id}")
async def get_move(
    move_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.move.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.move_service import MoveService
    from src.modules.accounting.schemas.move import MoveRead
    svc = MoveService(db)
    move = await svc.get_move(move_id)
    return MoveRead.model_validate(move)


@router.patch("/moves/{move_id}")
async def update_move(
    move_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.move.update")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.move import MoveUpdate, MoveRead
    from src.modules.accounting.services.move_service import MoveService
    validated = MoveUpdate(**data)
    svc = MoveService(db)
    move = await svc.update_move(move_id, validated)
    await db.commit()
    await db.refresh(move)
    return MoveRead.model_validate(move)


@router.post("/moves/{move_id}/post")
async def post_move(
    move_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.move.post")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.move_service import MoveService
    from src.modules.accounting.schemas.move import MoveRead
    svc = MoveService(db)
    move = await svc.post_move(move_id)
    await db.commit()
    await db.refresh(move)
    return MoveRead.model_validate(move)


@router.post("/moves/{move_id}/cancel")
async def cancel_move(
    move_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.move.post")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.move_service import MoveService
    from src.modules.accounting.schemas.move import MoveRead
    svc = MoveService(db)
    move = await svc.cancel_move(move_id)
    await db.commit()
    await db.refresh(move)
    return MoveRead.model_validate(move)


@router.post("/moves/{move_id}/reset-to-draft")
async def reset_to_draft(
    move_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.move.post")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.move_service import MoveService
    from src.modules.accounting.schemas.move import MoveRead
    svc = MoveService(db)
    move = await svc.reset_to_draft(move_id)
    await db.commit()
    await db.refresh(move)
    return MoveRead.model_validate(move)


@router.post("/moves/{move_id}/reverse")
async def reverse_move(
    move_id: uuid.UUID,
    reversal_date: date | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.move.post")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.move_service import MoveService
    from src.modules.accounting.schemas.move import MoveRead
    svc = MoveService(db)
    move = await svc.create_reversal(move_id, reversal_date=reversal_date)
    await db.commit()
    await db.refresh(move)
    return MoveRead.model_validate(move)


# ══════════════════════════════════════════════════════════════════════
# TAXES
# ══════════════════════════════════════════════════════════════════════


@router.get("/taxes")
async def list_taxes(
    type_tax_use: str | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.tax.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.tax_service import TaxService
    from src.modules.accounting.schemas.tax import TaxRead
    svc = TaxService(db)
    taxes = await svc.list_taxes(type_tax_use)
    return [TaxRead.model_validate(t) for t in taxes]


@router.post("/taxes", status_code=201)
async def create_tax(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.tax.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.tax import TaxCreate, TaxRead
    from src.modules.accounting.services.tax_service import TaxService
    validated = TaxCreate(**data)
    svc = TaxService(db)
    tax = await svc.create_tax(validated)
    await db.commit()
    return TaxRead.model_validate(tax)


@router.get("/taxes/{tax_id}")
async def get_tax(
    tax_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.tax.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.tax_service import TaxService
    from src.modules.accounting.schemas.tax import TaxRead
    svc = TaxService(db)
    tax = await svc.get_tax(tax_id)
    return TaxRead.model_validate(tax)


@router.patch("/taxes/{tax_id}")
async def update_tax(
    tax_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.tax.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.tax import TaxUpdate, TaxRead
    from src.modules.accounting.services.tax_service import TaxService
    validated = TaxUpdate(**data)
    svc = TaxService(db)
    tax = await svc.update_tax(tax_id, validated)
    await db.commit()
    return TaxRead.model_validate(tax)


@router.post("/taxes/compute")
async def compute_taxes(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.tax.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.tax import TaxComputeRequest
    from src.modules.accounting.services.tax_service import TaxService
    validated = TaxComputeRequest(**data)
    svc = TaxService(db)
    result = await svc.compute_taxes(
        validated.tax_ids, validated.price_unit, validated.quantity,
    )
    return {
        "base_amount": result.base_amount,
        "total_tax": result.total_tax,
        "total_included": result.total_included,
        "details": [
            {"tax_id": str(d.tax_id), "tax_name": d.tax_name, "amount": d.tax_amount, "base": d.base_amount}
            for d in result.details
        ],
    }


# ══════════════════════════════════════════════════════════════════════
# PAYMENTS
# ══════════════════════════════════════════════════════════════════════


@router.get("/payments")
async def list_payments(
    search: str | None = Query(None),
    payment_type: str | None = Query(None),
    state: str | None = Query(None),
    partner_id: uuid.UUID | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    params: PageParams = Depends(),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.payment.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.payment_service import PaymentService
    from src.modules.accounting.schemas.payment import PaymentReadBrief
    svc = PaymentService(db)
    query = svc.build_filtered_query(
        search=search, payment_type=payment_type, state=state,
        partner_id=partner_id, date_from=date_from, date_to=date_to,
    )
    return await paginate(db, query, params, PaymentReadBrief)


@router.post("/payments", status_code=201)
async def create_payment(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.payment.create")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.payment import PaymentCreate, PaymentRead
    from src.modules.accounting.services.payment_service import PaymentService
    validated = PaymentCreate(**data)
    svc = PaymentService(db)
    payment = await svc.create_payment(validated)
    await db.commit()
    await db.refresh(payment)
    return PaymentRead.model_validate(payment)


@router.post("/payments/{payment_id}/confirm")
async def confirm_payment(
    payment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.payment.post")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.payment_service import PaymentService
    from src.modules.accounting.schemas.payment import PaymentRead
    svc = PaymentService(db)
    payment = await svc.confirm_payment(payment_id)
    await db.commit()
    await db.refresh(payment)
    return PaymentRead.model_validate(payment)


@router.post("/payments/{payment_id}/cancel")
async def cancel_payment(
    payment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.payment.post")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.payment_service import PaymentService
    from src.modules.accounting.schemas.payment import PaymentRead
    svc = PaymentService(db)
    payment = await svc.cancel_payment(payment_id)
    await db.commit()
    await db.refresh(payment)
    return PaymentRead.model_validate(payment)


# ══════════════════════════════════════════════════════════════════════
# PAYMENT TERMS & FISCAL POSITIONS
# ══════════════════════════════════════════════════════════════════════


@router.get("/payment-terms")
async def list_payment_terms(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.payment_term_service import PaymentTermService
    from src.modules.accounting.schemas.payment_term import PaymentTermRead
    svc = PaymentTermService(db)
    terms = await svc.list_payment_terms()
    return [PaymentTermRead.model_validate(t) for t in terms]


@router.post("/payment-terms", status_code=201)
async def create_payment_term(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.config.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.payment_term import PaymentTermCreate, PaymentTermRead
    from src.modules.accounting.services.payment_term_service import PaymentTermService
    validated = PaymentTermCreate(**data)
    svc = PaymentTermService(db)
    term = await svc.create_payment_term(validated)
    await db.commit()
    return PaymentTermRead.model_validate(term)


@router.get("/payment-terms/{term_id}")
async def get_payment_term(
    term_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.payment_term_service import PaymentTermService
    from src.modules.accounting.schemas.payment_term import PaymentTermRead
    svc = PaymentTermService(db)
    term = await svc.get_payment_term(term_id)
    return PaymentTermRead.model_validate(term)


@router.patch("/payment-terms/{term_id}")
async def update_payment_term(
    term_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.config.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.payment_term import PaymentTermUpdate, PaymentTermRead
    from src.modules.accounting.services.payment_term_service import PaymentTermService
    validated = PaymentTermUpdate(**data)
    svc = PaymentTermService(db)
    term = await svc.update_payment_term(term_id, validated)
    await db.commit()
    return PaymentTermRead.model_validate(term)


@router.post("/payment-terms/{term_id}/compute")
async def compute_payment_term_dates(
    term_id: uuid.UUID,
    total_amount: float = Query(...),
    invoice_date: date = Query(...),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Compute due date installments from a payment term."""
    from src.modules.accounting.services.payment_term_service import PaymentTermService
    svc = PaymentTermService(db)
    term = await svc.get_payment_term(term_id)
    installments = svc.compute_due_dates(term, total_amount, invoice_date)
    return [
        {"date": inst.date.isoformat(), "amount": inst.amount, "percentage": inst.percentage}
        for inst in installments
    ]


@router.get("/fiscal-positions")
async def list_fiscal_positions(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.payment_term_service import PaymentTermService
    from src.modules.accounting.schemas.payment_term import FiscalPositionRead
    svc = PaymentTermService(db)
    fps = await svc.list_fiscal_positions()
    return [FiscalPositionRead.model_validate(fp) for fp in fps]


@router.post("/fiscal-positions", status_code=201)
async def create_fiscal_position(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.config.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.payment_term import FiscalPositionCreate, FiscalPositionRead
    from src.modules.accounting.services.payment_term_service import PaymentTermService
    validated = FiscalPositionCreate(**data)
    svc = PaymentTermService(db)
    fp = await svc.create_fiscal_position(validated)
    await db.commit()
    return FiscalPositionRead.model_validate(fp)


@router.get("/fiscal-positions/{fp_id}")
async def get_fiscal_position(
    fp_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.config.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.payment_term_service import PaymentTermService
    from src.modules.accounting.schemas.payment_term import FiscalPositionRead
    svc = PaymentTermService(db)
    fp = await svc.get_fiscal_position(fp_id)
    return FiscalPositionRead.model_validate(fp)


# ══════════════════════════════════════════════════════════════════════
# FISCAL YEARS
# ══════════════════════════════════════════════════════════════════════


@router.get("/fiscal-years")
async def list_fiscal_years(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.fiscal.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.fiscal_service import FiscalService
    from src.modules.accounting.schemas.fiscal_year import FiscalYearRead
    svc = FiscalService(db)
    years = await svc.list_fiscal_years()
    return [FiscalYearRead.model_validate(fy) for fy in years]


@router.post("/fiscal-years", status_code=201)
async def create_fiscal_year(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.fiscal.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.fiscal_year import FiscalYearCreate, FiscalYearRead
    from src.modules.accounting.services.fiscal_service import FiscalService
    validated = FiscalYearCreate(**data)
    svc = FiscalService(db)
    fy = await svc.create_fiscal_year(validated)
    await db.commit()
    return FiscalYearRead.model_validate(fy)


@router.get("/fiscal-years/{fy_id}")
async def get_fiscal_year(
    fy_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.fiscal.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.fiscal_service import FiscalService
    from src.modules.accounting.schemas.fiscal_year import FiscalYearRead
    svc = FiscalService(db)
    fy = await svc.get_fiscal_year(fy_id)
    return FiscalYearRead.model_validate(fy)


@router.post("/fiscal-years/{fy_id}/close")
async def close_fiscal_year(
    fy_id: uuid.UUID,
    retained_earnings_account_id: uuid.UUID = Query(...),
    closing_journal_id: uuid.UUID = Query(...),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.fiscal.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.fiscal_service import FiscalService
    from src.modules.accounting.schemas.move import MoveRead
    svc = FiscalService(db)
    move = await svc.close_fiscal_year(
        fy_id,
        retained_earnings_account_id=retained_earnings_account_id,
        closing_journal_id=closing_journal_id,
    )
    await db.commit()
    await db.refresh(move)
    return MoveRead.model_validate(move)


# ══════════════════════════════════════════════════════════════════════
# RECONCILIATION
# ══════════════════════════════════════════════════════════════════════


@router.get("/reconciliation/suggestions")
async def reconciliation_suggestions(
    account_id: uuid.UUID = Query(...),
    partner_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.reconcile.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.reconciliation_service import ReconciliationService
    svc = ReconciliationService(db)
    return await svc.get_reconciliation_suggestions(account_id, partner_id)


@router.post("/reconciliation/reconcile")
async def reconcile_lines(
    debit_line_id: uuid.UUID,
    credit_line_id: uuid.UUID,
    amount: float,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.reconcile.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.reconciliation_service import ReconciliationService
    from src.modules.accounting.schemas.reconciliation import PartialReconcileRead
    svc = ReconciliationService(db)
    debit_line = await svc.line_repo.get_by_id_or_raise(debit_line_id, "MoveLine")
    credit_line = await svc.line_repo.get_by_id_or_raise(credit_line_id, "MoveLine")
    partial = await svc.create_partial_reconcile(debit_line, credit_line, amount)
    await db.commit()
    await db.refresh(partial)
    return PartialReconcileRead.model_validate(partial)


@router.post("/reconciliation/unreconcile")
async def unreconcile(
    partial_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.reconcile.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.reconciliation_service import ReconciliationService
    svc = ReconciliationService(db)
    await svc.unreconcile(partial_id)
    await db.commit()
    return {"status": "ok"}


# ══════════════════════════════════════════════════════════════════════
# ASSETS
# ══════════════════════════════════════════════════════════════════════


@router.get("/assets")
async def list_assets(
    state: str | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.asset.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.asset_service import AssetService
    from src.modules.accounting.schemas.asset import AssetReadBrief
    svc = AssetService(db)
    assets = await svc.list_assets(state)
    return [AssetReadBrief.model_validate(a) for a in assets]


@router.post("/assets", status_code=201)
async def create_asset(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.asset.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.asset import AssetCreate, AssetRead
    from src.modules.accounting.services.asset_service import AssetService
    validated = AssetCreate(**data)
    svc = AssetService(db)
    asset = await svc.create_asset(validated)
    await db.commit()
    await db.refresh(asset)
    return AssetRead.model_validate(asset)


@router.post("/assets/{asset_id}/confirm")
async def confirm_asset(
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.asset.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.asset_service import AssetService
    from src.modules.accounting.schemas.asset import AssetRead
    svc = AssetService(db)
    asset = await svc.confirm_asset(asset_id)
    await db.commit()
    await db.refresh(asset)
    return AssetRead.model_validate(asset)


@router.post("/assets/{asset_id}/depreciate")
async def post_depreciation(
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.asset.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.asset_service import AssetService
    svc = AssetService(db)
    lines = await svc.post_depreciation(asset_id)
    await db.commit()
    return {"posted_lines": len(lines)}


@router.post("/assets/{asset_id}/dispose")
async def dispose_asset(
    asset_id: uuid.UUID,
    disposal_date: date | None = Query(None),
    sale_amount: float = Query(0.0),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.asset.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.asset_service import AssetService
    from src.modules.accounting.schemas.asset import AssetRead
    svc = AssetService(db)
    asset = await svc.dispose_asset(asset_id, disposal_date=disposal_date, sale_amount=sale_amount)
    await db.commit()
    await db.refresh(asset)
    return AssetRead.model_validate(asset)


# ══════════════════════════════════════════════════════════════════════
# ANALYTIC ACCOUNTING
# ══════════════════════════════════════════════════════════════════════


@router.get("/analytic-plans")
async def list_analytic_plans(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.analytic.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.analytic_service import AnalyticService
    from src.modules.accounting.schemas.analytic import AnalyticPlanRead
    svc = AnalyticService(db)
    plans = await svc.list_plans()
    return [AnalyticPlanRead.model_validate(p) for p in plans]


@router.post("/analytic-plans", status_code=201)
async def create_analytic_plan(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.analytic.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.analytic import AnalyticPlanCreate, AnalyticPlanRead
    from src.modules.accounting.services.analytic_service import AnalyticService
    validated = AnalyticPlanCreate(**data)
    svc = AnalyticService(db)
    plan = await svc.create_plan(validated)
    await db.commit()
    return AnalyticPlanRead.model_validate(plan)


@router.get("/analytic-plans/{plan_id}")
async def get_analytic_plan(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.analytic.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.analytic_service import AnalyticService
    from src.modules.accounting.schemas.analytic import AnalyticPlanRead
    svc = AnalyticService(db)
    plan = await svc.get_plan(plan_id)
    return AnalyticPlanRead.model_validate(plan)


@router.patch("/analytic-plans/{plan_id}")
async def update_analytic_plan(
    plan_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.analytic.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.analytic import AnalyticPlanUpdate, AnalyticPlanRead
    from src.modules.accounting.services.analytic_service import AnalyticService
    validated = AnalyticPlanUpdate(**data)
    svc = AnalyticService(db)
    plan = await svc.update_plan(plan_id, validated)
    await db.commit()
    return AnalyticPlanRead.model_validate(plan)


@router.get("/analytic-accounts")
async def list_analytic_accounts(
    plan_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.analytic.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.analytic_service import AnalyticService
    from src.modules.accounting.schemas.analytic import AnalyticAccountRead
    svc = AnalyticService(db)
    accounts = await svc.list_accounts(plan_id)
    return [AnalyticAccountRead.model_validate(a) for a in accounts]


@router.post("/analytic-accounts", status_code=201)
async def create_analytic_account(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.analytic.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.analytic import AnalyticAccountCreate, AnalyticAccountRead
    from src.modules.accounting.services.analytic_service import AnalyticService
    validated = AnalyticAccountCreate(**data)
    svc = AnalyticService(db)
    account = await svc.create_account(validated)
    await db.commit()
    return AnalyticAccountRead.model_validate(account)


@router.get("/analytic-accounts/{account_id}")
async def get_analytic_account(
    account_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.analytic.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.analytic_service import AnalyticService
    from src.modules.accounting.schemas.analytic import AnalyticAccountRead
    svc = AnalyticService(db)
    account = await svc.get_account(account_id)
    return AnalyticAccountRead.model_validate(account)


@router.patch("/analytic-accounts/{account_id}")
async def update_analytic_account(
    account_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.analytic.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.analytic import AnalyticAccountUpdate, AnalyticAccountRead
    from src.modules.accounting.services.analytic_service import AnalyticService
    validated = AnalyticAccountUpdate(**data)
    svc = AnalyticService(db)
    account = await svc.update_account(account_id, validated)
    await db.commit()
    return AnalyticAccountRead.model_validate(account)


@router.get("/budgets")
async def list_budgets(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.analytic.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.analytic_service import AnalyticService
    from src.modules.accounting.schemas.analytic import BudgetRead
    svc = AnalyticService(db)
    budgets = await svc.list_budgets()
    return [BudgetRead.model_validate(b) for b in budgets]


@router.post("/budgets", status_code=201)
async def create_budget(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.analytic.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.analytic import BudgetCreate, BudgetRead
    from src.modules.accounting.services.analytic_service import AnalyticService
    validated = BudgetCreate(**data)
    svc = AnalyticService(db)
    budget = await svc.create_budget(validated)
    await db.commit()
    return BudgetRead.model_validate(budget)


@router.get("/budgets/{budget_id}")
async def get_budget(
    budget_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.analytic.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.analytic_service import AnalyticService
    from src.modules.accounting.schemas.analytic import BudgetRead
    svc = AnalyticService(db)
    budget = await svc.get_budget(budget_id)
    return BudgetRead.model_validate(budget)


@router.patch("/budgets/{budget_id}")
async def update_budget(
    budget_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.analytic.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.analytic import BudgetUpdate, BudgetRead
    from src.modules.accounting.services.analytic_service import AnalyticService
    validated = BudgetUpdate(**data)
    svc = AnalyticService(db)
    budget = await svc.update_budget(budget_id, validated)
    await db.commit()
    return BudgetRead.model_validate(budget)


# ══════════════════════════════════════════════════════════════════════
# BANK STATEMENTS
# ══════════════════════════════════════════════════════════════════════


@router.get("/bank-statements")
async def list_bank_statements(
    journal_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.bank.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.bank_statement_service import BankStatementService
    from src.modules.accounting.schemas.bank_statement import BankStatementReadBrief
    svc = BankStatementService(db)
    statements = await svc.list_statements(journal_id)
    return [BankStatementReadBrief.model_validate(s) for s in statements]


@router.post("/bank-statements", status_code=201)
async def create_bank_statement(
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.bank.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.bank_statement import BankStatementCreate, BankStatementRead
    from src.modules.accounting.services.bank_statement_service import BankStatementService
    validated = BankStatementCreate(**data)
    svc = BankStatementService(db)
    stmt = await svc.create_statement(validated)
    await db.commit()
    return BankStatementRead.model_validate(stmt)


@router.get("/bank-statements/{statement_id}")
async def get_bank_statement(
    statement_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.bank.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.bank_statement_service import BankStatementService
    from src.modules.accounting.schemas.bank_statement import BankStatementRead
    svc = BankStatementService(db)
    stmt = await svc.get_statement(statement_id)
    return BankStatementRead.model_validate(stmt)


@router.patch("/bank-statements/{statement_id}")
async def update_bank_statement(
    statement_id: uuid.UUID,
    data: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.bank.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.bank_statement import BankStatementUpdate, BankStatementRead
    from src.modules.accounting.services.bank_statement_service import BankStatementService
    validated = BankStatementUpdate(**data)
    svc = BankStatementService(db)
    stmt = await svc.update_statement(statement_id, validated)
    await db.commit()
    return BankStatementRead.model_validate(stmt)


@router.post("/bank-statements/{statement_id}/confirm")
async def confirm_bank_statement(
    statement_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.bank.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.bank_statement_service import BankStatementService
    from src.modules.accounting.schemas.bank_statement import BankStatementRead
    svc = BankStatementService(db)
    stmt = await svc.confirm_statement(statement_id)
    await db.commit()
    return BankStatementRead.model_validate(stmt)


# ══════════════════════════════════════════════════════════════════════
# REPORTS
# ══════════════════════════════════════════════════════════════════════


@router.get("/reports/trial-balance")
async def trial_balance_report(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.reporting_service import ReportingService
    svc = ReportingService(db)
    lines = await svc.trial_balance(date_from=date_from, date_to=date_to)
    return [
        {"account_code": l.account_code, "account_name": l.account_name,
         "debit": l.debit, "credit": l.credit, "balance": l.balance}
        for l in lines
    ]


@router.get("/reports/profit-and-loss")
async def profit_and_loss_report(
    date_from: date = Query(...),
    date_to: date = Query(...),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.reporting_service import ReportingService
    svc = ReportingService(db)
    return await svc.profit_and_loss(date_from=date_from, date_to=date_to)


@router.get("/reports/balance-sheet")
async def balance_sheet_report(
    as_of: date = Query(...),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.reporting_service import ReportingService
    svc = ReportingService(db)
    return await svc.balance_sheet(as_of=as_of)


@router.get("/reports/general-ledger/{account_id}")
async def general_ledger_report(
    account_id: uuid.UUID,
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.reporting_service import ReportingService
    svc = ReportingService(db)
    return await svc.general_ledger(account_id=account_id, date_from=date_from, date_to=date_to)


@router.get("/reports/aged-receivable")
async def aged_receivable_report(
    as_of: date | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.reporting_service import ReportingService
    svc = ReportingService(db)
    lines = await svc.aged_receivable(as_of=as_of)
    return [
        {"partner_id": str(l.partner_id), "current": l.current, "1_30": l.days_1_30,
         "31_60": l.days_31_60, "61_90": l.days_61_90, "over_90": l.days_over_90, "total": l.total}
        for l in lines
    ]


@router.get("/reports/aged-payable")
async def aged_payable_report(
    as_of: date | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.reporting_service import ReportingService
    svc = ReportingService(db)
    lines = await svc.aged_payable(as_of=as_of)
    return [
        {"partner_id": str(l.partner_id), "current": l.current, "1_30": l.days_1_30,
         "31_60": l.days_31_60, "61_90": l.days_61_90, "over_90": l.days_over_90, "total": l.total}
        for l in lines
    ]


@router.get("/reports/tax-report")
async def tax_report(
    date_from: date = Query(...),
    date_to: date = Query(...),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.reporting_service import ReportingService
    svc = ReportingService(db)
    return await svc.tax_report(date_from=date_from, date_to=date_to)


@router.get("/reports/account-balances")
async def account_balances(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.reporting_service import ReportingService
    svc = ReportingService(db)
    return await svc.account_balances()


# ══════════════════════════════════════════════════════════════════════
# LOCALIZATION PACKAGES
# ══════════════════════════════════════════════════════════════════════


@router.get("/localization/packages")
async def list_localization_packages(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.localization.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.localization_service import LocalizationService
    svc = LocalizationService(db)
    return await svc.list_available_packages()


@router.get("/localization/packages/{country_code}")
async def get_localization_package(
    country_code: str,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.localization.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.localization_service import LocalizationService
    svc = LocalizationService(db)
    return await svc.get_package(country_code)


@router.post("/localization/install")
async def install_localization_package(
    payload: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.localization.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.schemas.localization import LocalizationInstallRequest
    from src.modules.accounting.services.localization_service import LocalizationService
    req = LocalizationInstallRequest(**payload)
    svc = LocalizationService(db)
    return await svc.install_package(req)


@router.get("/localization/install-history")
async def get_install_history(
    company_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.localization.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.localization_service import LocalizationService
    svc = LocalizationService(db)
    return await svc.get_install_history(company_id=company_id)


@router.post("/localization/seed-defaults")
async def seed_default_packages(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.localization.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.localization_service import LocalizationService
    svc = LocalizationService(db)
    count = await svc.seed_default_packages()
    return {"packages_created": count}


# ══════════════════════════════════════════════════════════════════════
# PERIOD CLOSING
# ══════════════════════════════════════════════════════════════════════


@router.get("/period-closing/{fiscal_year_id}/check")
async def check_period_closable(
    fiscal_year_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.fiscal.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.period_closing_service import PeriodClosingService
    svc = PeriodClosingService(db)
    return await svc.check_period_closable(fiscal_year_id)


@router.post("/period-closing/{fiscal_year_id}/close")
async def close_period(
    fiscal_year_id: uuid.UUID,
    payload: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.fiscal.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.period_closing_service import PeriodClosingService
    svc = PeriodClosingService(db)
    return await svc.close_period(
        fiscal_year_id=fiscal_year_id,
        closing_journal_id=payload["closing_journal_id"],
        user_id=user.id,
    )


@router.post("/period-closing/{fiscal_year_id}/reopen")
async def reopen_period(
    fiscal_year_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.fiscal.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.period_closing_service import PeriodClosingService
    svc = PeriodClosingService(db)
    await svc.reopen_period(fiscal_year_id, user_id=user.id)
    return {"status": "reopened"}


@router.post("/lock-dates")
async def set_lock_date(
    payload: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.fiscal.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.period_closing_service import PeriodClosingService
    svc = PeriodClosingService(db)
    await svc.set_lock_date(
        lock_date=date.fromisoformat(payload["lock_date"]),
        lock_type=payload.get("lock_type", "all"),
    )
    return {"status": "lock_date_set"}


@router.get("/lock-dates")
async def get_lock_dates(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.fiscal.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.period_closing_service import PeriodClosingService
    svc = PeriodClosingService(db)
    return await svc.get_lock_dates()


# ══════════════════════════════════════════════════════════════════════
# BANK FEED IMPORT
# ══════════════════════════════════════════════════════════════════════


@router.post("/bank-feed/import/ofx")
async def import_ofx(
    payload: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.bank.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.bank_feed_service import BankFeedService
    svc = BankFeedService(db)
    return await svc.import_ofx(
        journal_id=payload["journal_id"],
        file_content=payload["file_content"].encode() if isinstance(payload["file_content"], str) else payload["file_content"],
    )


@router.post("/bank-feed/import/csv")
async def import_csv(
    payload: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.bank.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.bank_feed_service import BankFeedService
    svc = BankFeedService(db)
    return await svc.import_csv(
        journal_id=payload["journal_id"],
        file_content=payload["file_content"],
        mapping=payload.get("mapping"),
    )


@router.post("/bank-feed/import/camt053")
async def import_camt053(
    payload: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.bank.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.bank_feed_service import BankFeedService
    svc = BankFeedService(db)
    return await svc.import_camt053(
        journal_id=payload["journal_id"],
        file_content=payload["file_content"].encode() if isinstance(payload["file_content"], str) else payload["file_content"],
    )


@router.post("/bank-feed/import/qif")
async def import_qif(
    payload: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.bank.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.bank_feed_service import BankFeedService
    svc = BankFeedService(db)
    return await svc.import_qif(
        journal_id=payload["journal_id"],
        file_content=payload["file_content"],
    )


@router.get("/bank-feed/import-history")
async def bank_feed_import_history(
    journal_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.bank.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.bank_feed_service import BankFeedService
    svc = BankFeedService(db)
    return await svc.get_import_history(journal_id=journal_id)


# ══════════════════════════════════════════════════════════════════════
# SMART RECONCILIATION
# ══════════════════════════════════════════════════════════════════════


@router.post("/smart-reconciliation/{statement_id}/auto-match")
async def auto_match_statement(
    statement_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.reconcile.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.smart_reconciliation_service import SmartReconciliationService
    svc = SmartReconciliationService(db)
    return await svc.auto_match_statement(statement_id)


@router.get("/smart-reconciliation/line/{statement_line_id}/suggestions")
async def suggest_matches(
    statement_line_id: uuid.UUID,
    limit: int = Query(5, ge=1, le=20),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.reconcile.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.smart_reconciliation_service import SmartReconciliationService
    svc = SmartReconciliationService(db)
    return await svc.suggest_matches(statement_line_id, limit=limit)


@router.post("/smart-reconciliation/line/{statement_line_id}/reconcile")
async def reconcile_match(
    statement_line_id: uuid.UUID,
    payload: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.reconcile.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.smart_reconciliation_service import SmartReconciliationService
    svc = SmartReconciliationService(db)
    return await svc.reconcile_match(statement_line_id, move_line_ids=payload["move_line_ids"])


@router.post("/smart-reconciliation/line/{statement_line_id}/unreconcile")
async def unreconcile_line(
    statement_line_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.reconcile.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.smart_reconciliation_service import SmartReconciliationService
    svc = SmartReconciliationService(db)
    await svc.unreconcile(statement_line_id)
    return {"status": "unreconciled"}


@router.post("/smart-reconciliation/line/{statement_line_id}/write-off")
async def create_write_off(
    statement_line_id: uuid.UUID,
    payload: dict,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.reconcile.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.smart_reconciliation_service import SmartReconciliationService
    svc = SmartReconciliationService(db)
    return await svc.create_write_off(
        statement_line_id=statement_line_id,
        move_line_id=payload["move_line_id"],
        write_off_account_id=payload["write_off_account_id"],
    )


@router.get("/smart-reconciliation/stats")
async def reconciliation_stats(
    journal_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.reconcile.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.smart_reconciliation_service import SmartReconciliationService
    svc = SmartReconciliationService(db)
    return await svc.get_reconciliation_stats(journal_id=journal_id)


# ══════════════════════════════════════════════════════════════════════
# CASH BASIS TAXES
# ══════════════════════════════════════════════════════════════════════


@router.post("/cash-basis/generate/{payment_id}")
async def generate_cash_basis_entries(
    payment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.tax.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.cash_basis_service import CashBasisService
    svc = CashBasisService(db)
    move_ids = await svc.generate_cash_basis_entries(payment_id)
    return {"move_ids": [str(mid) for mid in move_ids]}


@router.post("/cash-basis/reverse/{payment_id}")
async def reverse_cash_basis_entries(
    payment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.tax.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.cash_basis_service import CashBasisService
    svc = CashBasisService(db)
    move_ids = await svc.reverse_cash_basis_entries(payment_id)
    return {"reversed_move_ids": [str(mid) for mid in move_ids]}


@router.get("/cash-basis/report")
async def cash_basis_report(
    date_from: date = Query(...),
    date_to: date = Query(...),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("accounting.report.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.accounting.services.cash_basis_service import CashBasisService
    svc = CashBasisService(db)
    return await svc.get_cash_basis_report(date_from, date_to)
