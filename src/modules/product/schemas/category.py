"""Product Category Pydantic schemas."""

from __future__ import annotations

import uuid
from pydantic import BaseModel, Field


class ProductCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    sequence: int = 10
    description: str | None = None


class ProductCategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    sequence: int | None = None
    description: str | None = None
    is_active: bool | None = None


class ProductCategoryRead(BaseModel):
    id: uuid.UUID
    name: str
    complete_name: str | None
    parent_id: uuid.UUID | None
    sequence: int
    is_active: bool
    description: str | None
    model_config = {"from_attributes": True}
