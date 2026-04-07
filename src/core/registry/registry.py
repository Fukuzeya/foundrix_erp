"""Module registry: discovers, loads, and manages all ERP modules.

At startup the registry scans the ``src/modules/`` directory, imports each
module's ``__manifest__.py``, finds the ``ERPModule`` subclass, and registers
it. Routers are then mounted on the FastAPI app.
"""

import importlib
import inspect
import logging
import pkgutil
from pathlib import Path

from fastapi import FastAPI

from src.core.registry.module_base import ERPModule

logger = logging.getLogger(__name__)


class ModuleRegistry:
    """Central registry that holds all discovered ERP modules.

    This is the kernel's equivalent of Odoo's module registry — it owns the
    mapping from module name to ``ERPModule`` instance and handles router
    mounting.
    """

    def __init__(self) -> None:
        self._modules: dict[str, ERPModule] = {}

    @property
    def modules(self) -> dict[str, ERPModule]:
        """Return a read-only view of all registered modules."""
        return dict(self._modules)

    def register(self, module: ERPModule) -> None:
        """Register a single module instance.

        Args:
            module: An instantiated ``ERPModule`` subclass.

        Raises:
            ValueError: If a module with the same name is already registered.
        """
        if module.name in self._modules:
            raise ValueError(
                f"Module '{module.name}' is already registered. "
                f"Duplicate found: {module!r} vs {self._modules[module.name]!r}"
            )
        self._modules[module.name] = module
        logger.info("Registered module: %s@%s", module.name, module.version)

    def get(self, name: str) -> ERPModule | None:
        """Look up a registered module by name.

        Args:
            name: The module's unique name.

        Returns:
            The module instance, or ``None`` if not found.
        """
        return self._modules.get(name)

    def scan_modules(self, modules_package: str = "src.modules") -> None:
        """Discover and register all modules under the given package.

        Walks the ``src/modules/`` directory, imports each sub-package's
        ``__manifest__`` module, and looks for a class that extends
        ``ERPModule``. If found, it is instantiated and registered.

        Args:
            modules_package: Dotted Python package path to scan
                             (default: ``'src.modules'``).
        """
        package = importlib.import_module(modules_package)
        package_path = package.__path__

        for importer, module_name, is_pkg in pkgutil.iter_modules(package_path):
            if not is_pkg:
                continue

            manifest_path = f"{modules_package}.{module_name}.__manifest__"
            try:
                manifest_module = importlib.import_module(manifest_path)
            except ModuleNotFoundError:
                logger.warning(
                    "Module '%s' has no __manifest__.py — skipping", module_name
                )
                continue
            except Exception:
                logger.exception(
                    "Failed to import __manifest__.py for module '%s'", module_name
                )
                continue

            erp_module_class = self._find_erp_module_class(manifest_module)
            if erp_module_class is None:
                logger.warning(
                    "No ERPModule subclass found in %s — skipping", manifest_path
                )
                continue

            try:
                instance = erp_module_class()
                self._validate_dependencies(instance)
                self.register(instance)
            except Exception:
                logger.exception(
                    "Failed to instantiate module class from %s", manifest_path
                )

    def mount_all_routers(self, app: FastAPI) -> None:
        """Mount every registered module's router onto the FastAPI app.

        Each module's router is mounted under ``/api/v1/{module.name}``.

        Args:
            app: The FastAPI application instance.
        """
        for module in self._modules.values():
            router = module.get_router()
            prefix = f"/api/v1/{module.name}"
            app.include_router(router, prefix=prefix, tags=[module.name])
            logger.info("Mounted router for '%s' at %s", module.name, prefix)

    async def seed_permissions(self) -> None:
        """Seed permissions from all registered modules into the database.

        Iterates over every module's ``get_permissions()`` and registers
        each permission via ``AuthService.register_permission()``.
        Also seeds system roles if they don't exist.

        Should be called once during application startup after module scanning.
        """
        from src.core.auth.service import auth_service
        from src.core.database.session import AsyncSessionLocal

        session = AsyncSessionLocal()
        try:
            # Seed system roles first
            await auth_service.seed_system_roles(session)

            # Seed module permissions
            for module in self._modules.values():
                permissions = module.get_permissions()
                for perm in permissions:
                    await auth_service.register_permission(
                        codename=perm["codename"],
                        module_name=module.name,
                        description=perm["description"],
                        db=session,
                    )
                if permissions:
                    logger.info(
                        "Seeded %d permission(s) for module '%s'",
                        len(permissions),
                        module.name,
                    )

            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Failed to seed permissions")
        finally:
            await session.close()

    def run_startup_hooks(self) -> None:
        """Call ``on_startup()`` on every registered module."""
        for module in self._modules.values():
            try:
                module.on_startup()
                logger.info("Startup hook completed for '%s'", module.name)
            except Exception:
                logger.exception(
                    "Startup hook failed for module '%s'", module.name
                )

    def _find_erp_module_class(self, manifest_module: object) -> type[ERPModule] | None:
        """Find the first ERPModule subclass defined in a manifest module."""
        for _name, obj in inspect.getmembers(manifest_module, inspect.isclass):
            if issubclass(obj, ERPModule) and obj is not ERPModule:
                return obj
        return None

    def _validate_dependencies(self, module: ERPModule) -> None:
        """Check that all declared dependencies are already registered.

        Args:
            module: The module to validate.

        Raises:
            ValueError: If a required dependency is not registered.
        """
        for dep in module.depends:
            if dep == "core":
                continue  # 'core' is the kernel itself, always available
            if dep not in self._modules:
                raise ValueError(
                    f"Module '{module.name}' depends on '{dep}', "
                    f"which is not registered. Registered: {list(self._modules.keys())}"
                )


# Singleton registry instance used throughout the application
registry = ModuleRegistry()
