"""Product module API router.

All endpoints delegate to service layer — zero business logic in routes.

Endpoints organized by sub-resource:
- UoM Categories & Units: /uom-categories, /uoms
- Product Categories: /product-categories
- Attributes & Values: /attributes, /attribute-values
- Product Templates: /products (template-centric, variants nested)
- Product Variants: /products/{id}/variants, /variants/{id}
- Pricelists: /pricelists
- Pricing: /pricing/compute
- Tags: /product-tags
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_tenant_session
from src.core.auth.models import User
from src.core.auth.permissions import require_permissions
from src.core.pagination import PageParams, PaginatedResponse, paginate
from src.modules.product.schemas.attribute import (
    ProductAttributeCreate,
    ProductAttributeRead,
    ProductAttributeUpdate,
    ProductAttributeValueCreate,
    ProductAttributeValueRead,
    TemplateAttributeLineCreate,
)
from src.modules.product.schemas.category import (
    ProductCategoryCreate,
    ProductCategoryRead,
    ProductCategoryUpdate,
)
from src.modules.product.schemas.pricelist import (
    PricelistCreate,
    PricelistItemCreate,
    PricelistItemRead,
    PricelistItemUpdate,
    PricelistRead,
    PricelistUpdate,
)
from src.modules.product.schemas.product import (
    PriceComputeRequest,
    PriceComputeResponse,
    ProductTagCreate,
    ProductTagRead,
    ProductTemplateCreate,
    ProductTemplateRead,
    ProductTemplateReadBrief,
    ProductTemplateUpdate,
    VariantRead,
    VariantReadBrief,
    VariantUpdate,
)
from src.modules.product.schemas.uom import (
    UomCategoryCreate,
    UomCategoryRead,
    UomConvertRequest,
    UomConvertResponse,
    UomCreate,
    UomRead,
    UomUpdate,
)

router = APIRouter(tags=["product"])


# ══════════════════════════════════════════════════════════════════════
# UoM CATEGORIES & UNITS
# ══════════════════════════════════════════════════════════════════════


@router.get("/uom-categories", response_model=list[UomCategoryRead])
async def list_uom_categories(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.uom.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.uom_service import UomService
    svc = UomService(db)
    return await svc.list_categories()


@router.post("/uom-categories", response_model=UomCategoryRead, status_code=201)
async def create_uom_category(
    data: UomCategoryCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.uom.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.uom_service import UomService
    svc = UomService(db)
    cat = await svc.create_category(data)
    await db.commit()
    return cat


@router.get("/uoms", response_model=list[UomRead])
async def list_uoms(
    category_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.uom.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.uom_service import UomService
    svc = UomService(db)
    return await svc.list_uoms(category_id)


@router.post("/uoms", response_model=UomRead, status_code=201)
async def create_uom(
    data: UomCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.uom.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.uom_service import UomService
    svc = UomService(db)
    uom = await svc.create_uom(data)
    await db.commit()
    return uom


@router.get("/uoms/{uom_id}", response_model=UomRead)
async def get_uom(
    uom_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.uom.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.uom_service import UomService
    svc = UomService(db)
    return await svc.get_uom(uom_id)


@router.patch("/uoms/{uom_id}", response_model=UomRead)
async def update_uom(
    uom_id: uuid.UUID,
    data: UomUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.uom.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.uom_service import UomService
    svc = UomService(db)
    uom = await svc.update_uom(uom_id, data)
    await db.commit()
    return uom


@router.post("/uoms/convert", response_model=UomConvertResponse)
async def convert_uom(
    data: UomConvertRequest,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.uom.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.uom_service import UomService
    svc = UomService(db)
    return await svc.convert(data)


# ══════════════════════════════════════════════════════════════════════
# PRODUCT CATEGORIES
# ══════════════════════════════════════════════════════════════════════


@router.get("/product-categories", response_model=list[ProductCategoryRead])
async def list_product_categories(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.category.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.category_service import ProductCategoryService
    svc = ProductCategoryService(db)
    return await svc.list_categories()


@router.post("/product-categories", response_model=ProductCategoryRead, status_code=201)
async def create_product_category(
    data: ProductCategoryCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.category.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.category_service import ProductCategoryService
    svc = ProductCategoryService(db)
    cat = await svc.create_category(data)
    await db.commit()
    return cat


@router.patch("/product-categories/{category_id}", response_model=ProductCategoryRead)
async def update_product_category(
    category_id: uuid.UUID,
    data: ProductCategoryUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.category.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.category_service import ProductCategoryService
    svc = ProductCategoryService(db)
    cat = await svc.update_category(category_id, data)
    await db.commit()
    return cat


@router.delete("/product-categories/{category_id}", status_code=204)
async def delete_product_category(
    category_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.category.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.category_service import ProductCategoryService
    svc = ProductCategoryService(db)
    await svc.delete_category(category_id)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# ATTRIBUTES & VALUES
# ══════════════════════════════════════════════════════════════════════


@router.get("/attributes", response_model=list[ProductAttributeRead])
async def list_attributes(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.attribute.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.attribute_service import ProductAttributeService
    svc = ProductAttributeService(db)
    return await svc.list_attributes()


@router.post("/attributes", response_model=ProductAttributeRead, status_code=201)
async def create_attribute(
    data: ProductAttributeCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.attribute.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.attribute_service import ProductAttributeService
    svc = ProductAttributeService(db)
    attr = await svc.create_attribute(data)
    await db.commit()
    await db.refresh(attr)
    return attr


@router.get("/attributes/{attribute_id}", response_model=ProductAttributeRead)
async def get_attribute(
    attribute_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.attribute.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.attribute_service import ProductAttributeService
    svc = ProductAttributeService(db)
    return await svc.get_attribute(attribute_id)


@router.patch("/attributes/{attribute_id}", response_model=ProductAttributeRead)
async def update_attribute(
    attribute_id: uuid.UUID,
    data: ProductAttributeUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.attribute.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.attribute_service import ProductAttributeService
    svc = ProductAttributeService(db)
    attr = await svc.update_attribute(attribute_id, data)
    await db.commit()
    return attr


@router.post("/attribute-values", response_model=ProductAttributeValueRead, status_code=201)
async def create_attribute_value(
    data: ProductAttributeValueCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.attribute.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.attribute_service import ProductAttributeService
    svc = ProductAttributeService(db)
    val = await svc.create_value(data)
    await db.commit()
    await db.refresh(val)
    return val


@router.get("/attributes/{attribute_id}/values", response_model=list[ProductAttributeValueRead])
async def list_attribute_values(
    attribute_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.attribute.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.attribute_service import ProductAttributeService
    svc = ProductAttributeService(db)
    return await svc.list_values(attribute_id)


# ══════════════════════════════════════════════════════════════════════
# PRODUCT TEMPLATES
# ══════════════════════════════════════════════════════════════════════


@router.get("/products", response_model=PaginatedResponse[ProductTemplateReadBrief])
async def list_products(
    search: str | None = Query(None),
    product_type: str | None = Query(None),
    category_id: uuid.UUID | None = Query(None),
    sale_ok: bool | None = Query(None),
    purchase_ok: bool | None = Query(None),
    is_active: bool | None = Query(True),
    is_favorite: bool | None = Query(None),
    params: PageParams = Depends(),
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.product.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.product_service import ProductService
    svc = ProductService(db)
    query = svc.build_filtered_query(
        search=search,
        product_type=product_type,
        category_id=category_id,
        sale_ok=sale_ok,
        purchase_ok=purchase_ok,
        is_active=is_active,
        is_favorite=is_favorite,
    )
    return await paginate(db, query, params, ProductTemplateReadBrief)


@router.post("/products", response_model=ProductTemplateRead, status_code=201)
async def create_product(
    data: ProductTemplateCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.product.create")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.product_service import ProductService
    svc = ProductService(db)
    template = await svc.create_template(data)
    await db.commit()
    await db.refresh(template)
    return template


@router.get("/products/{template_id}", response_model=ProductTemplateRead)
async def get_product(
    template_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.product.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.product_service import ProductService
    svc = ProductService(db)
    return await svc.get_template(template_id)


@router.patch("/products/{template_id}", response_model=ProductTemplateRead)
async def update_product(
    template_id: uuid.UUID,
    data: ProductTemplateUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.product.update")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.product_service import ProductService
    svc = ProductService(db)
    template = await svc.update_template(template_id, data)
    await db.commit()
    await db.refresh(template)
    return template


@router.delete("/products/{template_id}", status_code=204)
async def delete_product(
    template_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.product.delete")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.product_service import ProductService
    svc = ProductService(db)
    await svc.delete_template(template_id)
    await db.commit()


@router.post("/products/{template_id}/archive", response_model=ProductTemplateRead)
async def archive_product(
    template_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.product.update")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.product_service import ProductService
    svc = ProductService(db)
    template = await svc.archive_template(template_id)
    await db.commit()
    await db.refresh(template)
    return template


@router.post("/products/{template_id}/restore", response_model=ProductTemplateRead)
async def restore_product(
    template_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.product.update")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.product_service import ProductService
    svc = ProductService(db)
    template = await svc.restore_template(template_id)
    await db.commit()
    await db.refresh(template)
    return template


# ── Attribute Lines (sub-resource of Template) ────────────────────────


@router.post(
    "/products/{template_id}/attribute-lines",
    response_model=ProductTemplateRead,
    status_code=201,
)
async def add_attribute_line(
    template_id: uuid.UUID,
    data: TemplateAttributeLineCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.product.update")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.product_service import ProductService
    svc = ProductService(db)
    template = await svc.add_attribute_line(template_id, data)
    await db.commit()
    await db.refresh(template)
    return template


@router.delete("/products/{template_id}/attribute-lines/{line_id}", response_model=ProductTemplateRead)
async def remove_attribute_line(
    template_id: uuid.UUID,
    line_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.product.update")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.product_service import ProductService
    svc = ProductService(db)
    template = await svc.remove_attribute_line(template_id, line_id)
    await db.commit()
    await db.refresh(template)
    return template


# ══════════════════════════════════════════════════════════════════════
# PRODUCT VARIANTS
# ══════════════════════════════════════════════════════════════════════


@router.get("/products/{template_id}/variants", response_model=list[VariantReadBrief])
async def list_variants(
    template_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.product.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.product_service import ProductService
    svc = ProductService(db)
    return await svc.list_variants(template_id)


@router.get("/variants/{variant_id}", response_model=VariantRead)
async def get_variant(
    variant_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.product.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.product_service import ProductService
    svc = ProductService(db)
    return await svc.get_variant(variant_id)


@router.patch("/variants/{variant_id}", response_model=VariantRead)
async def update_variant(
    variant_id: uuid.UUID,
    data: VariantUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.product.update")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.product_service import ProductService
    svc = ProductService(db)
    variant = await svc.update_variant(variant_id, data)
    await db.commit()
    return variant


@router.post("/products/{template_id}/variants/create-dynamic", response_model=VariantRead)
async def create_dynamic_variant(
    template_id: uuid.UUID,
    ptav_ids: list[uuid.UUID],
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.product.create")),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Create a variant on-demand for dynamic attribute combinations."""
    from src.modules.product.services.product_service import ProductService
    from src.modules.product.services.variant_service import VariantService
    psvc = ProductService(db)
    template = await psvc.get_template(template_id)
    vsvc = VariantService(db)
    variant = await vsvc.create_dynamic_variant(template, ptav_ids)
    await db.commit()
    await db.refresh(variant)
    return variant


