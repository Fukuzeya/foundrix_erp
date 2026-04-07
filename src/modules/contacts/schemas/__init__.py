"""Contacts module Pydantic schemas."""

from src.modules.contacts.schemas.partner import (
    AddressCreate,
    AddressRead,
    AddressUpdate,
    BankAccountCreate,
    BankAccountRead,
    BankAccountUpdate,
    CategoryCreate,
    CategoryRead,
    CategoryUpdate,
    IndustryCreate,
    IndustryRead,
    PartnerCreate,
    PartnerRead,
    PartnerReadBrief,
    PartnerUpdate,
    PartnerFilter,
)

__all__ = [
    "AddressCreate",
    "AddressRead",
    "AddressUpdate",
    "BankAccountCreate",
    "BankAccountRead",
    "BankAccountUpdate",
    "CategoryCreate",
    "CategoryRead",
    "CategoryUpdate",
    "IndustryCreate",
    "IndustryRead",
    "PartnerCreate",
    "PartnerRead",
    "PartnerReadBrief",
    "PartnerUpdate",
    "PartnerFilter",
]
