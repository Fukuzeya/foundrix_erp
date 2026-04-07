"""Contacts module domain models."""

from src.modules.contacts.models.partner import (
    Partner,
    PartnerAddress,
    PartnerBankAccount,
    PartnerCategory,
    PartnerIndustry,
)

__all__ = [
    "Partner",
    "PartnerAddress",
    "PartnerBankAccount",
    "PartnerCategory",
    "PartnerIndustry",
]
