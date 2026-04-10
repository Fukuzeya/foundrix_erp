"""Product Template and Variant Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from src.modules.product.schemas.attribute import (
    TemplateAttributeLineCreate,
    TemplateAttributeLineRead,
)
from src.modules.product.schemas.category import ProductCategoryRead
from src.modules.product.schemas.uom import UomRead


# ── Product Tag ───────────────────────────────────────────────────────

class ProductTagCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: int = 0


class ProductTagRead(BaseModel):
    id: uuid.UUID
    name: str
    color: int
    model_config = {"from_attributes": True}


# ── Variant ───────────────────────────────────────────────────────────

class VariantReadBrief(BaseModel):
    """Minimal variant info for listing."""
    id: uuid.UUID
    default_code: str | None
    barcode: str | None
    is_active: bool
    price_extra: float
    lst_price: float
    standard_price: float
    combination_indices: str
    model_config = {"from_attributes": True}


class VariantRead(BaseModel):
    """Full variant details."""
    id: uuid.UUID
    template_id: uuid.UUID
    default_code: str | None
    barcode: str | None
    is_active: bool
    price_extra: float
    lst_price: float
    standard_price: float
    weight: float
    volume: float
    combination_indices: str
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class VariantUpdate(BaseModel):
    default_code: str | None = None
    barcode: str | None = None
    standard_price: float | None = None
    weight: float | None = None
    volume: float | None = None
    is_active: bool | None = None


# ── Template ──────────────────────────────────────────────────────────

class ProductTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    product_type: str = Field(default="goods", pattern=r"^(goods|service|consumable)$")
    category_id: uuid.UUID | None = None
    uom_id: uuid.UUID
    uom_purchase_id: uuid.UUID | None = None

    list_price: float = 0.0
    standard_price: float = 0.0
    currency_code: str = "USD"

    sale_ok: bool = True
    purchase_ok: bool = True

    description: str | None = None
    description_sale: str | None = None
    description_purchase: str | None = None

    weight: float = 0.0
    volume: float = 0.0

    default_code: str | None = None
    barcode: str | None = None
    notes: str | None = None

    tag_ids: list[uuid.UUID] | None = None
    attribute_lines: list[TemplateAttributeLineCreate] | None = None


class ProductTemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=500)
    product_type: str | None = None
    category_id: uuid.UUID | None = None
    uom_id: uuid.UUID | None = None
    uom_purchase_id: uuid.UUID | None = None

    list_price: float | None = None
    standard_price: float | None = None
    currency_code: str | None = None

    sale_ok: bool | None = None
    purchase_ok: bool | None = None

    description: str | None = None
    description_sale: str | None = None
    description_purchase: str | None = None

    weight: float | None = None
    volume: float | None = None

    default_code: str | None = None
    barcode: str | None = None
    notes: str | None = None
    is_active: bool | None = None
    is_favorite: bool | None = None

    tag_ids: list[uuid.UUID] | None = None


class ProductTemplateReadBrief(BaseModel):
    """Minimal template info for listing."""
    id: uuid.UUID
    name: str
    product_type: str
    default_code: str | None
    list_price: float
    standard_price: float
    currency_code: str
    sale_ok: bool
    purchase_ok: bool
    is_active: bool
    is_favorite: bool
    variant_count: int = 0
    model_config = {"from_attributes": True}


class ProductTemplateRead(BaseModel):
    """Full template details with nested relationships."""
    id: uuid.UUID
    name: str
    product_type: str
    is_active: bool
    is_favorite: bool
    sequence: int

    description: str | None
    description_sale: str | None
    description_purchase: str | None

    list_price: float
    standard_price: float
    currency_code: str

    category_id: uuid.UUID | None
    category: ProductCategoryRead | None = None
    sale_ok: bool
    purchase_ok: bool

    uom_id: uuid.UUID
    uom: UomRead | None = None
    uom_purchase_id: uuid.UUID | None

    weight: float
    volume: float
    default_code: str | None
    barcode: str | None
    notes: str | None

    variants: list[VariantReadBrief] = []
    attribute_lines: list[TemplateAttributeLineRead] = []
    tags: list[ProductTagRead] = []

    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class ProductTemplateFilter(BaseModel):
    """Query params for filtering product templates."""
    search: str | None = Field(None, description="Search name, default_code, barcode")
    product_type: str | None = None
    category_id: uuid.UUID | None = None
    sale_ok: bool | None = None
    purchase_ok: bool | None = None
    is_active: bool | None = Field(True)
    is_favorite: bool | None = None
    tag_id: uuid.UUID | None = None


# ── Price Computation ─────────────────────────────────────────────────

class PriceComputeRequest(BaseModel):
    """Request to compute price for a product using a pricelist."""
    product_variant_id: uuid.UUID | None = None
    product_template_id: uuid.UUID | None = None
    pricelist_id: uuid.UUID
    quantity: float = 1.0
    date: datetime | None = None
    uom_id: uuid.UUID | None = None


class PriceComputeResponse(BaseModel):
    product_id: uuid.UUID
    original_price: float
    computed_price: float
    currency_code: str
    pricelist_name: str
    rule_applied: str | None = None
