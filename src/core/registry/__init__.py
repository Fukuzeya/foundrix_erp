"""Module registry: discovery, loading, and runtime activation checks."""

from src.core.registry.module_base import ERPModule
from src.core.registry.registry import ModuleRegistry, registry
from src.core.registry.registry_service import RegistryService, registry_service

__all__ = [
    "ERPModule",
    "ModuleRegistry",
    "registry",
    "RegistryService",
    "registry_service",
]
