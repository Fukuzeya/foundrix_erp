"""UoM Pydantic schemas."""

from __future__ import annotations

import uuid
from pydantic import BaseModel, Field


class UomCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class UomCategoryRead(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    model_config = {"from_attributes": True}


class UomCategoryReadWithUoms(UomCategoryRead):
    uoms: list[UomRead] = []


class UomCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    category_id: uuid.UUID
    uom_type: str = Field(default="reference", pattern=r"^(reference|bigger|smaller)$")
    ratio: float = Field(default=1.0, gt=0)
    rounding: float = Field(default=0.01, ge=0)


class UomUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    ratio: float | None = Field(None, gt=0)
    rounding: float | None = Field(None, ge=0)
    is_active: bool | None = None


class UomRead(BaseModel):
    id: uuid.UUID
    name: str
    category_id: uuid.UUID
    uom_type: str
    ratio: float
    rounding: float
    is_active: bool
    model_config = {"from_attributes": True}


class UomConvertRequest(BaseModel):
    """Request body for UoM conversion."""
    quantity: float
    from_uom_id: uuid.UUID
    to_uom_id: uuid.UUID


class UomConvertResponse(BaseModel):
    quantity: float
    from_uom: str
    to_uom: str
    result: float


# Resolve forward reference
UomCategoryReadWithUoms.model_rebuild()
