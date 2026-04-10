"""Invoice email service.

Sends invoice PDFs and payment reminders by email. Actual mail delivery
is delegated to a pluggable EmailBackend so the service works with SMTP,
transactional APIs (SendGrid, SES), or a no-op backend in tests.
"""

from __future__ import annotations

import smtplib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import NotFoundError
from src.core.repository.base import BaseRepository
from src.modules.accounting.models.move import Move, OUTBOUND_TYPES
from src.modules.invoicing.services.pdf_service import InvoicePDFService


# ── Email data structures ────────────────────────────────────────────


@dataclass
class EmailMessage:
    """Represents a fully-formed email ready for delivery."""

    to: list[str]
    subject: str
    body_html: str
    body_text: str | None = None
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    from_address: str = "noreply@foundrix.io"
    reply_to: str | None = None
    attachments: list[EmailAttachment] = field(default_factory=list)


@dataclass
class EmailAttachment:
    """A single email attachment."""

    filename: str
    content: bytes
    content_type: str = "application/pdf"


# ── Email backend protocol ──────────────────────────────────────────


@runtime_checkable
class EmailBackend(Protocol):
    """Protocol that any email delivery backend must satisfy."""

    async def send(self, message: EmailMessage) -> bool:
        """Send the message. Returns True on success."""
        ...


