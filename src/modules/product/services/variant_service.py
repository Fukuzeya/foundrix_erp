"""Variant generation service — Cartesian product engine.

Implements Odoo 19's variant generation logic:
1. Compute Cartesian product of all attribute value combinations
2. Filter out excluded combinations
3. Create variants with combination_indices for uniqueness
4. Handle dynamic variant creation on-demand
5. Sync single-variant templates (barcode, default_code → template)
"""

from __future__ import annotations

import itertools
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.events import event_bus
from src.modules.product.models.attribute import (
    ProductTemplateAttributeLine,
    ProductTemplateAttributeValue,
)
from src.modules.product.models.product import ProductTemplate, ProductVariant
from src.modules.product.repositories.attribute_repo import (
    TemplateAttributeLineRepository,
    TemplateAttributeValueRepository,
)
from src.modules.product.repositories.product_repo import ProductVariantRepository

logger = logging.getLogger(__name__)


class VariantService:
    """Generates and manages product variants from attribute combinations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.variant_repo = ProductVariantRepository(db)
        self.line_repo = TemplateAttributeLineRepository(db)
        self.ptav_repo = TemplateAttributeValueRepository(db)

    async def generate_variants(self, template: ProductTemplate) -> list[ProductVariant]:
        """Generate all valid variants for a product template.

        This is the core Cartesian product engine. It:
        1. Collects all attribute lines with create_variant != 'no_variant'
        2. Builds the Cartesian product of their template attribute values
        3. Filters out excluded combinations
        4. Creates or reactivates variants for each valid combination

        Returns the list of created/updated variants.
        """
        lines = await self.line_repo.get_by_template(template.id)

        # Filter to lines whose attribute creates variants
        variant_lines = [
            line for line in lines
            if line.attribute and line.attribute.create_variant in ("always", "dynamic")
        ]

        # If no variant-creating attributes, ensure exactly one default variant
        if not variant_lines:
            return await self._ensure_single_variant(template)

        # Only pre-create variants for 'always' mode
        always_lines = [
            line for line in variant_lines
            if line.attribute.create_variant == "always"
        ]

        if not always_lines:
            # All are dynamic — ensure at least one default variant exists
            return await self._ensure_single_variant(template)

        # Build Cartesian product from template_values of each line
        value_sets: list[list[ProductTemplateAttributeValue]] = []
        for line in always_lines:
            active_ptavs = [ptav for ptav in line.template_values if ptav.is_active]
            if active_ptavs:
                value_sets.append(active_ptavs)

        if not value_sets:
            return await self._ensure_single_variant(template)

        # Generate all combinations
        combinations = list(itertools.product(*value_sets))

        # Filter out excluded combinations
        valid_combinations = [
            combo for combo in combinations
            if not self._is_excluded(combo)
        ]

        # Get existing variants
        existing_variants = await self.variant_repo.get_by_template(template.id, active_only=False)
        existing_by_indices = {v.combination_indices: v for v in existing_variants}

        created: list[ProductVariant] = []
        seen_indices: set[str] = set()

        for combo in valid_combinations:
            indices = self._compute_combination_indices(combo)

            if indices in seen_indices:
                continue
            seen_indices.add(indices)

            # Check if variant already exists
            existing = existing_by_indices.get(indices)
            if existing:
                # Reactivate if archived
                if not existing.is_active:
                    existing.is_active = True
                # Update computed fields
                existing.price_extra = sum(ptav.price_extra for ptav in combo)
                existing.lst_price = template.list_price + existing.price_extra
                created.append(existing)
            else:
                # Create new variant
                price_extra = sum(ptav.price_extra for ptav in combo)
                variant = ProductVariant(
                    template_id=template.id,
                    combination_indices=indices,
                    price_extra=price_extra,
                    lst_price=template.list_price + price_extra,
                    standard_price=template.standard_price,
                    weight=template.weight,
                    volume=template.volume,
                )
                self.db.add(variant)
                await self.db.flush()
                await self.db.refresh(variant)

                # Link attribute values
                variant.attribute_values = list(combo)
                created.append(variant)

        # Archive variants whose combination is no longer valid
        for indices, variant in existing_by_indices.items():
            if indices not in seen_indices and indices != "":
                variant.is_active = False

        await self.db.flush()

        logger.info(
            "Generated %d variants for template '%s' (id=%s)",
            len(created), template.name, template.id,
        )

        return created

    async def create_dynamic_variant(
        self,
        template: ProductTemplate,
        ptav_ids: list[uuid.UUID],
    ) -> ProductVariant:
        """Create a variant on-demand for dynamic attributes.

        Used when a customer selects a specific attribute combination
        that hasn't been pre-created.
        """
        ptavs = await self.ptav_repo.get_by_ids(ptav_ids)

        if self._is_excluded(ptavs):
            from src.core.errors.exceptions import BusinessRuleError
            raise BusinessRuleError("This attribute combination is not available")

        indices = self._compute_combination_indices(ptavs)

        # Check for existing (possibly archived) variant
        existing = await self.variant_repo.find_by_combination(template.id, indices)
        if existing:
            if not existing.is_active:
                existing.is_active = True
                await self.db.flush()
            return existing

        price_extra = sum(ptav.price_extra for ptav in ptavs)
        variant = ProductVariant(
            template_id=template.id,
            combination_indices=indices,
            price_extra=price_extra,
            lst_price=template.list_price + price_extra,
            standard_price=template.standard_price,
            weight=template.weight,
            volume=template.volume,
        )
        self.db.add(variant)
        await self.db.flush()
        await self.db.refresh(variant)
        variant.attribute_values = ptavs
        await self.db.flush()

        await event_bus.publish("product.variant.created", {
            "variant_id": str(variant.id),
            "template_id": str(template.id),
        })

        return variant

    async def sync_single_variant(self, template: ProductTemplate) -> None:
        """Sync fields between a single-variant template and its variant.

        When a template has exactly one variant, barcode and default_code
        should be kept in sync bidirectionally.
        """
        active_variants = [v for v in template.variants if v.is_active]
        if len(active_variants) != 1:
            return

        variant = active_variants[0]

        # Template → variant (if template was updated)
        if template.barcode and not variant.barcode:
            variant.barcode = template.barcode
        if template.default_code and not variant.default_code:
            variant.default_code = template.default_code

        # Variant → template (if variant was updated)
        if variant.barcode and template.barcode != variant.barcode:
            template.barcode = variant.barcode
        if variant.default_code and template.default_code != variant.default_code:
            template.default_code = variant.default_code

        # Cost sync
        if variant.standard_price != template.standard_price:
            template.standard_price = variant.standard_price

        await self.db.flush()

    async def _ensure_single_variant(self, template: ProductTemplate) -> list[ProductVariant]:
        """Ensure a template with no variant attributes has exactly one variant."""
        existing = await self.variant_repo.get_by_template(template.id, active_only=False)

        if existing:
            # Reactivate the first, archive the rest
            first = existing[0]
            if not first.is_active:
                first.is_active = True
            first.lst_price = template.list_price
            first.standard_price = template.standard_price
            first.combination_indices = ""

            for extra in existing[1:]:
                extra.is_active = False

            await self.db.flush()
            return [first]

        # Create the implicit variant
        variant = ProductVariant(
            template_id=template.id,
            combination_indices="",
            lst_price=template.list_price,
            standard_price=template.standard_price,
            weight=template.weight,
            volume=template.volume,
            default_code=template.default_code,
            barcode=template.barcode,
        )
        self.db.add(variant)
        await self.db.flush()
        await self.db.refresh(variant)
        return [variant]

    def _compute_combination_indices(self, ptavs: list[ProductTemplateAttributeValue]) -> str:
        """Compute a stable, sorted string of PTAV IDs for uniqueness."""
        sorted_ids = sorted(str(ptav.id) for ptav in ptavs)
        return ",".join(sorted_ids)

    def _is_excluded(self, combo: list | tuple) -> bool:
        """Check if any value in the combination excludes another value in the same combination."""
        combo_ids = {ptav.id for ptav in combo}
        for ptav in combo:
            if ptav.excluded_values:
                for excluded in ptav.excluded_values:
                    if excluded.id in combo_ids:
                        return True
        return False
