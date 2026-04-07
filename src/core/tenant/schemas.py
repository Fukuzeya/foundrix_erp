"""Pydantic schemas for tenant management API."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TenantCreate(BaseModel):
    slug: str = Field(..., min_length=2, max_length=63, pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(..., min_length=1, max_length=255)
    subscription_tier: str = Field(default="free", max_length=50)


class TenantRead(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    is_active: bool
    subscription_tier: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TenantUpdate(BaseModel):
    name: str | None = None
    subscription_tier: str | None = None


class TenantModuleActivate(BaseModel):
    module_name: str = Field(..., min_length=1, max_length=100)


class TenantModuleRead(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    module_name: str
    is_active: bool
    activated_at: datetime

    model_config = {"from_attributes": True}
