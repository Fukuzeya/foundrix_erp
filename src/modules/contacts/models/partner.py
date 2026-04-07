"""Partner model — the central contact entity in Foundrix ERP.

Inspired by Odoo's res.partner, the Partner model represents any person
or organization the business interacts with: customers, vendors, employees,
leads. It supports a parent/child hierarchy for company-person relationships
and the "commercial partner" concept for billing entities.

Lives in the tenant schema (no explicit schema set).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class Partner(UUIDMixin, TimestampMixin, Base):
    """A contact: person, company, or address record.

    The ``partner_type`` field determines the record's role:
    - ``contact``: A person or main company record (must have a name)
    - ``invoice``: A billing address (child of a contact)
    - ``delivery``: A shipping address (child of a contact)
    - ``other``: Other address type

    The ``is_company`` flag distinguishes companies from individuals.
    Companies can have child contacts (employees) and child addresses.
    """

    __tablename__ = "partners"
    __table_args__ = (
        CheckConstraint(
            "(partner_type = 'contact' AND name IS NOT NULL) OR (partner_type != 'contact')",
            name="ck_partners_contact_has_name",
        ),
        Index("ix_partners_parent_id", "parent_id"),
        Index("ix_partners_commercial_partner_id", "commercial_partner_id"),
        Index("ix_partners_email", "email"),
        Index("ix_partners_is_company", "is_company"),
        Index("ix_partners_ref", "ref"),
        Index("ix_partners_active", "is_active"),
    )

    # ── Identity ──────────────────────────────────────────────────────
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        doc="Computed: 'Company, Person' for child contacts.",
    )
    ref: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        doc="Internal reference code (e.g. CUST-001).",
    )
    is_company: Mapped[bool] = mapped_column(server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    color: Mapped[int] = mapped_column(server_default=text("0"))

    # ── Type & Hierarchy ──────────────────────────────────────────────
    partner_type: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'contact'"),
        doc="One of: contact, invoice, delivery, other.",
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("partners.id", ondelete="SET NULL"),
        nullable=True,
    )
    commercial_partner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("partners.id", ondelete="SET NULL"),
        nullable=True,
        doc="Top-level company/person in the hierarchy (billing entity).",
    )

    # ── Contact Info ──────────────────────────────────────────────────
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    function: Mapped[str | None] = mapped_column(
        String(200), nullable=True, doc="Job position / title.",
    )

    # ── Address ───────────────────────────────────────────────────────
    street: Mapped[str | None] = mapped_column(String(255), nullable=True)
    street2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(
        String(100), nullable=True, doc="State / province / region.",
    )
    zip_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country_code: Mapped[str | None] = mapped_column(
        String(3), nullable=True, doc="ISO 3166-1 alpha-2 code.",
    )
    country_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Classification ────────────────────────────────────────────────
    industry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("partner_industries.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_customer: Mapped[bool] = mapped_column(server_default=text("false"))
    is_vendor: Mapped[bool] = mapped_column(server_default=text("false"))

    # ── Tax & Registration ────────────────────────────────────────────
    vat: Mapped[str | None] = mapped_column(
        String(50), nullable=True, doc="Tax Identification Number.",
    )
    company_registry: Mapped[str | None] = mapped_column(
        String(100), nullable=True, doc="Company registration number.",
    )

    # ── Localization ──────────────────────────────────────────────────
    lang: Mapped[str | None] = mapped_column(
        String(10), nullable=True, doc="Preferred language code (e.g. 'en', 'fr', 'sw').",
    )
    tz: Mapped[str | None] = mapped_column(
        String(50), nullable=True, doc="Timezone (e.g. 'Africa/Nairobi').",
    )
    currency_code: Mapped[str | None] = mapped_column(
        String(3), nullable=True, doc="Preferred currency ISO code.",
    )

    # ── Notes ─────────────────────────────────────────────────────────
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Tags (stored as array for simplicity within tenant schema) ────
    tag_ids: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(36)), nullable=True,
        doc="Array of PartnerCategory UUIDs this partner is tagged with.",
    )

    # ── Relationships ─────────────────────────────────────────────────
    parent: Mapped["Partner | None"] = relationship(
        "Partner",
        remote_side="Partner.id",
        foreign_keys=[parent_id],
        lazy="selectin",
    )
    children: Mapped[list["Partner"]] = relationship(
        "Partner",
        foreign_keys=[parent_id],
        lazy="selectin",
        viewonly=True,
    )
    addresses: Mapped[list["PartnerAddress"]] = relationship(
        back_populates="partner",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    bank_accounts: Mapped[list["PartnerBankAccount"]] = relationship(
        back_populates="partner",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    industry: Mapped["PartnerIndustry | None"] = relationship(lazy="selectin")

    def __repr__(self) -> str:
        return f"<Partner name={self.name!r} company={self.is_company} type={self.partner_type}>"


class PartnerAddress(UUIDMixin, TimestampMixin, Base):
    """A typed address belonging to a partner.

    Separates addresses into their own table for partners that need
    multiple invoice/delivery addresses beyond the main address on Partner.
    """

    __tablename__ = "partner_addresses"
    __table_args__ = (
        Index("ix_partner_addresses_partner_type", "partner_id", "address_type"),
    )

    partner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("partners.id", ondelete="CASCADE"),
        nullable=False,
    )
    address_type: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'other'"),
        doc="One of: invoice, delivery, other.",
    )
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    street: Mapped[str | None] = mapped_column(String(255), nullable=True)
    street2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    country_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_default: Mapped[bool] = mapped_column(server_default=text("false"))

    partner: Mapped["Partner"] = relationship(back_populates="addresses")

    def __repr__(self) -> str:
        return f"<PartnerAddress partner={self.partner_id} type={self.address_type}>"


class PartnerBankAccount(UUIDMixin, TimestampMixin, Base):
    """Bank account linked to a partner for payment processing."""

    __tablename__ = "partner_bank_accounts"
    __table_args__ = (
        UniqueConstraint(
            "partner_id", "account_number",
            name="uq_partner_bank_accounts_partner_account",
        ),
    )

    partner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("partners.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_number: Mapped[str] = mapped_column(String(50), nullable=False)
    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_code: Mapped[str | None] = mapped_column(
        String(20), nullable=True, doc="SWIFT/BIC or sort code.",
    )
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    branch_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    is_primary: Mapped[bool] = mapped_column(server_default=text("false"))
    allow_outbound: Mapped[bool] = mapped_column(
        server_default=text("false"),
        doc="Whether this account can be used for outbound payments.",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    partner: Mapped["Partner"] = relationship(back_populates="bank_accounts")

    def __repr__(self) -> str:
        return f"<PartnerBankAccount partner={self.partner_id} bank={self.bank_name!r}>"


class PartnerCategory(UUIDMixin, TimestampMixin, Base):
    """Hierarchical tag/category for organizing partners.

    Supports parent/child relationships for nested categories like:
    Industry > Manufacturing > Textiles
    """

    __tablename__ = "partner_categories"
    __table_args__ = (
        UniqueConstraint("name", "parent_id", name="uq_partner_categories_name_parent"),
        Index("ix_partner_categories_parent_id", "parent_id"),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[int] = mapped_column(server_default=text("0"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("partner_categories.id", ondelete="CASCADE"),
        nullable=True,
    )
    full_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        doc="Materialized path: 'Parent / Child / Grandchild'.",
    )
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    parent: Mapped["PartnerCategory | None"] = relationship(
        "PartnerCategory",
        remote_side="PartnerCategory.id",
        foreign_keys=[parent_id],
    )
    children: Mapped[list["PartnerCategory"]] = relationship(
        "PartnerCategory",
        foreign_keys=[parent_id],
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<PartnerCategory name={self.name!r}>"


class PartnerIndustry(UUIDMixin, Base):
    """Industry classification lookup table for partners."""

    __tablename__ = "partner_industries"

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    full_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))

    def __repr__(self) -> str:
        return f"<PartnerIndustry name={self.name!r}>"
