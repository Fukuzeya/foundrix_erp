"""Contacts module services."""

from src.modules.contacts.services.partner_service import PartnerService
from src.modules.contacts.services.address_service import AddressService
from src.modules.contacts.services.bank_service import BankAccountService
from src.modules.contacts.services.category_service import CategoryService

__all__ = [
    "PartnerService",
    "AddressService",
    "BankAccountService",
    "CategoryService",
]
