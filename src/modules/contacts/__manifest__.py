"""Contacts module manifest — discovered by the module registry at startup."""

from fastapi import APIRouter

from src.core.database.base import Base
from src.core.registry.module_base import ERPModule


class ContactsModule(ERPModule):
    name = "contacts"
    version = "1.0.0"
    depends = ["core"]
    description = "Contact and partner management — companies, people, addresses, bank accounts"

    def get_router(self) -> APIRouter:
        from src.modules.contacts.router import router

        return router

    def get_models(self) -> list[type[Base]]:
        from src.modules.contacts.models.partner import (
            Partner,
            PartnerAddress,
            PartnerBankAccount,
            PartnerCategory,
            PartnerIndustry,
        )

        return [Partner, PartnerAddress, PartnerBankAccount, PartnerCategory, PartnerIndustry]

    def get_permissions(self) -> list[dict]:
        return [
            # Partners
            {"codename": "contacts.partner.create", "description": "Create partners"},
            {"codename": "contacts.partner.read", "description": "View partners"},
            {"codename": "contacts.partner.update", "description": "Edit partners"},
            {"codename": "contacts.partner.delete", "description": "Delete partners"},
            # Categories / Industries
            {"codename": "contacts.category.read", "description": "View partner categories"},
            {"codename": "contacts.category.manage", "description": "Manage partner categories and industries"},
        ]

    def on_startup(self) -> None:
        from src.core.events import event_bus

        # Register cross-module event handlers here
        # e.g. event_bus.subscribe("invoice.created", ...)
        pass
