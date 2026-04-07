"""Contacts module API router.

All endpoints require:
1. Tenant resolution (X-Tenant-ID header)
2. Authentication (Bearer token)
3. Module activation (contacts must be active for the tenant)
4. Permission checking (contacts.partner.read, etc.)

Endpoints:
- Partners: full CRUD + archive/restore + search + address resolution
- Addresses: sub-resource CRUD under /partners/{id}/addresses
- Bank Accounts: sub-resource CRUD under /partners/{id}/bank-accounts
- Categories: standalone CRUD for partner tags
- Industries: standalone CRUD for industry lookup
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_tenant_session
from src.core.auth.models import User
from src.core.auth.permissions import require_permissions
from src.core.pagination import PageParams, PaginatedResponse, paginate
from src.modules.contacts.models.partner import PartnerIndustry
from src.modules.contacts.repositories.industry_repo import IndustryRepository
from src.modules.contacts.schemas.partner import (
    AddressCreate,
    AddressRead,
    AddressUpdate,
    BankAccountCreate,
    BankAccountRead,
    BankAccountUpdate,
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    IndustryCreate,
    IndustryRead,
    PartnerCreate,
    PartnerFilter,
    PartnerRead,
    PartnerReadBrief,
    PartnerUpdate,
)
from src.modules.contacts.services.address_service import AddressService
from src.modules.contacts.services.bank_service import BankAccountService
from src.modules.contacts.services.category_service import CategoryService
from src.modules.contacts.services.partner_service import PartnerService

router = APIRouter(tags=["contacts"])


# ══════════════════════════════════════════════════════════════════════
# PARTNERS
# ══════════════════════════════════════════════════════════════════════


@router.get("/partners", response_model=PaginatedResponse[PartnerReadBrief])
async def list_partners(
    search: str | None = Query(None),
    is_company: bool | None = Query(None),
    is_customer: bool | None = Query(None),
    is_vendor: bool | None = Query(None),
    is_active: bool | None = Query(True),
    partner_type: str | None = Query(None),
    parent_id: uuid.UUID | None = Query(None),
    country_code: str | None = Query(None),
    industry_id: uuid.UUID | None = Query(None),
    tag_id: str | None = Query(None),
    params: PageParams = Depends(),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    """List partners with filtering, search, and pagination."""
    svc = PartnerService(db)
    query = svc.repo.build_filtered_query(
        search=search,
        is_company=is_company,
        is_customer=is_customer,
        is_vendor=is_vendor,
        is_active=is_active,
        partner_type=partner_type,
        parent_id=parent_id,
        country_code=country_code,
        industry_id=industry_id,
        tag_id=tag_id,
    )
    return await paginate(db, query, params, PartnerReadBrief)


@router.post("/partners", response_model=PartnerRead, status_code=201)
async def create_partner(
    data: PartnerCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.create")),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Create a new partner (person, company, or address)."""
    svc = PartnerService(db)
    partner = await svc.create_partner(data)
    await db.commit()
    await db.refresh(partner)
    return partner


