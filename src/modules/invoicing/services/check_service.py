"""Check printing service — generates US-format check PDFs.

Uses reportlab to produce standard check-format PDFs with payee,
date, amount (numeric and written), memo, and check number.
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.modules.invoicing.models.batch_payment import InvoiceBatchPayment
from src.modules.invoicing.repositories.batch_payment_repo import (
    InvoiceBatchPaymentRepository,
)

logger = logging.getLogger(__name__)

# Standard US check dimensions (in points, 1 point = 1/72 inch)
CHECK_WIDTH = 8.5 * 72  # 8.5 inches
CHECK_HEIGHT = 3.5 * 72  # 3.5 inches per check (3 per page)
PAGE_HEIGHT = 11 * 72  # 11 inches (letter size)
PAGE_WIDTH = 8.5 * 72

# Number words for writing amounts in English
_ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
    "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
    "Sixteen", "Seventeen", "Eighteen", "Nineteen",
]
_TENS = [
    "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy",
    "Eighty", "Ninety",
]


def _amount_to_words(amount: float) -> str:
    """Convert a numeric amount to written English for check printing.

    Examples:
        1234.56 -> "One Thousand Two Hundred Thirty-Four and 56/100"
        0.99    -> "Zero and 99/100"
    """
    dollars = int(amount)
    cents = round((amount - dollars) * 100)

    if dollars == 0:
        words = "Zero"
    else:
        words = _int_to_words(dollars)

    return f"{words} and {cents:02d}/100"


def _int_to_words(n: int) -> str:
    """Convert a non-negative integer to English words."""
    if n == 0:
        return "Zero"
    if n < 0:
        return "Negative " + _int_to_words(-n)

    parts: list[str] = []

    if n >= 1_000_000_000:
        billions = n // 1_000_000_000
        parts.append(_int_to_words(billions) + " Billion")
        n %= 1_000_000_000

    if n >= 1_000_000:
        millions = n // 1_000_000
        parts.append(_int_to_words(millions) + " Million")
        n %= 1_000_000

    if n >= 1_000:
        thousands = n // 1_000
        parts.append(_int_to_words(thousands) + " Thousand")
        n %= 1_000

    if n >= 100:
        hundreds = n // 100
        parts.append(_ONES[hundreds] + " Hundred")
        n %= 100

    if n >= 20:
        tens = n // 10
        ones = n % 10
        if ones:
            parts.append(f"{_TENS[tens]}-{_ONES[ones]}")
        else:
            parts.append(_TENS[tens])
    elif n > 0:
        parts.append(_ONES[n])

    return " ".join(parts)


class CheckPrintService:
    """Generates US-format check PDFs for batch payments."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.batch_repo = InvoiceBatchPaymentRepository(db)

    async def generate_check_pdf(self, batch_id: uuid.UUID) -> bytes:
        """Generate a multi-check PDF for an entire batch.

        Returns the PDF content as bytes. Each check includes: payee name,
        date, amount (numeric and written), memo, and check number.
        """
        batch = await self.batch_repo.get_with_lines(batch_id)
        if batch is None:
            raise NotFoundError("InvoiceBatchPayment", str(batch_id))

        if batch.payment_method != "check":
            raise BusinessRuleError(
                f"Batch payment method is '{batch.payment_method}', "
                f"expected 'check'"
            )

        if batch.state not in ("confirmed", "sent"):
            raise BusinessRuleError(
                f"Batch must be confirmed before printing checks. "
                f"Current state: '{batch.state}'"
            )

        pending_lines = [l for l in batch.lines if l.state == "pending"]
        if not pending_lines:
            raise BusinessRuleError("No pending lines to print checks for")

        from reportlab.lib.pagesizes import LETTER
        from reportlab.pdfgen import canvas

        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=LETTER)

        check_number = 1001  # Starting check number (could be configurable)
        checks_on_page = 0

        for line in pending_lines:
            if checks_on_page >= 3:
                c.showPage()
                checks_on_page = 0

            y_offset = PAGE_HEIGHT - (checks_on_page + 1) * CHECK_HEIGHT
            self._draw_single_check(
                c,
                y_offset=y_offset,
                partner_name=f"Partner-{line.partner_id}",
                amount=line.amount,
                check_date=batch.execution_date or date.today(),
                memo=line.communication or "",
                check_number=check_number,
                currency_code=line.currency_code or "USD",
            )
            check_number += 1
            checks_on_page += 1

        c.save()
        pdf_bytes = buffer.getvalue()
        buffer.close()

        # Store on batch
        batch.generated_file = pdf_bytes
        batch.generated_filename = f"checks_{batch.name.replace('/', '_')}.pdf"
        await self.db.flush()

        logger.info(
            "Generated check PDF for batch %s (%d checks)",
            batch.name, len(pending_lines),
        )
        return pdf_bytes

    def generate_single_check(
        self,
        partner_name: str,
        amount: float,
        check_date: date,
        memo: str,
        check_number: int,
        currency_code: str = "USD",
    ) -> bytes:
        """Generate a single-check PDF. Returns PDF bytes."""
        from reportlab.lib.pagesizes import LETTER
        from reportlab.pdfgen import canvas

        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=LETTER)

        y_offset = PAGE_HEIGHT - CHECK_HEIGHT
        self._draw_single_check(
            c,
            y_offset=y_offset,
            partner_name=partner_name,
            amount=amount,
            check_date=check_date,
            memo=memo,
            check_number=check_number,
            currency_code=currency_code,
        )

        c.save()
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes

    # ── Private Drawing ────────────────────────────────────────────────

    @staticmethod
    def _draw_single_check(
        c,
        *,
        y_offset: float,
        partner_name: str,
        amount: float,
        check_date: date,
        memo: str,
        check_number: int,
        currency_code: str = "USD",
    ) -> None:
        """Draw a single US-format check on the canvas at the given y_offset.

        Layout (top to bottom within the check area):
        - Check number (top right)
        - Date (top right area)
        - Pay to the order of (payee name)
        - Amount box (numeric)
        - Amount in words line
        - Memo line
        - Signature line
        """
        from reportlab.lib.units import inch

        left_margin = 0.75 * inch
        right_edge = CHECK_WIDTH - 0.5 * inch

        # ── Border ─────────────────────────────────────────────────────
        c.setStrokeColorRGB(0.7, 0.7, 0.7)
        c.setLineWidth(0.5)
        c.rect(0.25 * inch, y_offset + 4, CHECK_WIDTH - 0.5 * inch, CHECK_HEIGHT - 8)

        c.setStrokeColorRGB(0, 0, 0)
        c.setFillColorRGB(0, 0, 0)

        # ── Check Number ───────────────────────────────────────────────
        c.setFont("Helvetica-Bold", 10)
        c.drawRightString(
            right_edge, y_offset + CHECK_HEIGHT - 30,
            f"No. {check_number}",
        )

        # ── Company Name (placeholder) ────────────────────────────────
        c.setFont("Helvetica-Bold", 12)
        c.drawString(left_margin, y_offset + CHECK_HEIGHT - 30, "Foundrix ERP")
        c.setFont("Helvetica", 8)
        c.drawString(left_margin, y_offset + CHECK_HEIGHT - 42, "123 Business Ave, Suite 100")

        # ── Date ───────────────────────────────────────────────────────
        c.setFont("Helvetica", 9)
        c.drawString(right_edge - 1.8 * inch, y_offset + CHECK_HEIGHT - 60, "Date:")
        c.setFont("Helvetica", 10)
        c.drawString(
            right_edge - 1.4 * inch, y_offset + CHECK_HEIGHT - 60,
            check_date.strftime("%m/%d/%Y"),
        )
        # Underline for date
        c.line(
            right_edge - 1.4 * inch, y_offset + CHECK_HEIGHT - 62,
            right_edge, y_offset + CHECK_HEIGHT - 62,
        )

        # ── Pay to the Order of ───────────────────────────────────────
        y_payee = y_offset + CHECK_HEIGHT - 85
        c.setFont("Helvetica", 8)
        c.drawString(left_margin, y_payee + 2, "PAY TO THE")
        c.drawString(left_margin, y_payee - 7, "ORDER OF")
        c.setFont("Helvetica-Bold", 11)
        c.drawString(left_margin + 0.8 * inch, y_payee, partner_name)
        # Underline
        c.line(
            left_margin + 0.8 * inch, y_payee - 2,
            right_edge - 1.5 * inch, y_payee - 2,
        )

        # ── Amount Box (numeric) ──────────────────────────────────────
        amt_box_x = right_edge - 1.3 * inch
        c.setFont("Helvetica-Bold", 10)
        c.drawString(amt_box_x - 0.15 * inch, y_payee, "$" if currency_code == "USD" else currency_code)
        c.rect(amt_box_x, y_payee - 5, 1.2 * inch, 18)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(amt_box_x + 4, y_payee, f"{amount:,.2f}")

        # ── Amount in Words ───────────────────────────────────────────
        y_words = y_payee - 25
        c.setFont("Helvetica", 9)
        amount_words = _amount_to_words(amount)
        # Truncate if too long for the line
        max_chars = 60
        if len(amount_words) > max_chars:
            amount_words = amount_words[:max_chars] + "..."
        c.drawString(left_margin, y_words, amount_words)
        c.drawRightString(right_edge, y_words, "DOLLARS")
        # Underline
        c.line(left_margin, y_words - 2, right_edge, y_words - 2)

        # ── Memo ──────────────────────────────────────────────────────
        y_memo = y_offset + 35
        c.setFont("Helvetica", 8)
        c.drawString(left_margin, y_memo, "Memo:")
        c.setFont("Helvetica", 9)
        memo_text = memo[:50] if memo else ""
        c.drawString(left_margin + 0.5 * inch, y_memo, memo_text)
        c.line(
            left_margin + 0.5 * inch, y_memo - 2,
            left_margin + 3.5 * inch, y_memo - 2,
        )

        # ── Signature Line ───────────────────────────────────────────
        c.line(
            right_edge - 2.5 * inch, y_memo - 2,
            right_edge, y_memo - 2,
        )
        c.setFont("Helvetica", 7)
        c.drawRightString(right_edge, y_memo - 10, "Authorized Signature")
