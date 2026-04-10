"""Pricing engine — pricelist rule evaluation.

Implements Odoo 19's multi-level pricing logic:
1. Find applicable rules ordered by specificity
2. Match rules against product/variant/category/global scope
3. Compute price using fixed/percentage/formula methods
4. Support recursive pricelist chaining with cycle protection
5. Apply rounding and margin clamping
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.modules.product.models.pricelist import Pricelist, PricelistItem
from src.modules.product.models.product import ProductTemplate, ProductVariant
from src.modules.product.repositories.category_repo import ProductCategoryRepository
from src.modules.product.repositories.pricelist_repo import (
    PricelistItemRepository,
    PricelistRepository,
)
from src.modules.product.repositories.product_repo import (
    ProductTemplateRepository,
    ProductVariantRepository,
)
from src.modules.product.schemas.product import PriceComputeResponse

logger = logging.getLogger(__name__)

# Maximum depth for pricelist recursion
MAX_PRICELIST_DEPTH = 10


class PricingService:
    """Evaluates pricelist rules to compute product prices."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.pricelist_repo = PricelistRepository(db)
        self.item_repo = PricelistItemRepository(db)
        self.template_repo = ProductTemplateRepository(db)
        self.variant_repo = ProductVariantRepository(db)
        self.category_repo = ProductCategoryRepository(db)

    async def compute_price(
        self,
        *,
        pricelist_id: uuid.UUID,
        product_variant_id: uuid.UUID | None = None,
        product_template_id: uuid.UUID | None = None,
        quantity: float = 1.0,
        date: datetime | None = None,
    ) -> PriceComputeResponse:
        """Compute the price for a product using a pricelist.

        Either product_variant_id or product_template_id must be provided.
        If variant is provided, the template is derived from it.
        """
        if date is None:
            date = datetime.now(timezone.utc)

        pricelist = await self.pricelist_repo.get_by_id(pricelist_id)
        if not pricelist:
            raise NotFoundError("Pricelist", str(pricelist_id))

        # Resolve product
        template: ProductTemplate
        variant: ProductVariant | None = None

        if product_variant_id:
            variant = await self.variant_repo.get_by_id_or_raise(product_variant_id, "ProductVariant")
            template = await self.template_repo.get_by_id_or_raise(variant.template_id, "ProductTemplate")
        elif product_template_id:
            template = await self.template_repo.get_by_id_or_raise(product_template_id, "ProductTemplate")
            # Use first active variant
            variants = await self.variant_repo.get_by_template(template.id)
            variant = variants[0] if variants else None
        else:
            raise BusinessRuleError("Either product_variant_id or product_template_id is required")

        original_price = variant.lst_price if variant else template.list_price

        # Evaluate pricelist
        computed_price, rule_desc = await self._evaluate_pricelist(
            pricelist=pricelist,
            template=template,
            variant=variant,
            quantity=quantity,
            date=date,
            depth=0,
        )

        return PriceComputeResponse(
            product_id=variant.id if variant else template.id,
            original_price=original_price,
            computed_price=round(computed_price, 2),
            currency_code=pricelist.currency_code,
            pricelist_name=pricelist.name,
            rule_applied=rule_desc,
        )

    async def _evaluate_pricelist(
        self,
        *,
        pricelist: Pricelist,
        template: ProductTemplate,
        variant: ProductVariant | None,
        quantity: float,
        date: datetime,
        depth: int,
    ) -> tuple[float, str | None]:
        """Evaluate a pricelist and return (computed_price, rule_description)."""
        if depth >= MAX_PRICELIST_DEPTH:
            raise BusinessRuleError("Pricelist recursion depth exceeded (circular reference?)")

        rules = await self.item_repo.get_applicable_rules(pricelist.id, now=date)

        for rule in rules:
            if await self._rule_matches(rule, template, variant, quantity):
                price = await self._compute_rule_price(
                    rule=rule,
                    template=template,
                    variant=variant,
                    quantity=quantity,
                    date=date,
                    depth=depth,
                )
                desc = f"{rule.compute_price} on {rule.applied_on}"
                return price, desc

        # No matching rule — return list price
        return variant.lst_price if variant else template.list_price, None

    async def _rule_matches(
        self,
        rule: PricelistItem,
        template: ProductTemplate,
        variant: ProductVariant | None,
        quantity: float,
    ) -> bool:
        """Check if a pricelist rule matches the given product and quantity."""
        # Quantity check
        if quantity < rule.min_quantity:
            return False

        # Scope check
        if rule.applied_on == "0_variant":
            return variant is not None and rule.product_variant_id == variant.id
        elif rule.applied_on == "1_product":
            return rule.product_template_id == template.id
        elif rule.applied_on == "2_category":
            if rule.category_id is None:
                return False
            if template.category_id == rule.category_id:
                return True
            # Check if product's category is a descendant
            if template.category_id:
                return await self.category_repo.is_descendant_of(
                    template.category_id, rule.category_id
                )
            return False
        elif rule.applied_on == "3_global":
            return True

        return False

    async def _compute_rule_price(
        self,
        *,
        rule: PricelistItem,
        template: ProductTemplate,
        variant: ProductVariant | None,
        quantity: float,
        date: datetime,
        depth: int,
    ) -> float:
        """Compute the price according to a matched rule."""
        # Resolve base price
        base_price = await self._get_base_price(
            rule=rule,
            template=template,
            variant=variant,
            quantity=quantity,
            date=date,
            depth=depth,
        )

        if rule.compute_price == "fixed":
            return rule.fixed_price

        elif rule.compute_price == "percentage":
            return base_price * (1.0 - rule.percent_price / 100.0)

        elif rule.compute_price == "formula":
            # Step 1: Apply percentage discount
            price = base_price * (1.0 - rule.price_discount / 100.0)

            # Step 2: Add surcharge
            price += rule.price_surcharge

            # Step 3: Apply rounding
            if rule.price_round and rule.price_round > 0:
                price = round(price / rule.price_round) * rule.price_round

            # Step 4: Clamp within margin bounds
            cost = variant.standard_price if variant else template.standard_price
            if rule.price_min_margin is not None:
                min_price = cost + rule.price_min_margin
                price = max(price, min_price)
            if rule.price_max_margin is not None:
                max_price = cost + rule.price_max_margin
                price = min(price, max_price)

            return price

        return base_price

    async def _get_base_price(
        self,
        *,
        rule: PricelistItem,
        template: ProductTemplate,
        variant: ProductVariant | None,
        quantity: float,
        date: datetime,
        depth: int,
    ) -> float:
        """Resolve the base price for a rule."""
        if rule.base == "list_price":
            return variant.lst_price if variant else template.list_price

        elif rule.base == "standard_price":
            return variant.standard_price if variant else template.standard_price

        elif rule.base == "pricelist":
            if not rule.base_pricelist_id:
                raise BusinessRuleError("Pricelist rule references another pricelist but none is set")
            base_pricelist = await self.pricelist_repo.get_by_id(rule.base_pricelist_id)
            if not base_pricelist:
                raise NotFoundError("Pricelist", str(rule.base_pricelist_id))

            price, _ = await self._evaluate_pricelist(
                pricelist=base_pricelist,
                template=template,
                variant=variant,
                quantity=quantity,
                date=date,
                depth=depth + 1,
            )
            return price

        return variant.lst_price if variant else template.list_price