# ══════════════════════════════════════════════════════════════════════
# PRICELISTS
# ══════════════════════════════════════════════════════════════════════


@router.get("/pricelists", response_model=list[PricelistRead])
async def list_pricelists(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.pricelist.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.pricelist_service import PricelistService
    svc = PricelistService(db)
    return await svc.list_pricelists()


@router.post("/pricelists", response_model=PricelistRead, status_code=201)
async def create_pricelist(
    data: PricelistCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.pricelist.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.pricelist_service import PricelistService
    svc = PricelistService(db)
    pricelist = await svc.create_pricelist(data)
    await db.commit()
    await db.refresh(pricelist)
    return pricelist


@router.get("/pricelists/{pricelist_id}", response_model=PricelistRead)
async def get_pricelist(
    pricelist_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.pricelist.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.pricelist_service import PricelistService
    svc = PricelistService(db)
    return await svc.get_pricelist(pricelist_id)


@router.patch("/pricelists/{pricelist_id}", response_model=PricelistRead)
async def update_pricelist(
    pricelist_id: uuid.UUID,
    data: PricelistUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.pricelist.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.pricelist_service import PricelistService
    svc = PricelistService(db)
    pricelist = await svc.update_pricelist(pricelist_id, data)
    await db.commit()
    return pricelist


@router.delete("/pricelists/{pricelist_id}", status_code=204)
async def delete_pricelist(
    pricelist_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.pricelist.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.pricelist_service import PricelistService
    svc = PricelistService(db)
    await svc.delete_pricelist(pricelist_id)
    await db.commit()


# ── Pricelist Items ───────────────────────────────────────────────────


@router.post(
    "/pricelists/{pricelist_id}/items",
    response_model=PricelistItemRead,
    status_code=201,
)
async def add_pricelist_item(
    pricelist_id: uuid.UUID,
    data: PricelistItemCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.pricelist.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.pricelist_service import PricelistService
    svc = PricelistService(db)
    item = await svc.add_item(pricelist_id, data)
    await db.commit()
    return item


@router.patch("/pricelist-items/{item_id}", response_model=PricelistItemRead)
async def update_pricelist_item(
    item_id: uuid.UUID,
    data: PricelistItemUpdate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.pricelist.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.pricelist_service import PricelistService
    svc = PricelistService(db)
    item = await svc.update_item(item_id, data)
    await db.commit()
    return item


@router.delete("/pricelist-items/{item_id}", status_code=204)
async def delete_pricelist_item(
    item_id: uuid.UUID,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.pricelist.manage")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.pricelist_service import PricelistService
    svc = PricelistService(db)
    await svc.delete_item(item_id)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════
# PRICING ENGINE
# ══════════════════════════════════════════════════════════════════════


@router.post("/pricing/compute", response_model=PriceComputeResponse)
async def compute_price(
    data: PriceComputeRequest,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.pricelist.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    """Compute the price of a product using a pricelist."""
    from src.modules.product.services.pricing_service import PricingService
    svc = PricingService(db)
    return await svc.compute_price(
        pricelist_id=data.pricelist_id,
        product_variant_id=data.product_variant_id,
        product_template_id=data.product_template_id,
        quantity=data.quantity,
        date=data.date,
    )


# ══════════════════════════════════════════════════════════════════════
# PRODUCT TAGS
# ══════════════════════════════════════════════════════════════════════


@router.get("/product-tags", response_model=list[ProductTagRead])
async def list_product_tags(
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.product.read")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.tag_service import ProductTagService
    svc = ProductTagService(db)
    return await svc.list_tags()


@router.post("/product-tags", response_model=ProductTagRead, status_code=201)
async def create_product_tag(
    data: ProductTagCreate,
    user: User = Depends(get_current_user),
    _perm: None = Depends(require_permissions("product.product.update")),
    db: AsyncSession = Depends(get_tenant_session),
):
    from src.modules.product.services.tag_service import ProductTagService
    svc = ProductTagService(db)
    tag = await svc.create_tag(data)
    await db.commit()
    return tag
