"""Product Attribute Pydantic schemas."""

from __future__ import annotations

import uuid
from pydantic import BaseModel, Field


# ── Attribute ─────────────────────────────────────────────────────────

class ProductAttributeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    sequence: int = 10
    display_type: str = Field(default="radio", pattern=r"^(radio|pills|select|color|multi)$")
    create_variant: str = Field(default="always", pattern=r"^(always|dynamic|no_variant)$")


class ProductAttributeUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    sequence: int | None = None
    display_type: str | None = None
    create_variant: str | None = None
    is_active: bool | None = None


class ProductAttributeValueRead(BaseModel):
    id: uuid.UUID
    attribute_id: uuid.UUID
    name: str
    sequence: int
    html_color: str | None
    is_custom: bool
    is_active: bool
    model_config = {"from_attributes": True}


class ProductAttributeRead(BaseModel):
    id: uuid.UUID
    name: str
    sequence: int
    display_type: str
    create_variant: str
    is_active: bool
    values: list[ProductAttributeValueRead] = []
    model_config = {"from_attributes": True}


# ── Attribute Value ───────────────────────────────────────────────────

class ProductAttributeValueCreate(BaseModel):
    attribute_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=200)
    sequence: int = 10
    html_color: str | None = None
    is_custom: bool = False


class ProductAttributeValueUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    sequence: int | None = None
    html_color: str | None = None
    is_custom: bool | None = None
    is_active: bool | None = None


# ── Template Attribute Line ───────────────────────────────────────────

class TemplateAttributeLineCreate(BaseModel):
    """Add an attribute to a product template with selected values."""
    attribute_id: uuid.UUID
    value_ids: list[uuid.UUID] = Field(..., min_length=1)
    sequence: int = 10


class TemplateAttributeLineRead(BaseModel):
    id: uuid.UUID
    product_template_id: uuid.UUID
    attribute_id: uuid.UUID
    sequence: int
    attribute: ProductAttributeRead | None = None
    value_ids: list[ProductAttributeValueRead] = []
    template_values: list[TemplateAttributeValueRead] = []
    model_config = {"from_attributes": True}


# ── Template Attribute Value ──────────────────────────────────────────

class TemplateAttributeValueRead(BaseModel):
    id: uuid.UUID
    attribute_line_id: uuid.UUID
    product_attribute_value_id: uuid.UUID
    product_template_id: uuid.UUID
    price_extra: float
    is_active: bool
    attribute_value: ProductAttributeValueRead | None = None
    model_config = {"from_attributes": True}


class TemplateAttributeValueUpdate(BaseModel):
    """Update price extra or exclusions for a PTAV."""
    price_extra: float | None = None
    is_active: bool | None = None
    excluded_value_ids: list[uuid.UUID] | None = None


# Resolve forward references
TemplateAttributeLineRead.model_rebuild()
