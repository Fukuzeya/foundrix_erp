"""PDF invoice generation engine.

Uses reportlab to produce professional invoice PDFs with customizable
templates controlling branding, layout, and content visibility.
"""

from __future__ import annotations

import io
import uuid
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import NotFoundError
from src.core.repository.base import BaseRepository
from src.modules.accounting.models.move import Move, MoveLine, OUTBOUND_TYPES
from src.modules.invoicing.models.invoice_template import InvoiceTemplate
from src.modules.invoicing.schemas.invoice_template import (
    InvoiceTemplateCreate,
    InvoiceTemplateUpdate,
)


# ── Helpers ──────────────────────────────────────────────────────────

_MOVE_TYPE_TITLES: dict[str, str] = {
    "out_invoice": "INVOICE",
    "out_refund": "CREDIT NOTE",
    "in_invoice": "VENDOR BILL",
    "in_refund": "VENDOR REFUND",
    "out_receipt": "SALES RECEIPT",
    "in_receipt": "PURCHASE RECEIPT",
    "entry": "JOURNAL ENTRY",
}


def _hex_to_color(hex_str: str) -> colors.Color:
    """Convert a hex color string like '#4F46E5' to a reportlab Color."""
    hex_str = hex_str.lstrip("#")
    r, g, b = (int(hex_str[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return colors.Color(r, g, b)


def _format_currency(amount: float, currency_code: str) -> str:
    """Format a monetary amount with currency code."""
    return f"{currency_code} {amount:,.2f}"


def _page_size(paper_format: str) -> tuple[float, float]:
    if paper_format == "Letter":
        return LETTER
    return A4


# ── Repository shortcut ─────────────────────────────────────────────

class _TemplateRepo(BaseRepository[InvoiceTemplate]):
    model = InvoiceTemplate


class _MoveRepo(BaseRepository[Move]):
    model = Move


# ── Service ──────────────────────────────────────────────────────────


class InvoicePDFService:
    """Generates PDF invoices from accounting moves using customizable templates."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._template_repo = _TemplateRepo(db)
        self._move_repo = _MoveRepo(db)

    # ── Template CRUD ────────────────────────────────────────────────

    async def get_default_template(self) -> InvoiceTemplate:
        """Return the default template, or a sensible built-in fallback."""
        result = await self.db.execute(
            select(InvoiceTemplate).where(
                InvoiceTemplate.is_default.is_(True),
                InvoiceTemplate.is_active.is_(True),
            )
        )
        template = result.scalar_one_or_none()
        if template is not None:
            return template

        # Fallback: return first active template, or create a built-in one
        result = await self.db.execute(
            select(InvoiceTemplate)
            .where(InvoiceTemplate.is_active.is_(True))
            .limit(1)
        )
        template = result.scalar_one_or_none()
        if template is not None:
            return template

        # No templates exist — create a default
        return await self._template_repo.create(
            name="Default Template",
            is_default=True,
        )

    async def create_template(self, data: InvoiceTemplateCreate) -> InvoiceTemplate:
        """Create a new invoice template."""
        if data.is_default:
            await self._clear_default_flag()
        return await self._template_repo.create(**data.model_dump())

    async def update_template(
        self, template_id: uuid.UUID, data: InvoiceTemplateUpdate
    ) -> InvoiceTemplate:
        """Update an existing invoice template."""
        updates = data.model_dump(exclude_unset=True)
        if updates.get("is_default"):
            await self._clear_default_flag()
        return await self._template_repo.update(template_id, **updates)

    async def list_templates(
        self, *, active_only: bool = True
    ) -> list[InvoiceTemplate]:
        """List all invoice templates."""
        filters = []
        if active_only:
            filters.append(InvoiceTemplate.is_active.is_(True))
        return await self._template_repo.list_all(filters=filters)

    async def _clear_default_flag(self) -> None:
        """Remove the default flag from all templates."""
        result = await self.db.execute(
            select(InvoiceTemplate).where(InvoiceTemplate.is_default.is_(True))
        )
        for tmpl in result.scalars().all():
            tmpl.is_default = False
        await self.db.flush()

    # ── PDF Generation ───────────────────────────────────────────────

    async def generate_invoice_pdf(
        self,
        move_id: uuid.UUID,
        template_id: uuid.UUID | None = None,
    ) -> bytes:
        """Generate a PDF for a single invoice/move.

        Args:
            move_id: The accounting move (invoice) to render.
            template_id: Optional template override; uses default if None.

        Returns:
            Raw PDF bytes.
        """
        move = await self._move_repo.get_by_id_or_raise(move_id, "Move")

        if template_id is not None:
            template = await self._template_repo.get_by_id(template_id)
            if template is None:
                raise NotFoundError("InvoiceTemplate", str(template_id))
        else:
            template = await self.get_default_template()

        return self._build_pdf(move, template)

    async def generate_batch_pdf(self, move_ids: list[uuid.UUID]) -> bytes:
        """Generate a single merged PDF containing multiple invoices.

        Each invoice starts on a new page.
        """
        if not move_ids:
            raise ValueError("move_ids must not be empty")

        template = await self.get_default_template()
        moves: list[Move] = []
        for mid in move_ids:
            move = await self._move_repo.get_by_id_or_raise(mid, "Move")
            moves.append(move)

        buf = io.BytesIO()
        page = _page_size(template.paper_format)
        doc = SimpleDocTemplate(
            buf,
            pagesize=page,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )

        elements: list = []
        for idx, move in enumerate(moves):
            elements.extend(self._build_story(move, template, page))
            if idx < len(moves) - 1:
                from reportlab.platypus import PageBreak
                elements.append(PageBreak())

        doc.build(elements)
        return buf.getvalue()

    # ── Internal PDF construction ────────────────────────────────────

    def _build_pdf(self, move: Move, template: InvoiceTemplate) -> bytes:
        """Build a single-invoice PDF and return bytes."""
        buf = io.BytesIO()
        page = _page_size(template.paper_format)
        doc = SimpleDocTemplate(
            buf,
            pagesize=page,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )
        story = self._build_story(move, template, page)
        doc.build(story)
        return buf.getvalue()

    def _build_story(
        self,
        move: Move,
        template: InvoiceTemplate,
        page_size: tuple[float, float],
    ) -> list:
        """Build the platypus story (list of flowables) for one invoice."""
        styles = getSampleStyleSheet()
        primary = _hex_to_color(template.primary_color)
        secondary = _hex_to_color(template.secondary_color)
        font = template.font_family

        # Custom styles
        title_style = ParagraphStyle(
            "InvoiceTitle",
            parent=styles["Title"],
            fontName=font,
            fontSize=22,
            textColor=primary,
            spaceAfter=6 * mm,
        )
        heading_style = ParagraphStyle(
            "InvoiceHeading",
            parent=styles["Heading2"],
            fontName=font,
            fontSize=11,
            textColor=primary,
            spaceBefore=4 * mm,
            spaceAfter=2 * mm,
        )
        normal_style = ParagraphStyle(
            "InvoiceNormal",
            parent=styles["Normal"],
            fontName=font,
            fontSize=9,
            textColor=colors.black,
        )
        small_style = ParagraphStyle(
            "InvoiceSmall",
            parent=styles["Normal"],
            fontName=font,
            fontSize=8,
            textColor=secondary,
        )

        story: list = []
        usable_width = page_size[0] - 40 * mm

        # ── Header ───────────────────────────────────────────────
        header_data: list[list] = []
        logo_cell = ""
        if template.show_logo and template.company_logo_url:
            try:
                logo_cell = Image(template.company_logo_url, width=50 * mm, height=20 * mm)
            except Exception:
                logo_cell = Paragraph("<b>COMPANY LOGO</b>", normal_style)
        elif template.show_logo:
            logo_cell = Paragraph("<b>COMPANY LOGO</b>", normal_style)

        header_right = []
        if template.header_text:
            header_right.append(Paragraph(template.header_text, small_style))

        header_data.append([logo_cell, header_right or ""])
        header_table = Table(header_data, colWidths=[usable_width * 0.5, usable_width * 0.5])
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 6 * mm))

        # ── Document title ───────────────────────────────────────
        doc_title = _MOVE_TYPE_TITLES.get(move.move_type, "DOCUMENT")
        story.append(Paragraph(doc_title, title_style))

        # ── Invoice info + customer/vendor details ───────────────
        inv_info_lines = [
            f"<b>Number:</b> {move.name or 'DRAFT'}",
            f"<b>Date:</b> {move.invoice_date or move.date or '-'}",
        ]
        if move.invoice_date_due:
            inv_info_lines.append(f"<b>Due Date:</b> {move.invoice_date_due}")
        if move.ref:
            inv_info_lines.append(f"<b>Reference:</b> {move.ref}")
        inv_info_lines.append(f"<b>Currency:</b> {move.currency_code}")

        inv_info_para = Paragraph("<br/>".join(inv_info_lines), normal_style)

        partner_label = "Customer" if move.move_type in OUTBOUND_TYPES else "Vendor"
        partner_lines = [
            f"<b>{partner_label}:</b>",
            f"Partner ID: {move.partner_id or 'N/A'}",
        ]
        partner_para = Paragraph("<br/>".join(partner_lines), normal_style)

        info_table = Table(
            [[inv_info_para, partner_para]],
            colWidths=[usable_width * 0.5, usable_width * 0.5],
        )
        info_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 8 * mm))

        # ── Line items table ─────────────────────────────────────
        story.append(Paragraph("Line Items", heading_style))

        # Filter to product lines only
        product_lines = [
            ln for ln in (move.lines or [])
            if ln.display_type == "product"
        ]

        table_data: list[list] = [
            ["#", "Description", "Qty", "Unit Price", "Discount %", "Tax", "Amount"],
        ]

        for idx, line in enumerate(product_lines, start=1):
            tax_display = ""
            if template.show_tax_details and hasattr(line, "tax_ids") and line.tax_ids:
                tax_display = ", ".join(str(t.id)[:8] for t in line.tax_ids)

            table_data.append([
                str(idx),
                Paragraph(line.name or "-", normal_style),
                f"{line.quantity:g}",
                _format_currency(line.price_unit, move.currency_code),
                f"{line.discount:g}%" if line.discount else "-",
                tax_display or "-",
                _format_currency(line.price_subtotal, move.currency_code),
            ])

        col_widths = [
            usable_width * 0.05,   # #
            usable_width * 0.30,   # Description
            usable_width * 0.08,   # Qty
            usable_width * 0.15,   # Unit Price
            usable_width * 0.12,   # Discount
            usable_width * 0.13,   # Tax
            usable_width * 0.17,   # Amount
        ]
        line_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        line_table.setStyle(TableStyle([
            # Header row
            ("BACKGROUND", (0, 0), (-1, 0), primary),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), font),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("TOPPADDING", (0, 0), (-1, 0), 6),
            # Data rows
            ("FONTNAME", (0, 1), (-1, -1), font),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("TOPPADDING", (0, 1), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            # Alternating row background
            *[
                ("BACKGROUND", (0, i), (-1, i), colors.Color(0.96, 0.96, 0.98))
                for i in range(2, len(table_data), 2)
            ],
            # Grid
            ("LINEBELOW", (0, 0), (-1, 0), 1, primary),
            ("LINEBELOW", (0, -1), (-1, -1), 0.5, secondary),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            # Right-align numeric columns
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ]))
        story.append(line_table)
        story.append(Spacer(1, 6 * mm))

        # ── Totals ───────────────────────────────────────────────
        totals_data = [
            ["Subtotal:", _format_currency(move.amount_untaxed, move.currency_code)],
        ]
        if template.show_tax_details:
            totals_data.append(
                ["Tax:", _format_currency(move.amount_tax, move.currency_code)]
            )
        totals_data.append(
            ["Total:", _format_currency(move.amount_total, move.currency_code)]
        )
        if move.amount_paid > 0:
            totals_data.append(
                ["Amount Paid:", _format_currency(move.amount_paid, move.currency_code)]
            )
            totals_data.append(
                ["Amount Due:", _format_currency(move.amount_residual, move.currency_code)]
            )

        totals_table = Table(
            totals_data,
            colWidths=[usable_width * 0.15, usable_width * 0.20],
            hAlign="RIGHT",
        )
        totals_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ALIGN", (0, 0), (0, -1), "RIGHT"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("LINEABOVE", (0, -1), (-1, -1), 1, primary),
            ("FONTNAME", (0, -1), (-1, -1), font),
            ("TEXTCOLOR", (0, -1), (-1, -1), primary),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(totals_table)
        story.append(Spacer(1, 8 * mm))

        # ── Payment terms ────────────────────────────────────────
        if template.show_payment_terms:
            if move.invoice_date_due:
                story.append(Paragraph("Payment Terms", heading_style))
                due_text = f"Payment is due by <b>{move.invoice_date_due}</b>."
                story.append(Paragraph(due_text, normal_style))
                story.append(Spacer(1, 4 * mm))

        # ── Terms & Conditions ───────────────────────────────────
        if template.terms_and_conditions:
            story.append(Paragraph("Terms & Conditions", heading_style))
            story.append(Paragraph(template.terms_and_conditions, small_style))
            story.append(Spacer(1, 4 * mm))

        # ── Footer ───────────────────────────────────────────────
        if template.footer_text:
            story.append(Spacer(1, 6 * mm))
            story.append(Paragraph(template.footer_text, small_style))

        return story
