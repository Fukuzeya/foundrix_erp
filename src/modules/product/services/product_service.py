"""Product service — orchestrates template/variant CRUD with business rules.

Handles:
- Template creation with attribute lines and automatic variant generation
- Template updates with variant regeneration when attributes change
- Single-variant field synchronization
- Archive/restore cascading between template and variants
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from src.core.events import event_bus
from src.modules.product.models.attribute import (
    ProductTemplateAttributeLine,
    ProductTemplateAttributeValue,
)
from src.modules.product.models.product import ProductTemplate, ProductVariant
from src.modules.product.repositories.attribute_repo import (
    ProductAttributeRepository,
    ProductAttributeValueRepository,
    TemplateAttributeLineRepository,
    TemplateAttributeValueRepository,
)
from src.modules.product.repositories.product_repo import (
    ProductTemplateRepository,
    ProductTagRepository,
    ProductVariantRepository,
)
from src.modules.product.repositories.uom_repo import UomRepository
from src.modules.product.schemas.attribute import TemplateAttributeLineCreate
from src.modules.product.schemas.product import (
    ProductTemplateCreate,
    ProductTemplateUpdate,
    VariantUpdate,
)
from src.modules.product.services.variant_service import VariantService

logger = logging.getLogger(__name__)


class ProductService:
    """Orchestrates product template and variant operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.template_repo = ProductTemplateRepository(db)
        self.variant_repo = ProductVariantRepository(db)
        self.attr_repo = ProductAttributeRepository(db)
        self.attr_value_repo = ProductAttributeValueRepository(db)
        self.line_repo = TemplateAttributeLineRepository(db)
        self.ptav_repo = TemplateAttributeValueRepository(db)
        self.tag_repo = ProductTagRepository(db)
        self.uom_repo = UomRepository(db)
        self.variant_svc = VariantService(db)

    # ── Template CRUD ─────────────────────────────────────────────────

    def build_filtered_query(self, **kwargs):
        """Delegate filtered query construction to the template repository."""
        return self.template_repo.build_filtered_query(**kwargs)

    async def list_variants(self, template_id: uuid.UUID) -> list[ProductVariant]:
        """List all variants for a given template."""
        return await self.variant_repo.get_by_template(template_id)

    async def create_template(self, data: ProductTemplateCreate) -> ProductTemplate:
        """Create a product template with optional attributes and auto-generate variants."""
        # Validate UoM exists
        uom = await self.uom_repo.get_by_id(data.uom_id)
        if not uom:
            raise NotFoundError("UoM", str(data.uom_id))

        # Validate purchase UoM if specified
        if data.uom_purchase_id:
            purchase_uom = await self.uom_repo.get_by_id(data.uom_purchase_id)
            if not purchase_uom:
                raise NotFoundError("UoM", str(data.uom_purchase_id))
            if purchase_uom.category_id != uom.category_id:
                raise ValidationError("Purchase UoM must be in the same category as the default UoM")

        # Build template
        template_data = data.model_dump(exclude={"tag_ids", "attribute_lines"})
        template = await self.template_repo.create(**template_data)

        # Link tags
        if data.tag_ids:
            tags = await self.tag_repo.get_by_ids(data.tag_ids)
            template.tags = tags

        # Create attribute lines and PTAVs
        if data.attribute_lines:
            await self._create_attribute_lines(template, data.attribute_lines)

        # Generate variants
        await self.variant_svc.generate_variants(template)

        # Sync single variant fields
        await self.variant_svc.sync_single_variant(template)

        await self.db.flush()
        await self.db.refresh(template)

        await event_bus.publish("product.template.created", {
            "template_id": str(template.id),
            "name": template.name,
        })

        return template

    async def get_template(self, template_id: uuid.UUID) -> ProductTemplate:
        return await self.template_repo.get_by_id_or_raise(template_id, "ProductTemplate")

    async def update_template(
        self, template_id: uuid.UUID, data: ProductTemplateUpdate
    ) -> ProductTemplate:
        """Update a product template. Regenerates variants if list_price changes."""
        template = await self.template_repo.get_by_id_or_raise(template_id, "ProductTemplate")

        update_data = data.model_dump(exclude_unset=True, exclude={"tag_ids"})
        if not update_data and data.tag_ids is None:
            return template

        # Validate UoM change
        if "uom_id" in update_data:
            uom = await self.uom_repo.get_by_id(update_data["uom_id"])
            if not uom:
                raise NotFoundError("UoM", str(update_data["uom_id"]))

        for key, value in update_data.items():
            setattr(template, key, value)

        # Update tags
        if data.tag_ids is not None:
            tags = await self.tag_repo.get_by_ids(data.tag_ids)
            template.tags = tags

        # If list_price changed, update all variant lst_prices
        if "list_price" in update_data:
            variants = await self.variant_repo.get_by_template(template.id)
            for v in variants:
                v.lst_price = template.list_price + v.price_extra
            await self.db.flush()

        await self.variant_svc.sync_single_variant(template)
        await self.db.flush()
        await self.db.refresh(template)

        await event_bus.publish("product.template.updated", {
            "template_id": str(template.id),
            "changed_fields": list(update_data.keys()),
        })

        return template

    async def archive_template(self, template_id: uuid.UUID) -> ProductTemplate:
        """Archive a template and all its variants."""
        template = await self.template_repo.get_by_id_or_raise(template_id, "ProductTemplate")
        template.is_active = False
        for v in template.variants:
            v.is_active = False
        await self.db.flush()

        await event_bus.publish("product.template.archived", {"template_id": str(template.id)})
        return template

    async def restore_template(self, template_id: uuid.UUID) -> ProductTemplate:
        """Restore an archived template and regenerate variants."""
        template = await self.template_repo.get_by_id_or_raise(template_id, "ProductTemplate")
        template.is_active = True
        await self.db.flush()

        await self.variant_svc.generate_variants(template)
        await self.db.refresh(template)

        await event_bus.publish("product.template.restored", {"template_id": str(template.id)})
        return template

    async def delete_template(self, template_id: uuid.UUID) -> None:
        """Hard delete a template and all its variants."""
        await self.template_repo.delete(template_id)
        await event_bus.publish("product.template.deleted", {"template_id": str(template_id)})

    # ── Attribute Lines ───────────────────────────────────────────────

    async def add_attribute_line(
        self,
        template_id: uuid.UUID,
        data: TemplateAttributeLineCreate,
    ) -> ProductTemplate:
        """Add an attribute line to a template and regenerate variants."""
        template = await self.template_repo.get_by_id_or_raise(template_id, "ProductTemplate")

        # Validate attribute
        attr = await self.attr_repo.get_by_id(data.attribute_id)
        if not attr:
            raise NotFoundError("ProductAttribute", str(data.attribute_id))

        # Check duplicate
        existing_lines = await self.line_repo.get_by_template(template_id)
        if any(line.attribute_id == data.attribute_id for line in existing_lines):
            raise ConflictError(f"Attribute '{attr.name}' is already configured for this product")

        # Validate values belong to the attribute
        values = await self.attr_value_repo.get_by_ids(data.value_ids)
        for v in values:
            if v.attribute_id != data.attribute_id:
                raise ValidationError(f"Value '{v.name}' does not belong to attribute '{attr.name}'")

        # Create the line
        line = ProductTemplateAttributeLine(
            product_template_id=template_id,
            attribute_id=data.attribute_id,
            sequence=data.sequence,
        )
        self.db.add(line)
        await self.db.flush()
        await self.db.refresh(line)

        # Link selected values
        line.value_ids = values

        # Create PTAVs for each selected value
        for value in values:
            ptav = ProductTemplateAttributeValue(
                attribute_line_id=line.id,
                product_attribute_value_id=value.id,
                product_template_id=template_id,
            )
            self.db.add(ptav)

        await self.db.flush()

        # Regenerate variants
        await self.variant_svc.generate_variants(template)

        await self.db.refresh(template)
        return template

    async def remove_attribute_line(
        self,
        template_id: uuid.UUID,
        attribute_line_id: uuid.UUID,
    ) -> ProductTemplate:
        """Remove an attribute line and regenerate variants."""
        template = await self.template_repo.get_by_id_or_raise(template_id, "ProductTemplate")
        await self.line_repo.delete(attribute_line_id)
        await self.db.flush()

        await self.variant_svc.generate_variants(template)
        await self.db.refresh(template)
        return template

    # ── Variant CRUD ──────────────────────────────────────────────────

    async def get_variant(self, variant_id: uuid.UUID) -> ProductVariant:
        return await self.variant_repo.get_by_id_or_raise(variant_id, "ProductVariant")

    async def update_variant(
        self, variant_id: uuid.UUID, data: VariantUpdate
    ) -> ProductVariant:
        """Update variant-specific fields (barcode, SKU, cost)."""
        variant = await self.variant_repo.get_by_id_or_raise(variant_id, "ProductVariant")
        update_data = data.model_dump(exclude_unset=True)

        # Barcode uniqueness
        if "barcode" in update_data and update_data["barcode"]:
            existing = await self.variant_repo.find_by_barcode(
                update_data["barcode"], exclude_id=variant_id
            )
            if existing:
                raise ConflictError(f"Barcode '{update_data['barcode']}' is already in use")

        for key, value in update_data.items():
            setattr(variant, key, value)

        await self.db.flush()

        # Sync to template if single variant
        template = await self.template_repo.get_by_id(variant.template_id)
        if template:
            await self.variant_svc.sync_single_variant(template)

        await self.db.refresh(variant)
        return variant

    # ── Private helpers ───────────────────────────────────────────────

    async def _create_attribute_lines(
        self,
        template: ProductTemplate,
        lines_data: list[TemplateAttributeLineCreate],
    ) -> None:
        """Bulk create attribute lines and their PTAVs for a new template."""
        for line_data in lines_data:
            attr = await self.attr_repo.get_by_id(line_data.attribute_id)
            if not attr:
                raise NotFoundError("ProductAttribute", str(line_data.attribute_id))

            values = await self.attr_value_repo.get_by_ids(line_data.value_ids)
            for v in values:
                if v.attribute_id != line_data.attribute_id:
                    raise ValidationError(
                        f"Value '{v.name}' does not belong to attribute '{attr.name}'"
                    )

            line = ProductTemplateAttributeLine(
                product_template_id=template.id,
                attribute_id=line_data.attribute_id,
                sequence=line_data.sequence,
            )
            self.db.add(line)
            await self.db.flush()
            await self.db.refresh(line)

            line.value_ids = values

            for value in values:
                ptav = ProductTemplateAttributeValue(
                    attribute_line_id=line.id,
                    product_attribute_value_id=value.id,
                    product_template_id=template.id,
                )
                self.db.add(ptav)

        await self.db.flush()
