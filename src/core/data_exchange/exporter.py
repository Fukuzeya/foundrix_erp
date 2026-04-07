"""Data exporter for generating CSV and Excel files from query results.

Modules define exportable fields and the exporter handles serialization
and streaming.

Usage::

    exporter = DataExporter()
    csv_bytes = await exporter.to_csv(
        rows=[{"name": "John", "email": "john@example.com"}],
        columns=["name", "email"],
        headers={"name": "Full Name", "email": "Email Address"},
    )
"""

import csv
import io
import logging
from typing import Any

logger = logging.getLogger(__name__)


class DataExporter:
    """Export data to CSV or Excel format."""

    async def to_csv(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        *,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        """Export rows to CSV bytes.

        Args:
            rows: List of dicts, each representing a row.
            columns: Column keys to include, in order.
            headers: Optional mapping of column keys to display headers.

        Returns:
            UTF-8 encoded CSV bytes.
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header row
        header_row = [headers.get(col, col) if headers else col for col in columns]
        writer.writerow(header_row)

        # Write data rows
        for row in rows:
            writer.writerow([str(row.get(col, "")) for col in columns])

        return output.getvalue().encode("utf-8")

    async def to_excel(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        *,
        headers: dict[str, str] | None = None,
        sheet_name: str = "Export",
    ) -> bytes:
        """Export rows to Excel (.xlsx) bytes.

        Requires openpyxl. Falls back to CSV if not installed.
        """
        try:
            from openpyxl import Workbook

            wb = Workbook()
            ws = wb.active
            ws.title = sheet_name

            # Header row
            header_row = [headers.get(col, col) if headers else col for col in columns]
            ws.append(header_row)

            # Data rows
            for row in rows:
                ws.append([row.get(col, "") for col in columns])

            output = io.BytesIO()
            wb.save(output)
            return output.getvalue()

        except ImportError:
            logger.warning("openpyxl not installed, falling back to CSV")
            return await self.to_csv(rows, columns, headers=headers)
