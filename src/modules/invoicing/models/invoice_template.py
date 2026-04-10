"""Invoice template model for customizable PDF invoice generation.

Stores layout and styling preferences used by the PDF generation engine
to produce branded, consistent invoice documents.
"""

from sqlalchemy import Boolean, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, TimestampMixin, UUIDMixin


class InvoiceTemplate(UUIDMixin, TimestampMixin, Base):
    """Customizable invoice template controlling PDF layout and branding."""

    __tablename__ = "invoice_templates"

    name: Mapped[str] = mapped_column(
        String(200), nullable=False, doc="Human-readable template name.",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"),
        doc="Whether this template is used when no template is specified.",
    )

    # ── Branding ─────────────────────────────────────────────────────
    company_logo_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
        doc="URL or path to the company logo image.",
    )
    primary_color: Mapped[str] = mapped_column(
        String(7), server_default=text("'#4F46E5'"),
        doc="Hex color for headings and accents.",
    )
    secondary_color: Mapped[str] = mapped_column(
        String(7), server_default=text("'#6B7280'"),
        doc="Hex color for secondary text and borders.",
    )
    font_family: Mapped[str] = mapped_column(
        String(100), server_default=text("'Helvetica'"),
        doc="Font family used in the PDF.",
    )

    # ── Visibility toggles ───────────────────────────────────────────
    show_logo: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"),
    )
    show_payment_qr: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"),
        doc="Whether to render a QR code for payment.",
    )
    show_payment_terms: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"),
    )
    show_tax_details: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"),
    )

    # ── Custom text blocks ───────────────────────────────────────────
    header_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Custom header text (company tagline, etc.).",
    )
    footer_text: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        doc="Custom footer text (bank details, legal disclaimers).",
    )
    terms_and_conditions: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Terms & conditions printed on the invoice.",
    )

    # ── Paper format ─────────────────────────────────────────────────
    paper_format: Mapped[str] = mapped_column(
        String(10), server_default=text("'A4'"),
        doc="Paper size: A4 or Letter.",
    )

    # ── Status ───────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"),
    )

    def __repr__(self) -> str:
        return f"<InvoiceTemplate name={self.name!r} default={self.is_default}>"