class SMTPEmailBackend:
    """SMTP-based email backend.

    Connects to an SMTP server to deliver messages. Configuration is
    provided at instantiation time so it can be loaded from settings.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls

    async def send(self, message: EmailMessage) -> bool:
        """Send the email via SMTP.

        Note: Uses synchronous smtplib. For production consider wrapping
        in ``asyncio.to_thread`` or using aiosmtplib.
        """
        msg = MIMEMultipart("mixed")
        msg["From"] = message.from_address
        msg["To"] = ", ".join(message.to)
        msg["Subject"] = message.subject
        if message.cc:
            msg["Cc"] = ", ".join(message.cc)
        if message.reply_to:
            msg["Reply-To"] = message.reply_to

        # Body
        body_part = MIMEMultipart("alternative")
        if message.body_text:
            body_part.attach(MIMEText(message.body_text, "plain", "utf-8"))
        body_part.attach(MIMEText(message.body_html, "html", "utf-8"))
        msg.attach(body_part)

        # Attachments
        for att in message.attachments:
            part = MIMEApplication(att.content, Name=att.filename)
            part["Content-Disposition"] = f'attachment; filename="{att.filename}"'
            msg.attach(part)

        # Deliver
        all_recipients = message.to + message.cc + message.bcc
        with smtplib.SMTP(self.host, self.port) as server:
            if self.use_tls:
                server.starttls()
            if self.username and self.password:
                server.login(self.username, self.password)
            server.sendmail(message.from_address, all_recipients, msg.as_string())

        return True


# ── Move repository shortcut ────────────────────────────────────────


class _MoveRepo(BaseRepository[Move]):
    model = Move


# ── Service ──────────────────────────────────────────────────────────


_MOVE_TYPE_LABELS: dict[str, str] = {
    "out_invoice": "Invoice",
    "out_refund": "Credit Note",
    "in_invoice": "Vendor Bill",
    "in_refund": "Vendor Refund",
    "out_receipt": "Sales Receipt",
    "in_receipt": "Purchase Receipt",
}


class InvoiceEmailService:
    """Composes and sends invoice-related emails."""

    def __init__(
        self,
        db: AsyncSession,
        backend: EmailBackend | None = None,
    ) -> None:
        self.db = db
        self._move_repo = _MoveRepo(db)
        self._pdf_service = InvoicePDFService(db)
        self._backend = backend

    @property
    def backend(self) -> EmailBackend:
        if self._backend is None:
            raise RuntimeError(
                "No email backend configured. Provide an EmailBackend "
                "instance when constructing InvoiceEmailService."
            )
        return self._backend

    # ── Public API ───────────────────────────────────────────────────

    async def send_invoice_email(
        self,
        move_id: uuid.UUID,
        recipient_email: str,
        *,
        cc: list[str] | None = None,
        subject: str | None = None,
        body: str | None = None,
        attach_pdf: bool = True,
    ) -> bool:
        """Send an invoice email with optional PDF attachment.

        Returns True if the email was sent successfully.
        """
        move = await self._move_repo.get_by_id_or_raise(move_id, "Move")
        preview = self._compose_invoice_email(move, subject=subject, body=body)

        attachments: list[EmailAttachment] = []
        if attach_pdf:
            pdf_bytes = await self._pdf_service.generate_invoice_pdf(move_id)
            filename = f"{move.name or 'invoice'}.pdf".replace("/", "-")
            attachments.append(
                EmailAttachment(filename=filename, content=pdf_bytes)
            )

        message = EmailMessage(
            to=[recipient_email],
            cc=cc or [],
            subject=preview["subject"],
            body_html=preview["body_html"],
            body_text=preview["body_text"],
            attachments=attachments,
        )
        return await self.backend.send(message)

    async def send_payment_reminder(
        self,
        move_id: uuid.UUID,
        recipient_email: str,
    ) -> bool:
        """Send a payment reminder for an overdue invoice."""
        move = await self._move_repo.get_by_id_or_raise(move_id, "Move")

        label = _MOVE_TYPE_LABELS.get(move.move_type, "Invoice")
        subject = f"Payment Reminder — {label} {move.name or 'DRAFT'}"

        overdue_note = ""
        if move.invoice_date_due:
            from datetime import date as _date

            days_overdue = (_date.today() - move.invoice_date_due).days
            if days_overdue > 0:
                overdue_note = f"<p>This invoice is <strong>{days_overdue} day(s) overdue</strong>.</p>"

        body_html = (
            f"<p>Dear Customer,</p>"
            f"<p>This is a friendly reminder that {label.lower()} "
            f"<strong>{move.name or 'DRAFT'}</strong> has an outstanding "
            f"balance of <strong>{move.currency_code} {move.amount_residual:,.2f}</strong>.</p>"
            f"{overdue_note}"
            f"<p>Please arrange payment at your earliest convenience.</p>"
            f"<p>Thank you,<br/>Accounts Receivable</p>"
        )

        body_text = (
            f"Dear Customer,\n\n"
            f"This is a friendly reminder that {label.lower()} "
            f"{move.name or 'DRAFT'} has an outstanding balance of "
            f"{move.currency_code} {move.amount_residual:,.2f}.\n\n"
            f"Please arrange payment at your earliest convenience.\n\n"
            f"Thank you,\nAccounts Receivable"
        )

        # Attach PDF
        pdf_bytes = await self._pdf_service.generate_invoice_pdf(move_id)
        filename = f"{move.name or 'invoice'}.pdf".replace("/", "-")

        message = EmailMessage(
            to=[recipient_email],
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            attachments=[EmailAttachment(filename=filename, content=pdf_bytes)],
        )
        return await self.backend.send(message)

    async def send_batch_emails(
        self,
        move_ids: list[uuid.UUID],
        *,
        template: str | None = None,
    ) -> dict[uuid.UUID, bool]:
        """Send invoice emails for multiple moves.

        Args:
            move_ids: List of move IDs to email.
            template: Optional email body override applied to all.

        Returns:
            Mapping of move_id to send success status.
        """
        results: dict[uuid.UUID, bool] = {}
        for mid in move_ids:
            move = await self._move_repo.get_by_id(mid)
            if move is None:
                results[mid] = False
                continue

            # Derive recipient from partner (placeholder — real implementation
            # would look up partner email from the partners table)
            recipient = f"partner-{move.partner_id}@placeholder.local"

            try:
                ok = await self.send_invoice_email(
                    mid, recipient, body=template
                )
                results[mid] = ok
            except Exception:
                results[mid] = False

        return results

    async def get_email_preview(
        self, move_id: uuid.UUID
    ) -> dict[str, str]:
        """Return the subject and body that would be sent, without sending.

        Returns:
            Dict with keys ``subject``, ``body_html``, ``body_text``.
        """
        move = await self._move_repo.get_by_id_or_raise(move_id, "Move")
        return self._compose_invoice_email(move)

    # ── Internal helpers ─────────────────────────────────────────────

    def _compose_invoice_email(
        self,
        move: Move,
        *,
        subject: str | None = None,
        body: str | None = None,
    ) -> dict[str, str]:
        """Compose subject and body for an invoice email."""
        label = _MOVE_TYPE_LABELS.get(move.move_type, "Invoice")
        inv_name = move.name or "DRAFT"

        final_subject = subject or f"{label} {inv_name}"

        if body:
            final_body_html = body
            final_body_text = body  # caller-provided, assume plain works too
        else:
            due_line = ""
            if move.invoice_date_due:
                due_line = (
                    f"<p>Payment is due by <strong>{move.invoice_date_due}</strong>.</p>"
                )

            final_body_html = (
                f"<p>Dear Customer,</p>"
                f"<p>Please find attached {label.lower()} "
                f"<strong>{inv_name}</strong> for "
                f"<strong>{move.currency_code} {move.amount_total:,.2f}</strong>.</p>"
                f"{due_line}"
                f"<p>If you have any questions, please do not hesitate to contact us.</p>"
                f"<p>Best regards,<br/>Accounts Team</p>"
            )
            final_body_text = (
                f"Dear Customer,\n\n"
                f"Please find attached {label.lower()} {inv_name} "
                f"for {move.currency_code} {move.amount_total:,.2f}.\n"
            )
            if move.invoice_date_due:
                final_body_text += (
                    f"Payment is due by {move.invoice_date_due}.\n"
                )
            final_body_text += (
                f"\nIf you have any questions, please do not hesitate to contact us.\n\n"
                f"Best regards,\nAccounts Team"
            )

        return {
            "subject": final_subject,
            "body_html": final_body_html,
            "body_text": final_body_text,
        }
