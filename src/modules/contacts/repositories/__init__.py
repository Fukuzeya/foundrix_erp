"""Contacts module repositories."""

from src.modules.contacts.repositories.partner_repo import PartnerRepository
from src.modules.contacts.repositories.address_repo import AddressRepository
from src.modules.contacts.repositories.bank_repo import BankAccountRepository
from src.modules.contacts.repositories.category_repo import CategoryRepository
from src.modules.contacts.repositories.industry_repo import IndustryRepository

__all__ = [
    "PartnerRepository",
    "AddressRepository",
    "BankAccountRepository",
    "CategoryRepository",
    "IndustryRepository",
]
