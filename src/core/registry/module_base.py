"""Abstract base class for all Foundrix ERP modules.

Every module must subclass ``ERPModule`` and implement the required methods.
The registry discovers modules by importing ``__manifest__.py`` from each
module package and looking for an ``ERPModule`` subclass.
"""

from abc import ABC, abstractmethod

from fastapi import APIRouter

from src.core.database.base import Base


class ERPModule(ABC):
    """Base class that every Foundrix module must extend.

    Subclasses declare metadata as class attributes and implement
    ``get_router()``, ``get_models()``, and ``get_permissions()`` to expose
    their functionality to the kernel.

    Example usage in ``__manifest__.py``::

        from src.core.registry.module_base import ERPModule

        class ContactsModule(ERPModule):
            name = "contacts"
            version = "1.0.0"
            depends = ["core"]
            description = "Contact and partner management"

            def get_router(self) -> APIRouter:
                from src.modules.contacts.router import router
                return router

            def get_models(self) -> list[type[Base]]:
                from src.modules.contacts.models.partner import Partner
                return [Partner]

            def get_permissions(self) -> list[dict]:
                return [
                    {"codename": "contacts.partner.create", "description": "Create partners"},
                    {"codename": "contacts.partner.read", "description": "View partners"},
                    {"codename": "contacts.partner.update", "description": "Edit partners"},
                    {"codename": "contacts.partner.delete", "description": "Delete partners"},
                ]
    """

    name: str
    """Unique machine-readable module identifier (e.g. ``'contacts'``)."""

    version: str
    """Semantic version string (e.g. ``'1.0.0'``)."""

    depends: list[str]
    """List of module names this module depends on (e.g. ``['core']``)."""

    description: str
    """Short human-readable description of the module."""

    @abstractmethod
    def get_router(self) -> APIRouter:
        """Return the FastAPI router containing this module's endpoints.

        The registry will mount this router under ``/api/v1/{module.name}``.
        """
        ...

    @abstractmethod
    def get_models(self) -> list[type[Base]]:
        """Return the list of SQLAlchemy model classes owned by this module.

        These models are used by Alembic to generate tenant-schema migrations.
        """
        ...

    def get_permissions(self) -> list[dict]:
        """Return the permissions this module declares.

        Each permission is a dict with:
        - ``codename``: Dotted string (e.g. ``'contacts.partner.create'``)
        - ``description``: Human-readable description

        The registry seeds these into the ``permissions`` table at startup.
        They can then be assigned to roles for granular access control.

        Returns:
            A list of permission dicts. Empty list by default.
        """
        return []

    def on_install(self, tenant_id: str) -> None:
        """Hook called when this module is activated for a tenant.

        Override to seed default data, create initial records, etc.

        Args:
            tenant_id: The UUID string of the tenant activating this module.
        """

    def on_startup(self) -> None:
        """Hook called once when the application starts up.

        Override to register event handlers, schedule background tasks, etc.
        """

    def __repr__(self) -> str:
        return f"<ERPModule {self.name}@{self.version}>"
