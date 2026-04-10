"""Incoterm schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class IncotermCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=3)
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    is_active: bool = True


class IncotermRead(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class IncotermUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
