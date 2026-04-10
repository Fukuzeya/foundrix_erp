"""Pricelist Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PricelistItemCreate(BaseModel):
    sequence: int = 10
    applied_on: str = Field(default="3_global", pattern=r"^(0_variant|1_product|2_category|3_global)$")
    product_variant_id: uuid.UUID | None = None
    product_template_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None

    compute_price: str = Field(default="fixed", pattern=r"^(fixed|percentage|formula)$")
    base: str = Field(default="list_price", pattern=r"^(list_price|standard_price|pricelist)$")
    base_pricelist_id: uuid.UUID | None = None

    fixed_price: float = 0.0
    percent_price: float = 0.0
    price_discount: float = 0.0
    price_surcharge: float = 0.0
    price_round: float = 0.0
    price_min_margin: float | None = None
    price_max_margin: float | None = None

    min_quantity: float = 0.0
    date_start: datetime | None = None
    date_end: datetime | None = None


class PricelistItemUpdate(BaseModel):
    sequence: int | None = None
    applied_on: str | None = None
    product_variant_id: uuid.UUID | None = None
    product_template_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None

    compute_price: str | None = None
    base: str | None = None
    base_pricelist_id: uuid.UUID | None = None

    fixed_price: float | None = None
    percent_price: float | None = None
    price_discount: float | None = None
    price_surcharge: float | None = None
    price_round: float | None = None
    price_min_margin: float | None = None
    price_max_margin: float | None = None

    min_quantity: float | None = None
    date_start: datetime | None = None
    date_end: datetime | None = None


class PricelistItemRead(BaseModel):
    id: uuid.UUID
    pricelist_id: uuid.UUID
    sequence: int
    applied_on: str
    product_variant_id: uuid.UUID | None
    product_template_id: uuid.UUID | None
    category_id: uuid.UUID | None
    compute_price: str
    base: str
    base_pricelist_id: uuid.UUID | None
    fixed_price: float
    percent_price: float
    price_discount: float
    price_surcharge: float
    price_round: float
    price_min_margin: float | None
    price_max_margin: float | None
    min_quantity: float
    date_start: datetime | None
    date_end: datetime | None
    model_config = {"from_attributes": True}


class PricelistCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    sequence: int = 16
    currency_code: str = "USD"
    description: str | None = None
    items: list[PricelistItemCreate] | None = None


class PricelistUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    sequence: int | None = None
    currency_code: str | None = None
    description: str | None = None
    is_active: bool | None = None


class PricelistRead(BaseModel):
    id: uuid.UUID
    name: str
    sequence: int
    is_active: bool
    currency_code: str
    description: str | None
    items: list[PricelistItemRead] = []
    model_config = {"from_attributes": True}
