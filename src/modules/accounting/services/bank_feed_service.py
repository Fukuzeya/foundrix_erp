"""Bank feed synchronization and statement import service.

Handles importing bank statements from multiple file formats:
- OFX/QFX (Open Financial Exchange)
- CSV (configurable column mapping)
- CAMT.053 (ISO 20022 XML bank-to-customer statement)
- QIF (Quicken Interchange Format)

Includes duplicate detection and import history tracking.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime
from difflib import SequenceMatcher

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import (
    BusinessRuleError,
    NotFoundError,
    ValidationError,
)
from src.modules.accounting.models.bank_statement import (
    BankStatement,
    BankStatementLine,
)
from src.modules.accounting.repositories.bank_statement_repo import (
    BankStatementLineRepository,
    BankStatementRepository,
)
from src.modules.accounting.repositories.journal_repo import JournalRepository

logger = logging.getLogger(__name__)

# Default CSV column mapping: column_name -> column_index
DEFAULT_CSV_MAPPING: dict[str, int] = {
    "date": 0,
    "description": 1,
    "amount": 2,
    "reference": 3,
}

# ISO 20022 CAMT.053 namespace
CAMT053_NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"

# Duplicate detection confidence thresholds
DUPLICATE_EXACT_THRESHOLD = 0.95
DUPLICATE_FUZZY_THRESHOLD = 0.70


class BankFeedService:
    """Import bank statements from various file formats with duplicate detection."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = BankStatementRepository(db)
        self.line_repo = BankStatementLineRepository(db)
        self.journal_repo = JournalRepository(db)

    # ── Public import methods ─────────────────────────────────────────

    async def import_ofx(
        self, journal_id: uuid.UUID, file_content: bytes
    ) -> dict:
        """Parse OFX/QFX file and create bank statement with lines.

        OFX files use an SGML-like format with <STMTTRN> entries containing
        TRNTYPE, DTPOSTED, TRNAMT, FITID, NAME, and MEMO fields.

        Returns:
            Summary dict with statement_id, lines_imported,
            duplicates_skipped, and date_range.
        """
        journal = await self._validate_bank_journal(journal_id)

        text_content = self._decode_bytes(file_content)
        parsed = self._parse_ofx(text_content)

        lines = parsed["transactions"]
        if not lines:
            raise ValidationError("OFX file contains no transactions")

        duplicates = await self.detect_duplicates(journal_id, lines)
        duplicate_keys = {
            (d["date"], d["amount"], d["reference"])
            for d in duplicates
            if d["confidence"] >= DUPLICATE_EXACT_THRESHOLD
        }

        filtered_lines = []
        duplicates_skipped = 0
        for line in lines:
            key = (line["date"], line["amount"], line.get("reference"))
            if key in duplicate_keys:
                duplicates_skipped += 1
            else:
                filtered_lines.append(line)

        statement = await self._create_statement_from_lines(
            journal=journal,
            lines=filtered_lines,
            import_format="ofx",
            balance_start=parsed.get("balance_start", 0.0),
            balance_end_real=parsed.get("balance_end", 0.0),
        )

        return self._build_import_summary(
            statement_id=statement.id,
            lines_imported=len(filtered_lines),
            duplicates_skipped=duplicates_skipped,
            lines=filtered_lines,
        )

    async def import_csv(
        self,
        journal_id: uuid.UUID,
        file_content: str,
        mapping: dict | None = None,
    ) -> dict:
        """Parse CSV with configurable column mapping.

        Args:
            journal_id: Target bank/cash journal.
            file_content: CSV text content.
            mapping: Column mapping dict, e.g. {date: 0, description: 1,
                     amount: 2, reference: 3}. Uses DEFAULT_CSV_MAPPING
                     if not provided.

        Returns:
            Summary dict with statement_id, lines_imported,
            duplicates_skipped, and date_range.
        """
        journal = await self._validate_bank_journal(journal_id)

        col_map = mapping or DEFAULT_CSV_MAPPING
        lines = self._parse_csv(file_content, col_map)

        if not lines:
            raise ValidationError("CSV file contains no valid transaction rows")

        duplicates = await self.detect_duplicates(journal_id, lines)
        duplicate_keys = {
            (d["date"], d["amount"], d["reference"])
            for d in duplicates
            if d["confidence"] >= DUPLICATE_EXACT_THRESHOLD
        }

        filtered_lines = []
        duplicates_skipped = 0
        for line in lines:
            key = (line["date"], line["amount"], line.get("reference"))
            if key in duplicate_keys:
                duplicates_skipped += 1
            else:
                filtered_lines.append(line)

        statement = await self._create_statement_from_lines(
            journal=journal,
            lines=filtered_lines,
            import_format="csv",
        )

        return self._build_import_summary(
            statement_id=statement.id,
            lines_imported=len(filtered_lines),
            duplicates_skipped=duplicates_skipped,
            lines=filtered_lines,
        )

    async def import_camt053(
        self, journal_id: uuid.UUID, file_content: bytes
    ) -> dict:
        """Parse CAMT.053 XML bank statement (ISO 20022).

        Extracts statement entries from the BkToCstmrStmt/Stmt/Ntry elements,
        including booking date, amount, credit/debit indicator, and references.

        Returns:
            Summary dict with statement_id, lines_imported,
            duplicates_skipped, and date_range.
        """
        journal = await self._validate_bank_journal(journal_id)

        text_content = self._decode_bytes(file_content)
        parsed = self._parse_camt053(text_content)

        lines = parsed["transactions"]
        if not lines:
            raise ValidationError("CAMT.053 file contains no entries")

        duplicates = await self.detect_duplicates(journal_id, lines)
        duplicate_keys = {
            (d["date"], d["amount"], d["reference"])
            for d in duplicates
            if d["confidence"] >= DUPLICATE_EXACT_THRESHOLD
        }

        filtered_lines = []
        duplicates_skipped = 0
        for line in lines:
            key = (line["date"], line["amount"], line.get("reference"))
            if key in duplicate_keys:
                duplicates_skipped += 1
            else:
                filtered_lines.append(line)

        statement = await self._create_statement_from_lines(
            journal=journal,
            lines=filtered_lines,
            import_format="camt053",
            balance_start=parsed.get("balance_start", 0.0),
            balance_end_real=parsed.get("balance_end", 0.0),
        )

        return self._build_import_summary(
            statement_id=statement.id,
            lines_imported=len(filtered_lines),
            duplicates_skipped=duplicates_skipped,
            lines=filtered_lines,
        )

    async def import_qif(
        self, journal_id: uuid.UUID, file_content: str
    ) -> dict:
        """Parse QIF (Quicken Interchange Format) file.

        QIF records are delimited by '^' lines, with field codes:
        D = date, T = amount, P = payee, N = check number, M = memo.

        Returns:
            Summary dict with statement_id, lines_imported,
            duplicates_skipped, and date_range.
        """
        journal = await self._validate_bank_journal(journal_id)

        lines = self._parse_qif(file_content)

        if not lines:
            raise ValidationError("QIF file contains no transactions")

        duplicates = await self.detect_duplicates(journal_id, lines)
        duplicate_keys = {
            (d["date"], d["amount"], d["reference"])
            for d in duplicates
            if d["confidence"] >= DUPLICATE_EXACT_THRESHOLD
        }

        filtered_lines = []
        duplicates_skipped = 0
        for line in lines:
            key = (line["date"], line["amount"], line.get("reference"))
            if key in duplicate_keys:
                duplicates_skipped += 1
            else:
                filtered_lines.append(line)

        statement = await self._create_statement_from_lines(
            journal=journal,
            lines=filtered_lines,
            import_format="qif",
        )

        return self._build_import_summary(
            statement_id=statement.id,
            lines_imported=len(filtered_lines),
            duplicates_skipped=duplicates_skipped,
            lines=filtered_lines,
        )

    # ── Duplicate detection ───────────────────────────────────────────

    async def detect_duplicates(
        self, journal_id: uuid.UUID, lines: list[dict]
    ) -> list[dict]:
        """Check proposed import lines against existing statement lines.

        Matches on: date + amount + reference (fuzzy on reference).
        Returns list of potential duplicates with confidence scores.
        """
        if not lines:
            return []

        # Collect all dates from the proposed lines to narrow the DB query
        line_dates = {line["date"] for line in lines if line.get("date")}
        if not line_dates:
            return []

        min_date = min(line_dates)
        max_date = max(line_dates)

        # Fetch existing lines from statements belonging to this journal
        existing_query = (
            select(BankStatementLine)
            .join(BankStatement, BankStatementLine.statement_id == BankStatement.id)
            .where(
                and_(
                    BankStatement.journal_id == journal_id,
                    BankStatementLine.date >= min_date,
                    BankStatementLine.date <= max_date,
                )
            )
        )
        result = await self.db.execute(existing_query)
        existing_lines = list(result.scalars().all())

        if not existing_lines:
            return []

        duplicates: list[dict] = []
        for proposed in lines:
            for existing in existing_lines:
                confidence = self._compute_duplicate_confidence(proposed, existing)
                if confidence >= DUPLICATE_FUZZY_THRESHOLD:
                    duplicates.append({
                        "date": proposed["date"],
                        "amount": proposed["amount"],
                        "reference": proposed.get("reference"),
                        "description": proposed.get("description", ""),
                        "confidence": round(confidence, 3),
                        "existing_line_id": str(existing.id),
                        "existing_statement_id": str(existing.statement_id),
                    })
                    break  # One match per proposed line is enough

        return duplicates

    # ── Import history ────────────────────────────────────────────────

    async def get_import_history(
        self, journal_id: uuid.UUID | None = None
    ) -> list[dict]:
        """Return history of statement imports with stats.

        Only includes statements created via file import (import_format is set).
        """
        query = (
            select(
                BankStatement.id,
                BankStatement.name,
                BankStatement.date,
                BankStatement.journal_id,
                BankStatement.import_format,
                BankStatement.balance_start,
                BankStatement.balance_end_real,
                BankStatement.balance_end,
                BankStatement.state,
                BankStatement.created_at,
                func.count(BankStatementLine.id).label("line_count"),
                func.coalesce(func.sum(BankStatementLine.amount), 0.0).label(
                    "total_amount"
                ),
            )
            .outerjoin(
                BankStatementLine,
                BankStatementLine.statement_id == BankStatement.id,
            )
            .where(BankStatement.import_format.isnot(None))
            .group_by(BankStatement.id)
            .order_by(BankStatement.created_at.desc())
        )

        if journal_id:
            query = query.where(BankStatement.journal_id == journal_id)

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "statement_id": str(row.id),
                "name": row.name,
                "date": row.date.isoformat(),
                "journal_id": str(row.journal_id),
                "import_format": row.import_format,
                "balance_start": row.balance_start,
                "balance_end_real": row.balance_end_real,
                "balance_end": row.balance_end,
                "state": row.state,
                "imported_at": row.created_at.isoformat(),
                "line_count": row.line_count,
                "total_amount": round(row.total_amount, 2),
            }
            for row in rows
        ]

    # ── Internal helpers ──────────────────────────────────────────────

    async def _validate_bank_journal(self, journal_id: uuid.UUID):
        """Validate that journal exists and is a bank/cash type."""
        journal = await self.journal_repo.get_by_id(journal_id)
        if not journal:
            raise NotFoundError("Journal", str(journal_id))
        if journal.journal_type not in ("bank", "cash"):
            raise BusinessRuleError(
                "Bank feed imports require a bank or cash journal"
            )
        return journal

    async def _create_statement_from_lines(
        self,
        journal,
        lines: list[dict],
        import_format: str,
        balance_start: float = 0.0,
        balance_end_real: float = 0.0,
    ) -> BankStatement:
        """Create a BankStatement with BankStatementLine records."""
        if not lines:
            # Create an empty statement — the caller already validated
            stmt_date = date.today()
        else:
            dates = [line["date"] for line in lines if line.get("date")]
            stmt_date = max(dates) if dates else date.today()

        stmt_name = (
            f"{import_format.upper()} Import "
            f"{journal.code} {stmt_date.isoformat()}"
        )

        statement = BankStatement(
            name=stmt_name,
            date=stmt_date,
            journal_id=journal.id,
            balance_start=balance_start,
            balance_end_real=balance_end_real,
            import_format=import_format,
            state="open",
        )
        self.db.add(statement)
        await self.db.flush()

        total_amount = 0.0
        for i, line_data in enumerate(lines):
            line = BankStatementLine(
                statement_id=statement.id,
                date=line_data["date"],
                name=line_data.get("description", "Imported transaction"),
                ref=line_data.get("reference"),
                amount=line_data["amount"],
                currency_code=line_data.get("currency", "USD"),
                sequence=i + 1,
                notes=line_data.get("notes"),
            )
            self.db.add(line)
            total_amount += line_data["amount"]

        statement.balance_end = round(balance_start + total_amount, 2)

        await self.db.flush()
        await self.db.refresh(statement)

        logger.info(
            "Created bank statement %s with %d lines (format=%s)",
            statement.id,
            len(lines),
            import_format,
        )
        return statement

    @staticmethod
    def _build_import_summary(
        statement_id: uuid.UUID,
        lines_imported: int,
        duplicates_skipped: int,
        lines: list[dict],
    ) -> dict:
        """Build the standard import summary dict."""
        dates = [line["date"] for line in lines if line.get("date")]
        date_range = None
        if dates:
            date_range = {
                "start": min(dates).isoformat(),
                "end": max(dates).isoformat(),
            }

        return {
            "statement_id": str(statement_id),
            "lines_imported": lines_imported,
            "duplicates_skipped": duplicates_skipped,
            "date_range": date_range,
        }

    @staticmethod
    def _compute_duplicate_confidence(
        proposed: dict, existing: BankStatementLine
    ) -> float:
        """Compute a confidence score (0.0–1.0) for duplicate detection.

        Exact match on date + amount gives 0.8 base score.
        Reference similarity adds up to 0.2 more.
        """
        # Date must match exactly
        if proposed.get("date") != existing.date:
            return 0.0

        # Amount must match exactly (floating point comparison with tolerance)
        if abs(proposed.get("amount", 0.0) - existing.amount) > 0.005:
            return 0.0

        # Base confidence for date + amount match
        confidence = 0.80

        # Boost with reference similarity
        proposed_ref = (proposed.get("reference") or "").strip().lower()
        existing_ref = (existing.ref or "").strip().lower()

        if proposed_ref and existing_ref:
            ref_similarity = SequenceMatcher(
                None, proposed_ref, existing_ref
            ).ratio()
            confidence += 0.20 * ref_similarity
        elif not proposed_ref and not existing_ref:
            # Both empty references — slight boost
            confidence += 0.10

        return confidence

    @staticmethod
    def _decode_bytes(content: bytes) -> str:
        """Decode bytes to string, trying common encodings."""
        for encoding in ("utf-8", "latin-1", "cp1252", "ascii"):
            try:
                return content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        raise ValidationError("Unable to decode file content — unsupported encoding")

    # ── OFX Parser ────────────────────────────────────────────────────

    @staticmethod
    def _parse_ofx(content: str) -> dict:
        """Parse OFX/QFX file content.

        OFX files have a header section followed by SGML-like tagged data.
        We extract STMTTRN entries from BANKTRANLIST and balance info from
        LEDGERBAL / AVAILBAL.
        """
        # Strip OFX headers (lines before the first '<')
        xml_start = content.find("<")
        if xml_start < 0:
            raise ValidationError("Invalid OFX file: no XML/SGML content found")

        body = content[xml_start:]

        # OFX uses SGML without closing tags in older versions.
        # Normalize: insert closing tags for self-closing elements.
        body = BankFeedService._normalize_ofx_sgml(body)

        transactions: list[dict] = []
        balance_start = 0.0
        balance_end = 0.0

        # Try XML parsing first (OFX 2.x is valid XML)
        try:
            root = ET.fromstring(body)
            # Search for transaction list
            for stmttrn in root.iter("STMTTRN"):
                txn = BankFeedService._extract_ofx_transaction(stmttrn)
                if txn:
                    transactions.append(txn)

            # Extract balances
            for bal in root.iter("LEDGERBAL"):
                bal_amt = bal.find("BALAMT")
                if bal_amt is not None and bal_amt.text:
                    balance_end = float(bal_amt.text.strip())
            for bal in root.iter("AVAILBAL"):
                bal_amt = bal.find("BALAMT")
                if bal_amt is not None and bal_amt.text:
                    balance_start = float(bal_amt.text.strip())

        except ET.ParseError:
            # Fall back to regex-based parsing for OFX 1.x SGML
            transactions = BankFeedService._parse_ofx_sgml(body)
            balance_start, balance_end = BankFeedService._parse_ofx_balances_sgml(
                body
            )

        return {
            "transactions": transactions,
            "balance_start": balance_start,
            "balance_end": balance_end,
        }

    @staticmethod
    def _normalize_ofx_sgml(body: str) -> str:
        """Normalize OFX 1.x SGML into parseable XML.

        OFX 1.x uses unclosed tags like <TRNAMT>123.45 instead of
        <TRNAMT>123.45</TRNAMT>. This inserts closing tags for known
        leaf elements.
        """
        leaf_tags = (
            "TRNTYPE", "DTPOSTED", "DTUSER", "TRNAMT", "FITID", "NAME",
            "MEMO", "CHECKNUM", "REFNUM", "SIC", "PAYEEID", "ACCTID",
            "BANKID", "BRANCHID", "ACCTTYPE", "BALAMT", "DTASOF",
            "CURRATE", "CURSYM", "SEVERITY", "CODE", "MESSAGE",
            "DTSTART", "DTEND", "DTSERVER", "LANGUAGE", "ORG", "FID",
            "INTU.BID", "INTU.USERID",
        )
        for tag in leaf_tags:
            # Match <TAG>value (not followed by <)
            pattern = rf"<{tag}>([^<\r\n]+)"
            body = re.sub(pattern, rf"<{tag}>\1</{tag}>", body)
        return body

    @staticmethod
    def _extract_ofx_transaction(stmttrn_elem) -> dict | None:
        """Extract a transaction dict from an XML STMTTRN element."""
        def get_text(tag: str) -> str | None:
            el = stmttrn_elem.find(tag)
            return el.text.strip() if el is not None and el.text else None

        amount_str = get_text("TRNAMT")
        date_str = get_text("DTPOSTED")

        if not amount_str or not date_str:
            return None

        try:
            amount = float(amount_str)
        except ValueError:
            return None

        txn_date = BankFeedService._parse_ofx_date(date_str)
        if not txn_date:
            return None

        name = get_text("NAME") or get_text("MEMO") or "OFX Transaction"
        reference = get_text("FITID") or get_text("CHECKNUM") or get_text("REFNUM")

        return {
            "date": txn_date,
            "description": name,
            "amount": amount,
            "reference": reference,
        }

    @staticmethod
    def _parse_ofx_sgml(body: str) -> list[dict]:
        """Regex-based OFX SGML parser for OFX 1.x files."""
        transactions: list[dict] = []
        # Split by STMTTRN blocks
        blocks = re.findall(
            r"<STMTTRN>(.*?)(?:</STMTTRN>|<STMTTRN>|</BANKTRANLIST>)",
            body,
            re.DOTALL | re.IGNORECASE,
        )

        for block in blocks:
            txn = BankFeedService._parse_ofx_sgml_block(block)
            if txn:
                transactions.append(txn)

        return transactions

    @staticmethod
    def _parse_ofx_sgml_block(block: str) -> dict | None:
        """Parse a single OFX SGML STMTTRN block into a transaction dict."""
        def extract(tag: str) -> str | None:
            match = re.search(
                rf"<{tag}>([^<\r\n]+)", block, re.IGNORECASE
            )
            return match.group(1).strip() if match else None

        amount_str = extract("TRNAMT")
        date_str = extract("DTPOSTED")

        if not amount_str or not date_str:
            return None

        try:
            amount = float(amount_str)
        except ValueError:
            return None

        txn_date = BankFeedService._parse_ofx_date(date_str)
        if not txn_date:
            return None

        name = extract("NAME") or extract("MEMO") or "OFX Transaction"
        reference = extract("FITID") or extract("CHECKNUM") or extract("REFNUM")

        return {
            "date": txn_date,
            "description": name,
            "amount": amount,
            "reference": reference,
        }

    @staticmethod
    def _parse_ofx_balances_sgml(body: str) -> tuple[float, float]:
        """Extract balance_start and balance_end from OFX SGML."""
        balance_start = 0.0
        balance_end = 0.0

        ledger_match = re.search(
            r"<LEDGERBAL>.*?<BALAMT>([^<\r\n]+)",
            body,
            re.DOTALL | re.IGNORECASE,
        )
        if ledger_match:
            try:
                balance_end = float(ledger_match.group(1).strip())
            except ValueError:
                pass

        avail_match = re.search(
            r"<AVAILBAL>.*?<BALAMT>([^<\r\n]+)",
            body,
            re.DOTALL | re.IGNORECASE,
        )
        if avail_match:
            try:
                balance_start = float(avail_match.group(1).strip())
            except ValueError:
                pass

        return balance_start, balance_end

    @staticmethod
    def _parse_ofx_date(date_str: str) -> date | None:
        """Parse OFX date format YYYYMMDDHHMMSS[.XXX:TZ] to date."""
        # Take only the first 8 characters (YYYYMMDD)
        cleaned = re.sub(r"[^\d]", "", date_str[:8])
        if len(cleaned) < 8:
            return None
        try:
            return datetime.strptime(cleaned[:8], "%Y%m%d").date()
        except ValueError:
            return None

    # ── CSV Parser ────────────────────────────────────────────────────

    @staticmethod
    def _parse_csv(content: str, col_map: dict[str, int]) -> list[dict]:
        """Parse CSV content with configurable column mapping.

        Args:
            content: Raw CSV text.
            col_map: Mapping of field names to column indices.
                     Required keys: 'date', 'description', 'amount'.
                     Optional: 'reference', 'currency'.
        """
        date_col = col_map.get("date", 0)
        desc_col = col_map.get("description", 1)
        amount_col = col_map.get("amount", 2)
        ref_col = col_map.get("reference")
        currency_col = col_map.get("currency")

        max_col = max(
            c for c in (date_col, desc_col, amount_col, ref_col, currency_col)
            if c is not None
        )

        transactions: list[dict] = []
        reader = csv.reader(io.StringIO(content))

        for row_num, row in enumerate(reader):
            # Skip empty rows
            if not row or all(cell.strip() == "" for cell in row):
                continue

            # Skip rows that don't have enough columns
            if len(row) <= max_col:
                continue

            # Try to parse date — skip header rows that fail
            raw_date = row[date_col].strip()
            txn_date = BankFeedService._parse_flexible_date(raw_date)
            if not txn_date:
                # Likely a header row or invalid row
                continue

            # Parse amount
            raw_amount = row[amount_col].strip()
            amount = BankFeedService._parse_amount(raw_amount)
            if amount is None:
                logger.warning("Skipping CSV row %d: unparseable amount '%s'", row_num, raw_amount)
                continue

            description = row[desc_col].strip() if desc_col < len(row) else ""
            reference = (
                row[ref_col].strip()
                if ref_col is not None and ref_col < len(row)
                else None
            )
            currency = (
                row[currency_col].strip()
                if currency_col is not None and currency_col < len(row)
                else None
            )

            txn: dict = {
                "date": txn_date,
                "description": description or "CSV Transaction",
                "amount": amount,
                "reference": reference,
            }
            if currency:
                txn["currency"] = currency

            transactions.append(txn)

        return transactions

    @staticmethod
    def _parse_flexible_date(raw: str) -> date | None:
        """Try multiple date formats commonly found in bank CSVs."""
        formats = (
            "%Y-%m-%d",      # 2024-01-15
            "%m/%d/%Y",      # 01/15/2024
            "%d/%m/%Y",      # 15/01/2024
            "%m-%d-%Y",      # 01-15-2024
            "%d-%m-%Y",      # 15-01-2024
            "%Y/%m/%d",      # 2024/01/15
            "%d.%m.%Y",      # 15.01.2024
            "%m.%d.%Y",      # 01.15.2024
            "%Y%m%d",        # 20240115
            "%d %b %Y",      # 15 Jan 2024
            "%b %d, %Y",     # Jan 15, 2024
        )
        cleaned = raw.strip()
        for fmt in formats:
            try:
                return datetime.strptime(cleaned, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_amount(raw: str) -> float | None:
        """Parse an amount string, handling various locale formats."""
        if not raw:
            return None
        # Remove currency symbols, spaces, and non-breaking spaces
        cleaned = re.sub(r"[^\d.,\-+]", "", raw)
        if not cleaned:
            return None

        # Handle European format: 1.234,56 -> 1234.56
        if re.match(r"^-?\d{1,3}(\.\d{3})*(,\d{1,2})?$", cleaned):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        # Handle comma as thousands separator: 1,234.56 -> 1234.56
        elif "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(",", "")
        # Handle comma as decimal separator: 123,45 -> 123.45
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")

        try:
            return float(cleaned)
        except ValueError:
            return None

    # ── CAMT.053 Parser ───────────────────────────────────────────────

    @staticmethod
    def _parse_camt053(content: str) -> dict:
        """Parse CAMT.053 ISO 20022 XML bank statement.

        Structure: Document > BkToCstmrStmt > Stmt > Ntry (entries)
        Each Ntry contains: BookgDt, Amt, CdtDbtInd, NtryRef, NtryDtls
        """
        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            raise ValidationError(f"Invalid CAMT.053 XML: {e}") from e

        # Detect namespace — try known CAMT.053 versions
        ns = ""
        root_tag = root.tag
        ns_match = re.match(r"\{(.+)\}", root_tag)
        if ns_match:
            ns = ns_match.group(1)

        def tag(name: str) -> str:
            return f"{{{ns}}}{name}" if ns else name

        transactions: list[dict] = []
        balance_start = 0.0
        balance_end = 0.0

        # Find Stmt elements
        for stmt in root.iter(tag("Stmt")):
            # Extract balances
            for bal in stmt.iter(tag("Bal")):
                tp = bal.find(f"{tag('Tp')}/{tag('CdOrPrtry')}/{tag('Cd')}")
                amt_elem = bal.find(tag("Amt"))

                if tp is not None and amt_elem is not None and amt_elem.text:
                    try:
                        bal_amount = float(amt_elem.text.strip())
                    except ValueError:
                        continue

                    cd_dbt = bal.find(tag("CdtDbtInd"))
                    if cd_dbt is not None and cd_dbt.text and cd_dbt.text.strip() == "DBIT":
                        bal_amount = -bal_amount

                    if tp.text and tp.text.strip() == "OPBD":
                        balance_start = bal_amount
                    elif tp.text and tp.text.strip() == "CLBD":
                        balance_end = bal_amount

            # Extract entries (Ntry)
            for ntry in stmt.iter(tag("Ntry")):
                txn = BankFeedService._extract_camt053_entry(ntry, tag)
                if txn:
                    transactions.append(txn)

        return {
            "transactions": transactions,
            "balance_start": balance_start,
            "balance_end": balance_end,
        }

    @staticmethod
    def _extract_camt053_entry(ntry, tag) -> dict | None:
        """Extract a single CAMT.053 Ntry element into a transaction dict."""
        # Amount
        amt_elem = ntry.find(tag("Amt"))
        if amt_elem is None or not amt_elem.text:
            return None

        try:
            amount = float(amt_elem.text.strip())
        except ValueError:
            return None

        # Credit/Debit indicator
        cd_dbt = ntry.find(tag("CdtDbtInd"))
        if cd_dbt is not None and cd_dbt.text and cd_dbt.text.strip() == "DBIT":
            amount = -amount

        # Currency from Amt attribute
        currency = amt_elem.get("Ccy", "USD")

        # Booking date
        bookg_dt = ntry.find(f"{tag('BookgDt')}/{tag('Dt')}")
        if bookg_dt is None:
            # Fall back to ValDt
            bookg_dt = ntry.find(f"{tag('ValDt')}/{tag('Dt')}")

        if bookg_dt is None or not bookg_dt.text:
            return None

        try:
            txn_date = datetime.strptime(bookg_dt.text.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None

        # Description: try multiple locations
        description = None
        # NtryDtls > TxDtls > RmtInf > Ustrd
        ustrd = ntry.find(
            f"{tag('NtryDtls')}/{tag('TxDtls')}/{tag('RmtInf')}/{tag('Ustrd')}"
        )
        if ustrd is not None and ustrd.text:
            description = ustrd.text.strip()

        # AddtlNtryInf as fallback
        if not description:
            addtl = ntry.find(tag("AddtlNtryInf"))
            if addtl is not None and addtl.text:
                description = addtl.text.strip()

        # Reference
        reference = None
        ntry_ref = ntry.find(tag("NtryRef"))
        if ntry_ref is not None and ntry_ref.text:
            reference = ntry_ref.text.strip()

        # AcctSvcrRef as fallback
        if not reference:
            acct_ref = ntry.find(tag("AcctSvcrRef"))
            if acct_ref is not None and acct_ref.text:
                reference = acct_ref.text.strip()

        # EndToEndId from TxDtls as fallback
        if not reference:
            e2e = ntry.find(
                f"{tag('NtryDtls')}/{tag('TxDtls')}/{tag('Refs')}/{tag('EndToEndId')}"
            )
            if e2e is not None and e2e.text and e2e.text.strip() != "NOTPROVIDED":
                reference = e2e.text.strip()

        return {
            "date": txn_date,
            "description": description or "CAMT.053 Entry",
            "amount": amount,
            "reference": reference,
            "currency": currency,
        }

    # ── QIF Parser ────────────────────────────────────────────────────

    @staticmethod
    def _parse_qif(content: str) -> list[dict]:
        """Parse QIF (Quicken Interchange Format) content.

        QIF records are separated by '^'. Each record contains lines starting
        with a field code character:
            D = date
            T = amount
            U = amount (alternate)
            P = payee
            N = check number / reference
            M = memo
            L = category
        The file may begin with a !Type: header line.
        """
        transactions: list[dict] = []
        lines = content.splitlines()

        current: dict[str, str] = {}

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            # Skip header lines
            if line.startswith("!"):
                continue

            # Record separator
            if line == "^":
                txn = BankFeedService._build_qif_transaction(current)
                if txn:
                    transactions.append(txn)
                current = {}
                continue

            # Parse field code
            code = line[0]
            value = line[1:].strip()

            if code == "D":
                current["date"] = value
            elif code == "T":
                current["amount"] = value
            elif code == "U":
                # Alternate amount field — use if T not set
                if "amount" not in current:
                    current["amount"] = value
            elif code == "P":
                current["payee"] = value
            elif code == "N":
                current["reference"] = value
            elif code == "M":
                current["memo"] = value
            elif code == "L":
                current["category"] = value

        # Handle last record if file doesn't end with ^
        if current:
            txn = BankFeedService._build_qif_transaction(current)
            if txn:
                transactions.append(txn)

        return transactions

    @staticmethod
    def _build_qif_transaction(fields: dict[str, str]) -> dict | None:
        """Build a transaction dict from parsed QIF fields."""
        if "date" not in fields or "amount" not in fields:
            return None

        # Parse date — QIF uses M/D/Y or M/D'Y formats
        raw_date = fields["date"]
        txn_date = BankFeedService._parse_qif_date(raw_date)
        if not txn_date:
            return None

        amount = BankFeedService._parse_amount(fields["amount"])
        if amount is None:
            return None

        # Description: prefer payee, fall back to memo
        description = fields.get("payee") or fields.get("memo") or "QIF Transaction"

        # Notes: combine memo and category if both present
        notes_parts = []
        if fields.get("memo") and fields.get("payee"):
            notes_parts.append(fields["memo"])
        if fields.get("category"):
            notes_parts.append(f"Category: {fields['category']}")

        return {
            "date": txn_date,
            "description": description,
            "amount": amount,
            "reference": fields.get("reference"),
            "notes": "; ".join(notes_parts) if notes_parts else None,
        }

    @staticmethod
    def _parse_qif_date(raw: str) -> date | None:
        """Parse QIF date formats.

        Common QIF formats:
            M/D/YYYY, M/D'YYYY, MM/DD/YY, M-D-YYYY
        The apostrophe format uses ' to separate day from year.
        """
        cleaned = raw.strip()

        # Handle apostrophe year separator: 1/15'2024 -> 1/15/2024
        cleaned = cleaned.replace("'", "/")

        # Try standard formats
        formats = (
            "%m/%d/%Y",  # 01/15/2024 or 1/15/2024
            "%m/%d/%y",  # 01/15/24 or 1/15/24
            "%m-%d-%Y",  # 01-15-2024
            "%m-%d-%y",  # 01-15-24
            "%d/%m/%Y",  # 15/01/2024
            "%Y-%m-%d",  # 2024-01-15
        )
        for fmt in formats:
            try:
                return datetime.strptime(cleaned, fmt).date()
            except ValueError:
                continue
        return None
