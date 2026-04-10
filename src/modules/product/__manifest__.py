"""Product module manifest — discovered by the module registry at startup."""

from fastapi import APIRouter

from src.core.database.base import Base
from src.core.registry.module_base import ERPModule


class ProductModule(ERPModule):
    name = "product"
    version = "1.0.0"
    depends = ["core"]
    description = "Product catalog — templates, variants, attributes, UoM, pricelists, pricing engine"

    def get_router(self) -> APIRouter:
        from src.modules.product.router import router
        return router

    def get_models(self) -> list[type[Base]]:
        from src.modules.product.models.uom import Uom, UomCategory
        from src.modules.product.models.category import ProductCategory
        from src.modules.product.models.attribute import (
            ProductAttribute,
            ProductAttributeValue,
            ProductTemplateAttributeLine,
            ProductTemplateAttributeValue,
        )
        from src.modules.product.models.product import (
            ProductTag,
            ProductTemplate,
            ProductVariant,
        )
        from src.modules.product.models.pricelist import Pricelist, PricelistItem

        return [
            UomCategory,
            Uom,
            ProductCategory,
            ProductAttribute,
            ProductAttributeValue,
            ProductTag,
            ProductTemplate,
            ProductTemplateAttributeLine,
            ProductTemplateAttributeValue,
            ProductVariant,
            Pricelist,
            PricelistItem,
        ]

    def get_permissions(self) -> list[dict]:
        return [
            # UoM
            {"codename": "product.uom.read", "description": "View units of measure"},
            {"codename": "product.uom.manage", "description": "Manage units of measure"},
            # Categories
            {"codename": "product.category.read", "description": "View product categories"},
            {"codename": "product.category.manage", "description": "Manage product categories"},
            # Attributes
            {"codename": "product.attribute.read", "description": "View product attributes"},
            {"codename": "product.attribute.manage", "description": "Manage product attributes"},
            # Products
            {"codename": "product.product.create", "description": "Create products"},
            {"codename": "product.product.read", "description": "View products"},
            {"codename": "product.product.update", "description": "Edit products"},
            {"codename": "product.product.delete", "description": "Delete products"},
            # Pricelists
            {"codename": "product.pricelist.read", "description": "View pricelists and compute prices"},
            {"codename": "product.pricelist.manage", "description": "Manage pricelists and pricing rules"},
        ]

    def on_startup(self) -> None:
        pass
