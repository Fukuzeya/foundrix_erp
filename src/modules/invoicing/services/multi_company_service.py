"""Multi-company invoicing service — inter-company invoice mirroring and sync.

Handles:
- Automatic invoice mirroring between companies
- Pending transaction synchronization
- Inter-company balance calculation
- Rule CRUD operations
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError, ValidationError
from src.core.events import event_bus
from src.modules.accounting.models.move import Move, MoveLine
from src.modules.accounting.repositories.move_repo import MoveRepository, MoveLineRepository
from src.modules.invoicing.models.multi_company import (
    InterCompanyRule,
    InterCompanyTransaction,
)
from src.modules.invoicing.repositories.multi_company_repo import (
    InterCompanyRuleRepository,
    InterCompanyTransactionRepository,
)
from src.modules.invoicing.schemas.multi_company import (
    InterCompanyRuleCreate,
    InterCompanyRuleUpdate,
    InterCompanySummary,
    InterCompanySyncResult,
)

logger = logging.getLogger(__name__)

# Move type mapping: source type -> mirrored target type
_MIRROR_TYPE_MAP = {
    "out_invoice": "in_invoice",
    "out_refund": "in_refund",
    "in_invoice": "out_invoice",
    "in_refund": "out_refund",
}


class MultiCompanyService:
    """Service for inter-company invoice operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.rule_repo = InterCompanyRuleRepository(db)
        self.tx_repo = InterCompanyTransactionRepository(db)
        self.move_repo = MoveRepository(db)
        self.move_line_repo = MoveLineRepository(db)

    # ── Invoice mirroring ─────────────────────────────────────────────

    async def mirror_invoice(self, source_move_id: uuid.UUID) -> InterCompanySyncResult:
        """Mirror a source invoice to the target company based on matching rules.

        Finds the applicable inter-company rule by the source move's company
        and ``invoice_mirror`` type, then creates the mirrored move with mapped
        accounts and taxes.
        """
        source_move = await self.move_repo.get_by_id_or_raise(
            source_move_id, resource_name="Move",
        )

        if source_move.move_type not in _MIRROR_TYPE_MAP:
            raise BusinessRuleError(
                f"Move type '{source_move.move_type}' cannot be mirrored. "
                f"Only invoice/refund types are supported.",
            )

        # Check for existing mirror
        existing = await self.tx_repo.get_by_source_move(source_move_id)
        if existing and existing.state in ("synced", "pending"):
            raise BusinessRuleError(
                f"Move {source_move_id} already has an inter-company transaction "
                f"in state '{existing.state}'.",
            )

        # Find matching rule
        rule = await self.rule_repo.find_matching_rule(
            source_company_id=source_move.journal.company_id
            if hasattr(source_move.journal, "company_id")
            else source_move.partner_id,  # fallback
            rule_type="invoice_mirror",
        )
        if rule is None:
            raise BusinessRuleError(
                "No active invoice_mirror rule found for the source company.",
            )

        # Create the mirrored move and transaction
        try:
            target_move = await self._create_mirror_move(source_move, rule)

            transaction = await self.tx_repo.create(
                rule_id=rule.id,
                source_move_id=source_move.id,
                target_move_id=target_move.id,
                source_company_id=rule.source_company_id,
                target_company_id=rule.target_company_id,
                transaction_type="invoice_mirror",
                amount=source_move.amount_total,
                currency_code=source_move.currency_code,
                state="synced",
                synced_at=datetime.utcnow(),
            )

            await event_bus.publish("intercompany.invoice_mirrored", {
                "transaction_id": str(transaction.id),
                "source_move_id": str(source_move.id),
                "target_move_id": str(target_move.id),
                "rule_id": str(rule.id),
                "amount": source_move.amount_total,
            })

            logger.info(
                "Mirrored move %s -> %s (rule=%s)",
                source_move.id, target_move.id, rule.id,
            )

            return InterCompanySyncResult(
                source_move_id=source_move.id,
                target_move_id=target_move.id,
                state="synced",
            )

        except Exception as exc:
            # Record the failure
            await self.tx_repo.create(
                rule_id=rule.id,
                source_move_id=source_move.id,
                target_move_id=None,
                source_company_id=rule.source_company_id,
                target_company_id=rule.target_company_id,
                transaction_type="invoice_mirror",
                amount=source_move.amount_total,
                currency_code=source_move.currency_code,
                state="failed",
                error_message=str(exc),
            )

            await event_bus.publish("intercompany.sync_failed", {
                "source_move_id": str(source_move.id),
                "rule_id": str(rule.id),
                "error": str(exc),
            })

            logger.exception("Failed to mirror move %s", source_move.id)

            return InterCompanySyncResult(
                source_move_id=source_move.id,
                target_move_id=None,
                state="failed",
                error=str(exc),
            )

    # ── Sync pending ──────────────────────────────────────────────────

    async def sync_pending_transactions(self) -> list[InterCompanySyncResult]:
        """Process all pending inter-company transactions.

        Attempts to mirror each pending transaction. Marks them as synced
        on success or failed on error.
        """
        pending = await self.tx_repo.list_pending()
        results: list[InterCompanySyncResult] = []

        for tx in pending:
            try:
                source_move = await self.move_repo.get_by_id(tx.source_move_id)
                if source_move is None:
                    raise NotFoundError("Move", str(tx.source_move_id))

                rule = await self.rule_repo.get_by_id_or_raise(
                    tx.rule_id, resource_name="InterCompanyRule",
                )

                target_move = await self._create_mirror_move(source_move, rule)

                tx.target_move_id = target_move.id
                tx.state = "synced"
                tx.synced_at = datetime.utcnow()
                tx.error_message = None
                await self.db.flush()

                await event_bus.publish("intercompany.invoice_mirrored", {
                    "transaction_id": str(tx.id),
                    "source_move_id": str(tx.source_move_id),
                    "target_move_id": str(target_move.id),
                    "rule_id": str(tx.rule_id),
                    "amount": tx.amount,
                })

                results.append(InterCompanySyncResult(
                    source_move_id=tx.source_move_id,
                    target_move_id=target_move.id,
                    state="synced",
                ))

            except Exception as exc:
                tx.state = "failed"
                tx.error_message = str(exc)
                await self.db.flush()

                await event_bus.publish("intercompany.sync_failed", {
                    "source_move_id": str(tx.source_move_id),
                    "rule_id": str(tx.rule_id),
                    "error": str(exc),
                })

                results.append(InterCompanySyncResult(
                    source_move_id=tx.source_move_id,
                    target_move_id=None,
                    state="failed",
                    error=str(exc),
                ))

        logger.info(
            "Sync complete: %d processed, %d synced, %d failed",
            len(results),
            sum(1 for r in results if r.state == "synced"),
            sum(1 for r in results if r.state == "failed"),
        )

        return results

    # ── Cancel mirror ─────────────────────────────────────────────────

    async def cancel_mirror(self, transaction_id: uuid.UUID) -> InterCompanyTransaction:
        """Cancel an inter-company transaction by setting its state to cancelled."""
        tx = await self.tx_repo.get_by_id_or_raise(
            transaction_id, resource_name="InterCompanyTransaction",
        )

        if tx.state == "cancelled":
            raise BusinessRuleError("Transaction is already cancelled.")

        tx.state = "cancelled"
        await self.db.flush()

        await event_bus.publish("intercompany.cancelled", {
            "transaction_id": str(tx.id),
            "source_move_id": str(tx.source_move_id),
            "target_move_id": str(tx.target_move_id) if tx.target_move_id else None,
        })

        logger.info("Cancelled inter-company transaction %s", transaction_id)
        return tx

    # ── Inter-company balance ─────────────────────────────────────────

    async def get_inter_company_balance(
        self,
        company_a_id: uuid.UUID,
        company_b_id: uuid.UUID,
    ) -> float:
        """Calculate the net balance between two companies.

        Positive means company_a owes company_b (A is debtor).
        Sums synced transactions in both directions:
        - A->B transactions add to A's debt
        - B->A transactions subtract from A's debt
        """
        # A -> B: amounts company A owes to B
        result_ab = await self.db.execute(
            select(func.coalesce(func.sum(InterCompanyTransaction.amount), 0)).where(
                InterCompanyTransaction.source_company_id == company_a_id,
                InterCompanyTransaction.target_company_id == company_b_id,
                InterCompanyTransaction.state == "synced",
            )
        )
        a_to_b = result_ab.scalar() or 0.0

        # B -> A: amounts company B owes to A
        result_ba = await self.db.execute(
            select(func.coalesce(func.sum(InterCompanyTransaction.amount), 0)).where(
                InterCompanyTransaction.source_company_id == company_b_id,
                InterCompanyTransaction.target_company_id == company_a_id,
                InterCompanyTransaction.state == "synced",
            )
        )
        b_to_a = result_ba.scalar() or 0.0

        return a_to_b - b_to_a

    # ── Rule CRUD ─────────────────────────────────────────────────────

    async def create_rule(self, data: InterCompanyRuleCreate) -> InterCompanyRule:
        """Create a new inter-company rule."""
        if data.source_company_id == data.target_company_id:
            raise ValidationError(
                "Source and target company must be different.",
            )

        valid_types = {"invoice_mirror", "so_to_po", "auto_bill"}
        if data.rule_type not in valid_types:
            raise ValidationError(
                f"Invalid rule_type '{data.rule_type}'. "
                f"Must be one of: {', '.join(sorted(valid_types))}",
            )

        return await self.rule_repo.create(
            name=data.name,
            source_company_id=data.source_company_id,
            target_company_id=data.target_company_id,
            rule_type=data.rule_type,
            auto_validate=data.auto_validate,
            source_journal_id=data.source_journal_id,
            target_journal_id=data.target_journal_id,
            account_mapping=data.account_mapping,
            tax_mapping=data.tax_mapping,
        )

    async def update_rule(
        self,
        rule_id: uuid.UUID,
        data: InterCompanyRuleUpdate,
    ) -> InterCompanyRule:
        """Update an existing inter-company rule."""
        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            raise ValidationError("No fields provided for update.")

        return await self.rule_repo.update(rule_id, **update_data)

    async def list_rules(
        self,
        company_id: uuid.UUID | None = None,
    ) -> list[InterCompanyRule]:
        """List inter-company rules, optionally filtered by company."""
        if company_id is not None:
            return await self.rule_repo.get_active_rules(company_id)
        return await self.rule_repo.list_all()

    async def deactivate_rule(self, rule_id: uuid.UUID) -> InterCompanyRule:
        """Deactivate an inter-company rule."""
        return await self.rule_repo.update(rule_id, is_active=False)

    # ── Transaction queries ───────────────────────────────────────────

    async def list_transactions(
        self,
        company_id: uuid.UUID | None = None,
        state: str | None = None,
    ) -> list[InterCompanyTransaction]:
        """List inter-company transactions with optional filters."""
        filters = []
        if company_id is not None:
            filters.append(
                or_(
                    InterCompanyTransaction.source_company_id == company_id,
                    InterCompanyTransaction.target_company_id == company_id,
                )
            )
        if state is not None:
            filters.append(InterCompanyTransaction.state == state)

        return await self.tx_repo.list_all(filters=filters)

    async def get_transaction(
        self, transaction_id: uuid.UUID,
    ) -> InterCompanyTransaction:
        """Get a single inter-company transaction by ID."""
        return await self.tx_repo.get_by_id_or_raise(
            transaction_id, resource_name="InterCompanyTransaction",
        )

    # ── Summary ───────────────────────────────────────────────────────

    async def get_summary(
        self,
        company_id: uuid.UUID | None = None,
    ) -> InterCompanySummary:
        """Aggregate statistics for inter-company operations."""
        # Rule counts
        rule_filters = []
        if company_id is not None:
            rule_filters.append(
                or_(
                    InterCompanyRule.source_company_id == company_id,
                    InterCompanyRule.target_company_id == company_id,
                )
            )

        total_rules = await self.rule_repo.count(filters=rule_filters if rule_filters else None)
        active_rules = await self.rule_repo.count(
            filters=(rule_filters + [InterCompanyRule.is_active.is_(True)])
            if rule_filters
            else [InterCompanyRule.is_active.is_(True)],
        )

        # Transaction counts by state
        tx_base_filters = []
        if company_id is not None:
            tx_base_filters.append(
                or_(
                    InterCompanyTransaction.source_company_id == company_id,
                    InterCompanyTransaction.target_company_id == company_id,
                )
            )

        pending = await self.tx_repo.count(
            filters=tx_base_filters + [InterCompanyTransaction.state == "pending"],
        )
        synced = await self.tx_repo.count(
            filters=tx_base_filters + [InterCompanyTransaction.state == "synced"],
        )
        failed = await self.tx_repo.count(
            filters=tx_base_filters + [InterCompanyTransaction.state == "failed"],
        )

        return InterCompanySummary(
            total_rules=total_rules,
            active_rules=active_rules,
            pending_transactions=pending,
            synced_transactions=synced,
            failed_transactions=failed,
        )

    # ── Private helpers ───────────────────────────────────────────────

    def _map_account(
        self,
        source_account_id: uuid.UUID,
        rule: InterCompanyRule,
    ) -> uuid.UUID:
        """Map a source account to the target account using the rule's mapping.

        Returns the mapped account ID if a mapping exists, otherwise returns
        the original source account ID.
        """
        if rule.account_mapping and str(source_account_id) in rule.account_mapping:
            return uuid.UUID(rule.account_mapping[str(source_account_id)])
        return source_account_id

    def _map_tax(
        self,
        source_tax_id: uuid.UUID,
        rule: InterCompanyRule,
    ) -> uuid.UUID:
        """Map a source tax to the target tax using the rule's mapping.

        Returns the mapped tax ID if a mapping exists, otherwise returns
        the original source tax ID.
        """
        if rule.tax_mapping and str(source_tax_id) in rule.tax_mapping:
            return uuid.UUID(rule.tax_mapping[str(source_tax_id)])
        return source_tax_id

    async def _create_mirror_move(
        self,
        source_move: Move,
        rule: InterCompanyRule,
    ) -> Move:
        """Build and persist a mirrored Move in the target company.

        Maps the move type (out_invoice -> in_invoice, etc.), applies account
        and tax mappings from the rule, and assigns the target journal.
        """
        mirror_type = _MIRROR_TYPE_MAP.get(source_move.move_type)
        if mirror_type is None:
            raise BusinessRuleError(
                f"Cannot mirror move type '{source_move.move_type}'.",
            )

        # Determine the target journal
        target_journal_id = rule.target_journal_id or source_move.journal_id

        # Create the mirrored move header
        target_move = await self.move_repo.create(
            name="/",  # sequence assigned on posting
            move_type=mirror_type,
            state="draft",
            partner_id=source_move.partner_id,
            date=source_move.date,
            invoice_date=source_move.invoice_date,
            invoice_date_due=source_move.invoice_date_due,
            journal_id=target_journal_id,
            currency_code=source_move.currency_code,
            currency_rate=source_move.currency_rate,
            amount_untaxed=source_move.amount_untaxed,
            amount_tax=source_move.amount_tax,
            amount_total=source_move.amount_total,
            amount_residual=source_move.amount_total,
            ref=f"IC:{source_move.name}",
            narration=source_move.narration,
        )

        # Mirror each source line with account/tax mapping
        source_lines = await self.move_line_repo.get_by_move(source_move.id)
        for line in source_lines:
            mapped_account_id = self._map_account(line.account_id, rule)
            mapped_tax_line_id = (
                self._map_tax(line.tax_line_id, rule)
                if line.tax_line_id
                else None
            )

            await self.move_line_repo.create(
                move_id=target_move.id,
                account_id=mapped_account_id,
                partner_id=line.partner_id,
                name=line.name,
                product_id=line.product_id,
                quantity=line.quantity,
                price_unit=line.price_unit,
                discount=line.discount,
                debit=line.credit,  # swap debit/credit for mirror
                credit=line.debit,
                balance=-(line.balance),
                amount_currency=-(line.amount_currency),
                currency_code=line.currency_code,
                price_subtotal=line.price_subtotal,
                price_total=line.price_total,
                display_type=line.display_type,
                tax_line_id=mapped_tax_line_id,
                tax_base_amount=line.tax_base_amount,
                date_maturity=line.date_maturity,
                sequence=line.sequence,
                analytic_distribution=line.analytic_distribution,
            )

        # Auto-validate if the rule says so
        if rule.auto_validate:
            target_move.state = "posted"
            await self.db.flush()

        await self.db.refresh(target_move)
        return target_move
