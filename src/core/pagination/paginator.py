"""Reusable pagination for SQLAlchemy queries and FastAPI responses.

Usage in a route::

    from src.core.pagination import PageParams, PaginatedResponse, paginate

    @router.get("/partners", response_model=PaginatedResponse[PartnerRead])
    async def list_partners(
        params: PageParams = Depends(),
        db: AsyncSession = Depends(get_tenant_session),
    ):
        query = select(Partner).order_by(Partner.created_at.desc())
        return await paginate(db, query, params, PartnerRead)
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T", bound=BaseModel)


class PageParams:
    """FastAPI dependency for extracting pagination parameters from query string."""

    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number (1-based)"),
        size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    ) -> None:
        self.page = page
        self.size = size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class PaginatedResponse(BaseModel, Generic[T]):
    """Standardized paginated response envelope."""

    items: list[T]
    total: int
    page: int
    size: int
    pages: int

    model_config = {"from_attributes": True}


async def paginate(
    db: AsyncSession,
    query: Select,
    params: PageParams,
    schema: type[T],
    *,
    serialize_fn: Any | None = None,
) -> PaginatedResponse[T]:
    """Execute a paginated query and return a standardized response.

    Args:
        db: The async database session.
        query: A SQLAlchemy Select statement (before limit/offset).
        params: Pagination parameters (page, size).
        schema: The Pydantic model to serialize each row into.
        serialize_fn: Optional custom serializer function. If provided,
                      each row is passed through this function instead
                      of ``schema.model_validate``.

    Returns:
        A PaginatedResponse with items, total count, and page metadata.
    """
    # Count total rows
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Fetch page
    paginated_query = query.offset(params.offset).limit(params.size)
    result = await db.execute(paginated_query)
    rows = result.scalars().all()

    # Serialize
    if serialize_fn:
        items = [serialize_fn(row) for row in rows]
    else:
        items = [schema.model_validate(row) for row in rows]

    pages = (total + params.size - 1) // params.size if total > 0 else 0

    return PaginatedResponse(
        items=items,
        total=total,
        page=params.page,
        size=params.size,
        pages=pages,
    )