@router.get("/partners/{partner_id}", response_model=PartnerRead)
async def get_partner(
    partner_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Get a single partner with full details."""
    svc = PartnerService(db)
    return await svc.get_partner(partner_id)


@router.patch("/partners/{partner_id}", response_model=PartnerRead)
async def update_partner(
    partner_id: uuid.UUID,
    data: PartnerUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.update")),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Update a partner (partial update)."""
    svc = PartnerService(db)
    partner = await svc.update_partner(partner_id, data)
    await db.commit()
    await db.refresh(partner)
    return partner


@router.delete("/partners/{partner_id}", status_code=204)
async def delete_partner(
    partner_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.delete")),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Hard delete a partner. Prefer archive for production use."""
    svc = PartnerService(db)
    await svc.delete_partner(partner_id)
    await db.commit()


@router.post("/partners/{partner_id}/archive", response_model=PartnerRead)
async def archive_partner(
    partner_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.update")),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Soft-delete (archive) a partner."""
    svc = PartnerService(db)
    partner = await svc.archive_partner(partner_id)
    await db.commit()
    await db.refresh(partner)
    return partner


@router.post("/partners/{partner_id}/restore", response_model=PartnerRead)
async def restore_partner(
    partner_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.update")),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Restore an archived partner."""
    svc = PartnerService(db)
    partner = await svc.restore_partner(partner_id)
    await db.commit()
    await db.refresh(partner)
    return partner


@router.get("/partners/{partner_id}/addresses/resolve")
async def resolve_addresses(
    partner_id: uuid.UUID,
    types: str = Query("invoice,delivery,contact", description="Comma-separated address types"),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Resolve the best address for each requested type (Odoo-style address_get)."""
    svc = PartnerService(db)
    address_types = [t.strip() for t in types.split(",")]
    return await svc.get_address(partner_id, address_types)


@router.get("/partners/stats/overview")
async def partner_stats(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Get partner counts grouped by type."""
    svc = PartnerService(db)
    return await svc.get_stats()


# ══════════════════════════════════════════════════════════════════════
# ADDRESSES (sub-resource of Partner)
# ══════════════════════════════════════════════════════════════════════


@router.get(
    "/partners/{partner_id}/addresses",
    response_model=list[AddressRead],
)
async def list_addresses(
    partner_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    svc = AddressService(db)
    return await svc.list_addresses(partner_id)


@router.post(
    "/partners/{partner_id}/addresses",
    response_model=AddressRead,
    status_code=201,
)
async def add_address(
    partner_id: uuid.UUID,
    data: AddressCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.update")),
    db: AsyncSession = Depends(get_tenant_session),
):
    svc = AddressService(db)
    address = await svc.add_address(partner_id, data)
    await db.commit()
    return address


@router.patch("/addresses/{address_id}", response_model=AddressRead)
async def update_address(
    address_id: uuid.UUID,
    data: AddressUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.update")),
    db: AsyncSession = Depends(get_tenant_session),
):
    svc = AddressService(db)
    address = await svc.update_address(address_id, data)
    await db.commit()
    return address


@router.delete("/addresses/{address_id}", status_code=204)
async def delete_address(
    address_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.delete")),
    db: AsyncSession = Depends(get_tenant_session),
):
    svc = AddressService(db)
    await svc.delete_address(address_id)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# BANK ACCOUNTS (sub-resource of Partner)
# ══════════════════════════════════════════════════════════════════════


@router.get(
    "/partners/{partner_id}/bank-accounts",
    response_model=list[BankAccountRead],
)
async def list_bank_accounts(
    partner_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    svc = BankAccountService(db)
    return await svc.list_bank_accounts(partner_id)


@router.post(
    "/partners/{partner_id}/bank-accounts",
    response_model=BankAccountRead,
    status_code=201,
)
async def add_bank_account(
    partner_id: uuid.UUID,
    data: BankAccountCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.update")),
    db: AsyncSession = Depends(get_tenant_session),
):
    svc = BankAccountService(db)
    account = await svc.add_bank_account(partner_id, data)
    await db.commit()
    return account


@router.patch("/bank-accounts/{account_id}", response_model=BankAccountRead)
async def update_bank_account(
    account_id: uuid.UUID,
    data: BankAccountUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.update")),
    db: AsyncSession = Depends(get_tenant_session),
):
    svc = BankAccountService(db)
    account = await svc.update_bank_account(account_id, data)
    await db.commit()
    return account


@router.delete("/bank-accounts/{account_id}", status_code=204)
async def delete_bank_account(
    account_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.delete")),
    db: AsyncSession = Depends(get_tenant_session),
):
    svc = BankAccountService(db)
    await svc.delete_bank_account(account_id)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# CATEGORIES (tags)
# ══════════════════════════════════════════════════════════════════════


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.category.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    svc = CategoryService(db)
    return await svc.list_categories()


@router.post("/categories", response_model=CategoryRead, status_code=201)
async def create_category(
    data: CategoryCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.category.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    svc = CategoryService(db)
    category = await svc.create_category(data)
    await db.commit()
    return category


@router.patch("/categories/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: uuid.UUID,
    data: CategoryUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.category.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    svc = CategoryService(db)
    category = await svc.update_category(category_id, data)
    await db.commit()
    return category


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(
    category_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.category.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    svc = CategoryService(db)
    await svc.delete_category(category_id)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# INDUSTRIES
# ══════════════════════════════════════════════════════════════════════


@router.get("/industries", response_model=list[IndustryRead])
async def list_industries(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.partner.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    repo = IndustryRepository(db)
    return await repo.list_active()


@router.post("/industries", response_model=IndustryRead, status_code=201)
async def create_industry(
    data: IndustryCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("contacts.category.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    repo = IndustryRepository(db)
    existing = await repo.find_by_name(data.name)
    if existing:
        from src.core.errors.exceptions import ConflictError
        raise ConflictError(f"Industry '{data.name}' already exists")
    industry = await repo.create(**data.model_dump())
    await db.commit()
    return industry
