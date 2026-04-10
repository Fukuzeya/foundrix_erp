"""Product Template and Variant repositories."""

import uuid

from sqlalchemy import Select, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.repository.base import BaseRepository
from src.modules.product.models.product import ProductTemplate, ProductVariant, ProductTag


class ProductTemplateRepository(BaseRepository[ProductTemplate]):
    model = ProductTemplate

    def build_filtered_query(
        self,
        *,
        search: str | None = None,
        product_type: str | None = None,
        category_id: uuid.UUID | None = None,
        sale_ok: bool | None = None,
        purchase_ok: bool | None = None,
        is_active: bool | None = True,
        is_favorite: bool | None = None,
    ) -> Select:
        query = select(self.model)

        if search:
            term = f"%{search}%"
            query = query.where(
                or_(
                    self.model.name.ilike(term),
                    self.model.default_code.ilike(term),
                    self.model.barcode.ilike(term),
                )
            )
        if product_type is not None:
            query = query.where(self.model.product_type == product_type)
        if category_id is not None:
            query = query.where(self.model.category_id == category_id)
        if sale_ok is not None:
            query = query.where(self.model.sale_ok.is_(sale_ok))
        if purchase_ok is not None:
            query = query.where(self.model.purchase_ok.is_(purchase_ok))
        if is_active is not None:
            query = query.where(self.model.is_active.is_(is_active))
        if is_favorite is not None:
            query = query.where(self.model.is_favorite.is_(is_favorite))

        query = query.order_by(
            self.model.is_favorite.desc(),
            self.model.sequence,
            self.model.name,
        )
        return query

    async def find_by_barcode(self, barcode: str, exclude_id: uuid.UUID | None = None) -> ProductTemplate | None:
        query = select(self.model).where(self.model.barcode == barcode)
        if exclude_id:
            query = query.where(self.model.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()


class ProductVariantRepository(BaseRepository[ProductVariant]):
    model = ProductVariant

    async def get_by_template(self, template_id: uuid.UUID, active_only: bool = True) -> list[ProductVariant]:
        query = select(self.model).where(self.model.template_id == template_id)
        if active_only:
            query = query.where(self.model.is_active.is_(True))
        query = query.order_by(self.model.default_code, self.model.combination_indices)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def find_by_combination(
        self, template_id: uuid.UUID, combination_indices: str
    ) -> ProductVariant | None:
        result = await self.db.execute(
            select(self.model).where(
                self.model.template_id == template_id,
                self.model.combination_indices == combination_indices,
            )
        )
        return result.scalar_one_or_none()

    async def find_by_barcode(self, barcode: str, exclude_id: uuid.UUID | None = None) -> ProductVariant | None:
        query = select(self.model).where(self.model.barcode == barcode)
        if exclude_id:
            query = query.where(self.model.id != exclude_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    def build_search_query(self, *, search: str | None = None, is_active: bool | None = True) -> Select:
        query = select(self.model)
        if search:
            term = f"%{search}%"
            query = query.where(
                or_(
                    self.model.default_code.ilike(term),
                    self.model.barcode.ilike(term),
                )
            )
        if is_active is not None:
            query = query.where(self.model.is_active.is_(is_active))
        return query.order_by(self.model.default_code)


class ProductTagRepository(BaseRepository[ProductTag]):
    model = ProductTag

    async def find_by_name(self, name: str) -> ProductTag | None:
        result = await self.db.execute(
            select(self.model).where(self.model.name == name)
        )
        return result.scalar_one_or_none()

    async def get_by_ids(self, ids: list[uuid.UUID]) -> list[ProductTag]:
        if not ids:
            return []
        result = await self.db.execute(
            select(self.model).where(self.model.id.in_(ids))
        )
        return list(result.scalars().all())
