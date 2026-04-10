"""Service for importing vendor bills from uploads, emails, and API sources.

Handles document parsing, data extraction, and creation of accounting moves
from imported vendor bill data.
"""

import logging
import re
import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError, ValidationError
from src.core.events import event_bus
from src.modules.accounting.models.move import Move
from src.modules.accounting.repositories.move_repo import MoveRepository
from src.modules.invoicing.models.vendor_bill_import import (
    VendorBillEmailAlias,
    VendorBillImport,
)
from src.modules.invoicing.schemas.vendor_import import (
    ImportSummary,
    ParsedBillData,
    ParsedBillLine,
    VendorBillEmailAliasCreate,
    VendorBillEmailAliasRead,
    VendorBillEmailAliasUpdate,
    VendorBillImportRead,
)

logger = logging.getLogger(__name__)

# File types we can attempt to parse
SUPPORTED_CONTENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "text/plain",
    "text/csv",
}


class VendorBillImportService:
    """Manages the full lifecycle of vendor bill imports.

    Supports manual file uploads, email ingestion, and programmatic API
    submissions. Extracts structured data from documents and creates
    accounting moves (vendor bills) from the parsed results.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.move_repo = MoveRepository(db)

    # ── Import entry points ──────────────────────────────────────────

    async def import_from_upload(
        self,
        file_name: str,
        file_content: bytes,
        content_type: str,
    ) -> VendorBillImportRead:
        """Import a vendor bill from a manual file upload.

        Args:
            file_name: Original file name.
            file_content: Raw file bytes.
            content_type: MIME type of the uploaded file.

        Returns:
            The created import record with parsing results.
        """
        if content_type not in SUPPORTED_CONTENT_TYPES:
            raise ValidationError(
                f"Unsupported file type: {content_type}. "
                f"Supported types: {', '.join(sorted(SUPPORTED_CONTENT_TYPES))}"
            )

        record = VendorBillImport(
            source_type="manual_upload",
            file_name=file_name,
            file_content_type=content_type,
            status="processing",
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)

        await event_bus.publish("vendor_import.received", {
            "import_id": str(record.id),
            "source_type": "manual_upload",
        })

        # Attempt to parse the document
        try:
            text = await self._extract_text(file_content, content_type)
            parsed = self._parse_invoice_text(text)

            record.parsed_data = parsed.model_dump(mode="json")
            record.total_amount = parsed.total
            record.invoice_number = parsed.invoice_number
            record.invoice_date = parsed.date
            record.status = "parsed"
            record.processing_notes = "Successfully parsed uploaded document."

            await event_bus.publish("vendor_import.parsed", {
                "import_id": str(record.id),
                "invoice_number": parsed.invoice_number,
            })
        except Exception as exc:
            logger.exception("Failed to parse uploaded file: %s", file_name)
            record.status = "failed"
            record.error_message = str(exc)

        await self.db.flush()
        await self.db.refresh(record)
        return VendorBillImportRead.model_validate(record)

    async def import_from_email(
        self,
        email_from: str,
        subject: str,
        body: str,
        attachments: list[tuple[str, bytes, str]],
    ) -> VendorBillImportRead:
        """Import a vendor bill from an incoming email.

        Processes the first supported attachment found in the email.

        Args:
            email_from: Sender email address.
            subject: Email subject line.
            body: Email body text.
            attachments: List of (filename, content_bytes, content_type) tuples.

        Returns:
            The created import record.
        """
        record = VendorBillImport(
            source_type="email",
            email_from=email_from,
            email_subject=subject,
            status="processing",
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)

        await event_bus.publish("vendor_import.received", {
            "import_id": str(record.id),
            "source_type": "email",
            "email_from": email_from,
        })

        # Try to parse the first supported attachment
        parsed = None
        for att_name, att_content, att_type in attachments:
            if att_type in SUPPORTED_CONTENT_TYPES:
                record.file_name = att_name
                record.file_content_type = att_type
                try:
                    text = await self._extract_text(att_content, att_type)
                    parsed = self._parse_invoice_text(text)
                    break
                except Exception as exc:
                    logger.warning("Failed to parse attachment %s: %s", att_name, exc)

        # Fall back to parsing the email body itself
        if parsed is None and body.strip():
            try:
                parsed = self._parse_invoice_text(body)
            except Exception as exc:
                logger.warning("Failed to parse email body: %s", exc)

        if parsed is not None:
            record.parsed_data = parsed.model_dump(mode="json")
            record.total_amount = parsed.total
            record.invoice_number = parsed.invoice_number
            record.invoice_date = parsed.date
            record.status = "parsed"
            record.processing_notes = "Successfully parsed email content."

            await event_bus.publish("vendor_import.parsed", {
                "import_id": str(record.id),
                "invoice_number": parsed.invoice_number,
            })
        else:
            record.status = "failed"
            record.error_message = "No parseable content found in email or attachments."

        await self.db.flush()
        await self.db.refresh(record)
        return VendorBillImportRead.model_validate(record)

    # ── Parsing ──────────────────────────────────────────────────────

    async def parse_bill_data(self, import_id: uuid.UUID) -> ParsedBillData:
        """Return parsed data for an import, re-parsing if needed.

        Args:
            import_id: The vendor bill import record ID.

        Returns:
            Structured parsed bill data.

        Raises:
            NotFoundError: If the import record does not exist.
            BusinessRuleError: If the import has no parseable data.
        """
        record = await self._get_import_or_raise(import_id)

        if record.parsed_data:
            return ParsedBillData.model_validate(record.parsed_data)

        raise BusinessRuleError(
            "Import has no parsed data. Re-upload or provide the document again.",
        )

    # ── Bill creation ────────────────────────────────────────────────

    async def create_bill_from_import(
        self,
        import_id: uuid.UUID,
        overrides: dict | None = None,
    ) -> uuid.UUID:
        """Create a vendor bill (Move) from a parsed import.

        Args:
            import_id: The vendor bill import record ID.
            overrides: Optional dict of field overrides for the created move.

        Returns:
            The UUID of the created Move record.

        Raises:
            NotFoundError: If the import record does not exist.
            BusinessRuleError: If the import is not in 'parsed' status or
                has already been converted to a bill.
        """
        record = await self._get_import_or_raise(import_id)

        if record.status not in ("parsed",):
            raise BusinessRuleError(
                f"Cannot create bill from import with status '{record.status}'. "
                "Import must be in 'parsed' status."
            )

        if record.move_id is not None:
            raise BusinessRuleError(
                "A bill has already been created from this import.",
                details={"move_id": str(record.move_id)},
            )

        parsed = ParsedBillData.model_validate(record.parsed_data or {})
        overrides = overrides or {}

        # Build move fields
        move_kwargs: dict = {
            "move_type": "in_invoice",
            "state": "draft",
            "ref": parsed.invoice_number,
            "invoice_date": parsed.date or date.today(),
            "invoice_date_due": parsed.due_date,
            "amount_untaxed": (parsed.total or 0.0) - (parsed.tax_amount or 0.0),
            "amount_tax": parsed.tax_amount or 0.0,
            "amount_total": parsed.total or 0.0,
            "amount_residual": parsed.total or 0.0,
            "currency_code": parsed.currency,
            "narration": f"Imported from {record.source_type}: {record.file_name or record.email_subject or 'N/A'}",
        }

        # Apply partner if resolved
        if record.partner_id:
            move_kwargs["partner_id"] = record.partner_id

        # Apply overrides (journal_id, partner_id, etc.)
        move_kwargs.update(overrides)

        # A journal_id is required
        if "journal_id" not in move_kwargs:
            raise ValidationError(
                "journal_id is required to create a vendor bill. "
                "Provide it via overrides."
            )

        move = await self.move_repo.create(**move_kwargs)

        # Update the import record
        record.move_id = move.id
        record.status = "created"
        record.processing_notes = (
            f"{record.processing_notes or ''}\n"
            f"Bill created: {move.id}"
        ).strip()

        await self.db.flush()

        await event_bus.publish("vendor_import.bill_created", {
            "import_id": str(record.id),
            "move_id": str(move.id),
        })

        return move.id

    # ── Import CRUD ──────────────────────────────────────────────────

    async def list_imports(
        self,
        status: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[VendorBillImportRead]:
        """List vendor bill imports with optional status filter."""
        query = select(VendorBillImport)
        if status:
            query = query.where(VendorBillImport.status == status)
        query = query.order_by(VendorBillImport.created_at.desc())
        query = query.offset(offset).limit(limit)
        result = await self.db.execute(query)
        records = list(result.scalars().all())
        return [VendorBillImportRead.model_validate(r) for r in records]

    async def get_import(self, import_id: uuid.UUID) -> VendorBillImportRead:
        """Get a single import by ID."""
        record = await self._get_import_or_raise(import_id)
        return VendorBillImportRead.model_validate(record)

    async def get_import_summary(self) -> ImportSummary:
        """Return aggregated counts of imports by status."""
        result = await self.db.execute(
            select(
                VendorBillImport.status,
                func.count().label("cnt"),
            ).group_by(VendorBillImport.status)
        )
        counts: dict[str, int] = {}
        total = 0
        for row in result.all():
            counts[row[0]] = row[1]
            total += row[1]

        return ImportSummary(
            total_imports=total,
            pending=counts.get("pending", 0),
            processing=counts.get("processing", 0),
            parsed=counts.get("parsed", 0),
            created=counts.get("created", 0),
            failed=counts.get("failed", 0),
        )

    # ── Email alias management ───────────────────────────────────────

    async def create_email_alias(
        self, data: VendorBillEmailAliasCreate,
    ) -> VendorBillEmailAliasRead:
        """Create a new email alias for vendor bill ingestion."""
        alias = VendorBillEmailAlias(
            alias_email=data.alias_email,
            target_journal_id=data.target_journal_id,
            auto_create=data.auto_create,
        )
        self.db.add(alias)
        await self.db.flush()
        await self.db.refresh(alias)
        return VendorBillEmailAliasRead.model_validate(alias)

    async def list_email_aliases(self) -> list[VendorBillEmailAliasRead]:
        """List all configured email aliases."""
        result = await self.db.execute(
            select(VendorBillEmailAlias).order_by(VendorBillEmailAlias.alias_email)
        )
        records = list(result.scalars().all())
        return [VendorBillEmailAliasRead.model_validate(r) for r in records]

    async def update_email_alias(
        self,
        alias_id: uuid.UUID,
        data: VendorBillEmailAliasUpdate,
    ) -> VendorBillEmailAliasRead:
        """Update an existing email alias."""
        result = await self.db.execute(
            select(VendorBillEmailAlias).where(VendorBillEmailAlias.id == alias_id)
        )
        alias = result.scalar_one_or_none()
        if alias is None:
            raise NotFoundError("VendorBillEmailAlias", str(alias_id))

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None:
                setattr(alias, key, value)

        await self.db.flush()
        await self.db.refresh(alias)
        return VendorBillEmailAliasRead.model_validate(alias)

    # ── Private helpers ──────────────────────────────────────────────

    async def _get_import_or_raise(self, import_id: uuid.UUID) -> VendorBillImport:
        """Fetch import record by ID or raise NotFoundError."""
        result = await self.db.execute(
            select(VendorBillImport).where(VendorBillImport.id == import_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise NotFoundError("VendorBillImport", str(import_id))
        return record

    async def _extract_text(self, content: bytes, content_type: str) -> str:
        """Extract text from file content based on MIME type."""
        if content_type == "application/pdf":
            return self._extract_text_from_pdf(content)
        if content_type in ("text/plain", "text/csv"):
            return content.decode("utf-8", errors="replace")
        if content_type in ("image/png", "image/jpeg"):
            # OCR stub -- would integrate with an OCR service
            return "[OCR extraction not yet implemented]"
        return ""

    def _extract_text_from_pdf(self, content: bytes) -> str:
        """Extract text from a PDF document.

        This is a stub implementation. In production, integrate with a
        PDF parsing library such as PyMuPDF or pdfplumber.
        """
        # Stub: return placeholder indicating PDF parsing is needed
        return "[PDF text extraction placeholder - integrate PDF library]"

    def _parse_invoice_text(self, text: str) -> ParsedBillData:
        """Parse invoice text using regex patterns to extract structured data.

        Extracts totals, dates, invoice numbers, VAT numbers, and line items
        from free-text invoice content.
        """
        data = ParsedBillData()

        # ── Invoice number ───────────────────────────────────────────
        inv_patterns = [
            r"(?:Invoice\s*#|Invoice\s*No\.?|Invoice\s*Number|Inv\s*No\.?|Bill\s*#|Bill\s*No\.?)\s*:?\s*([A-Za-z0-9\-/]+)",
        ]
        for pattern in inv_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                data.invoice_number = match.group(1).strip()
                break

        # ── Total amount ─────────────────────────────────────────────
        total_patterns = [
            r"(?:Grand\s*Total|Total\s*Due|Amount\s*Due|Total\s*Amount|Total)\s*:?\s*\$?\s*([\d,]+\.?\d*)",
        ]
        for pattern in total_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount_str = match.group(1).replace(",", "")
                try:
                    data.total = float(amount_str)
                except ValueError:
                    pass
                break

        # ── Tax amount ───────────────────────────────────────────────
        tax_patterns = [
            r"(?:Tax|VAT|GST|Sales\s*Tax)\s*:?\s*\$?\s*([\d,]+\.?\d*)",
        ]
        for pattern in tax_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                tax_str = match.group(1).replace(",", "")
                try:
                    data.tax_amount = float(tax_str)
                except ValueError:
                    pass
                break

        # ── Dates ────────────────────────────────────────────────────
        date_patterns = [
            # MM/DD/YYYY or MM-DD-YYYY
            (r"(?:Invoice\s*Date|Date|Bill\s*Date)\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})", "%m/%d/%Y"),
            # YYYY-MM-DD (ISO)
            (r"(?:Invoice\s*Date|Date|Bill\s*Date)\s*:?\s*(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
            # DD Mon YYYY
            (r"(?:Invoice\s*Date|Date|Bill\s*Date)\s*:?\s*(\d{1,2}\s+\w{3,9}\s+\d{4})", "%d %B %Y"),
        ]
        for pattern, fmt in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1).replace("-", "/") if "/" in fmt else match.group(1)
                try:
                    data.date = datetime.strptime(date_str, fmt).date()
                except ValueError:
                    pass
                break

        # Due date
        due_patterns = [
            (r"(?:Due\s*Date|Payment\s*Due)\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})", "%m/%d/%Y"),
            (r"(?:Due\s*Date|Payment\s*Due)\s*:?\s*(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
        ]
        for pattern, fmt in due_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1).replace("-", "/") if "/" in fmt else match.group(1)
                try:
                    data.due_date = datetime.strptime(date_str, fmt).date()
                except ValueError:
                    pass
                break

        # ── Vendor name ──────────────────────────────────────────────
        vendor_patterns = [
            r"(?:From|Vendor|Supplier|Company)\s*:?\s*(.+?)(?:\n|$)",
        ]
        for pattern in vendor_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                if name and len(name) < 200:
                    data.vendor_name = name
                break

        # ── VAT number ───────────────────────────────────────────────
        vat_match = re.search(
            r"(?:VAT\s*(?:No\.?|Number|ID|Reg\.?)\s*:?\s*)([A-Z]{2}\s*[\dA-Z]+)",
            text,
            re.IGNORECASE,
        )
        if vat_match:
            # Store in processing_notes or parsed_data for downstream use
            vat_number = vat_match.group(1).replace(" ", "")
            if data.vendor_name is None:
                data.vendor_name = f"VAT: {vat_number}"

        # ── Currency ─────────────────────────────────────────────────
        currency_match = re.search(r"(?:Currency)\s*:?\s*([A-Z]{3})", text)
        if currency_match:
            data.currency = currency_match.group(1)
        elif "\u20ac" in text:
            data.currency = "EUR"
        elif "\u00a3" in text:
            data.currency = "GBP"

        return data
