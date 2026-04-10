"""Recurring invoice service — template CRUD and automated invoice generation.

Handles:
- Creating and managing recurring invoice templates
- Generating invoices from due templates
- Advancing the next invoice date based on frequency
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.core.events import event_bus
from src.modules.invoicing.models.recurring import (
    RecurringTemplate,
    RecurringTemplateLine,
    RecurringFrequency,
)
from src.modules.invoicing.repositories.recurring_repo import (
    RecurringTemplateRepository,
    RecurringTemplateLineRepository,
)
from src.modules.invoicing.schemas.recurring import (
    RecurringTemplateCreate,
    RecurringTemplateUpdate,
)

logger = logging.getLogger(__name__)


FREQUENCY_DELTA = {
    RecurringFrequency.DAILY: timedelta(days=1),
    RecurringFrequency.WEEKLY: timedelta(weeks=1),
    RecurringFrequency.MONTHLY: relativedelta(months=1),
    RecurringFrequency.QUARTERLY: relativedelta(months=3),
    RecurringFrequency.SEMI_ANNUALLY: relativedelta(months=6),
    RecurringFrequency.YEARLY: relativedelta(years=1),
}


class RecurringInvoiceService:
    """Manages recurring invoice templates and invoice generation."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.template_repo = RecurringTemplateRepository(db)
        self.line_repo = RecurringTemplateLineRepository(db)

    # ── CRUD ──────────────────────────────────────────────────────────

    async def get_template(self, template_id: uuid.UUID) -> RecurringTemplate:
        """Get a template with its lines."""
        template = await self.template_repo.get_with_lines(template_id)
        if not template:
            raise NotFoundError("RecurringTemplate", str(template_id))
        return template

    async def list_templates(self, *, active_only: bool = True) -> list[RecurringTemplate]:
        """List recurring templates."""
        if active_only:
            return await self.template_repo.list_active()
        result = await self.template_repo.list_all()
        return result

    async def list_by_partner(self, partner_id: uuid.UUID) -> list[RecurringTemplate]:
        """List templates for a specific partner."""
        return await self.template_repo.get_by_partner(partner_id)

    async def create_template(self, data: RecurringTemplateCreate) -> RecurringTemplate:
        """Create a new recurring invoice template with lines."""
        template = RecurringTemplate(
            name=data.name,
            partner_id=data.partner_id,
            journal_id=data.journal_id,
            frequency=RecurringFrequency(data.frequency),
            next_invoice_date=data.next_invoice_date,
            end_date=data.end_date,
            currency_code=data.currency_code,
            payment_term_id=data.payment_term_id,
            fiscal_position_id=data.fiscal_position_id,
            incoterm_id=data.incoterm_id,
            auto_send=data.auto_send,
            auto_post=data.auto_post,
            note=data.note,
        )
        self.db.add(template)
        await self.db.flush()

        for line_data in data.lines:
            line = RecurringTemplateLine(
                template_id=template.id,
                product_id=line_data.product_id,
                name=line_data.name,
                account_id=line_data.account_id,
                quantity=line_data.quantity,
                price_unit=line_data.price_unit,
                discount=line_data.discount,
                tax_ids=line_data.tax_ids,
                sequence=line_data.sequence,
            )
            self.db.add(line)

        await self.db.flush()
        await self.db.refresh(template)

        await event_bus.publish("recurring_template.created", {
            "template_id": str(template.id),
            "name": template.name,
        })

        return template

    async def update_template(
        self, template_id: uuid.UUID, data: RecurringTemplateUpdate,
    ) -> RecurringTemplate:
        """Update an existing template."""
        template = await self.template_repo.get_with_lines(template_id)
        if not template:
            raise NotFoundError("RecurringTemplate", str(template_id))

        update_fields = data.model_dump(exclude_unset=True)
        if "frequency" in update_fields and update_fields["frequency"] is not None:
            update_fields["frequency"] = RecurringFrequency(update_fields["frequency"])

        for key, value in update_fields.items():
            setattr(template, key, value)

        await self.db.flush()
        await self.db.refresh(template)
        return template

    async def deactivate_template(self, template_id: uuid.UUID) -> RecurringTemplate:
        """Deactivate a recurring template."""
        template = await self.template_repo.get_with_lines(template_id)
        if not template:
            raise NotFoundError("RecurringTemplate", str(template_id))
        template.is_active = False
        await self.db.flush()
        return template

    # ── Invoice Generation ────────────────────────────────────────────

    async def generate_due_invoices(self, as_of: date | None = None) -> list[dict]:
        """Generate invoices for all templates that are due.

        Returns a list of dicts with template_id and move_id for each generated invoice.
        """
        from src.modules.invoicing.services.invoice_service import InvoiceService
        from src.modules.invoicing.schemas.invoice import (
            CreateCustomerInvoice,
            InvoiceLineInput,
        )

        invoice_svc = InvoiceService(self.db)
        target = as_of or date.today()
        due_templates = await self.template_repo.get_due_templates(target)

        results = []
        for template in due_templates:
            if template.is_expired:
                template.is_active = False
                continue

            if not template.lines:
                logger.warning("Skipping template %s: no lines", template.id)
                continue

            try:
                invoice = await self._generate_invoice_from_template(
                    template, invoice_svc,
                )
                results.append({
                    "template_id": str(template.id),
                    "move_id": str(invoice.id),
                    "partner_id": str(template.partner_id),
                })

                # Advance next invoice date
                delta = FREQUENCY_DELTA[template.frequency]
                template.next_invoice_date = template.next_invoice_date + delta

                await event_bus.publish("recurring_template.invoice_generated", {
                    "template_id": str(template.id),
                    "move_id": str(invoice.id),
                })

            except Exception:
                logger.exception(
                    "Failed to generate invoice for template %s", template.id,
                )

        await self.db.flush()
        return results

    async def _generate_invoice_from_template(
        self,
        template: RecurringTemplate,
        invoice_svc,
    ):
        """Create a single invoice from a recurring template."""
        from src.modules.invoicing.schemas.invoice import (
            CreateCustomerInvoice,
            InvoiceLineInput,
        )

        lines = [
            InvoiceLineInput(
                product_id=line.product_id,
                name=line.name,
                account_id=line.account_id,
                quantity=line.quantity,
                price_unit=line.price_unit,
                discount=line.discount,
                tax_ids=line.tax_ids or [],
            )
            for line in sorted(template.lines, key=lambda l: l.sequence)
        ]

        data = CreateCustomerInvoice(
            partner_id=template.partner_id,
            invoice_date=template.next_invoice_date,
            journal_id=template.journal_id,
            currency_code=template.currency_code,
            payment_term_id=template.payment_term_id,
            fiscal_position_id=template.fiscal_position_id,
            incoterm_id=template.incoterm_id,
            narration=template.note,
            lines=lines,
        )

        invoice = await invoice_svc.create_customer_invoice(data)

        # Auto-post if configured
        if template.auto_post:
            invoice = await invoice_svc.confirm_invoice(invoice.id)

        return invoice
