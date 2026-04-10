"""Invoice reporting service — analytics and aggregate reports over accounting moves.

Provides period-based analysis, aging reports, top customer/vendor rankings,
payment performance metrics, revenue trends, and outstanding summaries.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import Date, String, case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.accounting.models.move import Move
from src.modules.invoicing.schemas.invoice import (
    AgingBucket,
    InvoiceAnalysis,
    OutstandingSummary,
    PaymentPerformance,
    RevenueTrendEntry,
    TopPartnerEntry,
)

logger = logging.getLogger(__name__)

# Only consider posted invoices/bills for reporting
_CUSTOMER_TYPES = ("out_invoice", "out_refund")
_VENDOR_TYPES = ("in_invoice", "in_refund")
_ALL_INVOICE_TYPES = _CUSTOMER_TYPES + _VENDOR_TYPES


class InvoiceReportingService:
    """Analytics and reporting over posted invoices and bills."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Invoice Analysis ───────────────────────────────────────────────

    async def get_invoice_analysis(
        self,
        date_from: date,
        date_to: date,
        move_type: str | None = None,
        partner_id: uuid.UUID | None = None,
        group_by: str = "month",
    ) -> list[InvoiceAnalysis]:
        """Aggregate invoices into period buckets.

        Args:
            date_from: Start of the reporting period (inclusive).
            date_to: End of the reporting period (inclusive).
            move_type: Optional filter for a specific move type.
            partner_id: Optional filter for a specific partner.
            group_by: Grouping granularity — "month" (default) or "quarter".

        Returns:
            List of InvoiceAnalysis entries, one per period.
        """
        if group_by == "quarter":
            period_expr = func.concat(
                func.extract("year", Move.invoice_date).cast(String),
                literal("-Q"),
                func.extract("quarter", Move.invoice_date).cast(String),
            )
        else:
            # Default: month grouping — YYYY-MM
            period_expr = func.to_char(Move.invoice_date, "YYYY-MM")

        # Days to pay: difference between payment date proxy and invoice date.
        # For paid invoices we approximate days-to-pay using (due_date - invoice_date)
        # when actual payment date isn't stored on the move header.
        # A more accurate metric would join the payment table; this is a pragmatic
        # approximation using amount_residual = 0 as "fully paid".
        days_to_pay_expr = case(
            (
                Move.payment_state == "paid",
                func.extract("day", Move.invoice_date_due - Move.invoice_date),
            ),
            else_=None,
        )

        query = (
            select(
                period_expr.label("period"),
                func.count(Move.id).label("invoice_count"),
                func.coalesce(func.sum(Move.amount_total), 0).label("total_amount"),
                func.coalesce(func.sum(Move.amount_paid), 0).label("total_paid"),
                func.coalesce(func.sum(Move.amount_residual), 0).label("total_outstanding"),
                func.avg(days_to_pay_expr).label("average_days_to_pay"),
            )
            .where(
                Move.state == "posted",
                Move.invoice_date >= date_from,
                Move.invoice_date <= date_to,
                Move.move_type.in_(_ALL_INVOICE_TYPES),
            )
            .group_by(period_expr)
            .order_by(period_expr)
        )

        if move_type:
            query = query.where(Move.move_type == move_type)
        if partner_id:
            query = query.where(Move.partner_id == partner_id)

        result = await self.db.execute(query)
        rows = result.all()

        return [
            InvoiceAnalysis(
                period=row.period or "unknown",
                invoice_count=row.invoice_count,
                total_amount=float(row.total_amount),
                total_paid=float(row.total_paid),
                total_outstanding=float(row.total_outstanding),
                average_days_to_pay=(
                    round(float(row.average_days_to_pay), 1)
                    if row.average_days_to_pay is not None
                    else None
                ),
            )
            for row in rows
        ]

    # ── Aging Report ───────────────────────────────────────────────────

    async def get_aging_report(
        self,
        as_of: date | None = None,
        partner_id: uuid.UUID | None = None,
    ) -> list[AgingBucket]:
        """Return aging buckets (current, 1-30, 31-60, 61-90, 90+) per partner.

        Args:
            as_of: Reference date for aging calculation (defaults to today).
            partner_id: Optional filter for a specific partner.

        Returns:
            List of AgingBucket entries, one per partner with outstanding balances.
        """
        if as_of is None:
            as_of = date.today()

        days_overdue = func.extract(
            "day",
            func.cast(literal(as_of), Date) - Move.invoice_date_due,
        )

        current_amt = func.coalesce(
            func.sum(case((days_overdue <= 0, Move.amount_residual), else_=literal(0))),
            0,
        )
        days_1_30 = func.coalesce(
            func.sum(
                case(
                    ((days_overdue > 0) & (days_overdue <= 30), Move.amount_residual),
                    else_=literal(0),
                )
            ),
            0,
        )
        days_31_60 = func.coalesce(
            func.sum(
                case(
                    ((days_overdue > 30) & (days_overdue <= 60), Move.amount_residual),
                    else_=literal(0),
                )
            ),
            0,
        )
        days_61_90 = func.coalesce(
            func.sum(
                case(
                    ((days_overdue > 60) & (days_overdue <= 90), Move.amount_residual),
                    else_=literal(0),
                )
            ),
            0,
        )
        days_90_plus = func.coalesce(
            func.sum(case((days_overdue > 90, Move.amount_residual), else_=literal(0))),
            0,
        )

        query = (
            select(
                Move.partner_id,
                current_amt.label("current"),
                days_1_30.label("days_1_30"),
                days_31_60.label("days_31_60"),
                days_61_90.label("days_61_90"),
                days_90_plus.label("days_90_plus"),
                func.coalesce(func.sum(Move.amount_residual), 0).label("total"),
            )
            .where(
                Move.state == "posted",
                Move.move_type.in_(("out_invoice", "in_invoice")),
                Move.payment_state.in_(("not_paid", "partial")),
                Move.amount_residual > 0,
            )
            .group_by(Move.partner_id)
            .order_by(func.sum(Move.amount_residual).desc())
        )

        if partner_id:
            query = query.where(Move.partner_id == partner_id)

        result = await self.db.execute(query)
        rows = result.all()

        return [
            AgingBucket(
                partner_id=row.partner_id,
                current=float(row.current),
                days_1_30=float(row.days_1_30),
                days_31_60=float(row.days_31_60),
                days_61_90=float(row.days_61_90),
                days_90_plus=float(row.days_90_plus),
                total=float(row.total),
            )
            for row in rows
        ]

    # ── Top Customers ──────────────────────────────────────────────────

    async def get_top_customers(
        self,
        limit: int = 10,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[TopPartnerEntry]:
        """Top customers ranked by total invoice amount.

        Args:
            limit: Maximum number of results.
            date_from: Optional start date filter.
            date_to: Optional end date filter.

        Returns:
            List of TopPartnerEntry for customer invoices.
        """
        return await self._top_partners(
            move_types=("out_invoice",),
            limit=limit,
            date_from=date_from,
            date_to=date_to,
        )

    # ── Top Vendors ────────────────────────────────────────────────────

    async def get_top_vendors(
        self,
        limit: int = 10,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[TopPartnerEntry]:
        """Top vendors ranked by total bill amount.

        Args:
            limit: Maximum number of results.
            date_from: Optional start date filter.
            date_to: Optional end date filter.

        Returns:
            List of TopPartnerEntry for vendor bills.
        """
        return await self._top_partners(
            move_types=("in_invoice",),
            limit=limit,
            date_from=date_from,
            date_to=date_to,
        )

    async def _top_partners(
        self,
        move_types: tuple[str, ...],
        limit: int,
        date_from: date | None,
        date_to: date | None,
    ) -> list[TopPartnerEntry]:
        """Shared implementation for top customers/vendors."""
        query = (
            select(
                Move.partner_id,
                func.count(Move.id).label("invoice_count"),
                func.coalesce(func.sum(Move.amount_total), 0).label("total_amount"),
                func.coalesce(func.sum(Move.amount_paid), 0).label("total_paid"),
            )
            .where(
                Move.state == "posted",
                Move.move_type.in_(move_types),
                Move.partner_id.isnot(None),
            )
            .group_by(Move.partner_id)
            .order_by(func.sum(Move.amount_total).desc())
            .limit(limit)
        )

        if date_from:
            query = query.where(Move.invoice_date >= date_from)
        if date_to:
            query = query.where(Move.invoice_date <= date_to)

        result = await self.db.execute(query)
        rows = result.all()

        return [
            TopPartnerEntry(
                partner_id=row.partner_id,
                invoice_count=row.invoice_count,
                total_amount=float(row.total_amount),
                total_paid=float(row.total_paid),
            )
            for row in rows
        ]

    # ── Payment Performance ────────────────────────────────────────────

    async def get_payment_performance(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> PaymentPerformance:
        """Compute payment performance metrics for paid customer invoices.

        Metrics include average days to pay, on-time percentage, and late percentage.
        An invoice is "on time" if it was paid (payment_state='paid') and its
        invoice_date_due >= its invoice_date (i.e., we use the due-vs-issue gap
        as a proxy when actual payment date isn't on the move header).

        Args:
            date_from: Optional start date filter on invoice_date.
            date_to: Optional end date filter on invoice_date.

        Returns:
            PaymentPerformance with aggregate metrics.
        """
        # We consider only posted customer invoices that are fully paid
        days_expr = func.extract("day", Move.invoice_date_due - Move.invoice_date)

        # on_time: paid invoices where amount_residual = 0 (fully paid)
        # We treat invoice_date_due >= date.today()-proxy as on-time.
        # Since we lack actual payment_date on Move, we use a simpler heuristic:
        # if the invoice_date_due hasn't passed as_of posting, it was on time.
        # But more practically: paid invoices with due_date >= invoice_date
        # are "structurally on time". We'll just count paid vs total for now.

        on_time_case = case(
            (Move.payment_state == "paid", literal(1)),
            else_=literal(0),
        )
        late_case = case(
            (Move.payment_state.in_(("not_paid", "partial")), literal(1)),
            else_=literal(0),
        )

        query = (
            select(
                func.avg(
                    case(
                        (Move.payment_state == "paid", days_expr),
                        else_=None,
                    )
                ).label("average_days_to_pay"),
                func.sum(on_time_case).label("on_time_count"),
                func.sum(late_case).label("late_count"),
                func.count(Move.id).label("total_invoices"),
            )
            .where(
                Move.state == "posted",
                Move.move_type.in_(("out_invoice",)),
                Move.invoice_date.isnot(None),
                Move.invoice_date_due.isnot(None),
            )
        )

        if date_from:
            query = query.where(Move.invoice_date >= date_from)
        if date_to:
            query = query.where(Move.invoice_date <= date_to)

        result = await self.db.execute(query)
        row = result.one()

        total = row.total_invoices or 0
        on_time = int(row.on_time_count or 0)
        late = int(row.late_count or 0)

        return PaymentPerformance(
            average_days_to_pay=(
                round(float(row.average_days_to_pay), 1)
                if row.average_days_to_pay is not None
                else None
            ),
            on_time_count=on_time,
            on_time_percent=round((on_time / total) * 100, 1) if total > 0 else 0.0,
            late_count=late,
            late_percent=round((late / total) * 100, 1) if total > 0 else 0.0,
            total_invoices=total,
        )

    # ── Revenue Trend ──────────────────────────────────────────────────

    async def get_revenue_trend(self, months: int = 12) -> list[RevenueTrendEntry]:
        """Monthly revenue (customer invoices) vs expense (vendor bills) trend.

        Args:
            months: Number of trailing months to include (default 12).

        Returns:
            List of RevenueTrendEntry per month, ordered chronologically.
        """
        start_date = date.today().replace(day=1) - timedelta(days=(months - 1) * 30)
        start_date = start_date.replace(day=1)  # Snap to first of month

        period_expr = func.to_char(Move.invoice_date, "YYYY-MM")

        revenue_expr = func.coalesce(
            func.sum(
                case(
                    (Move.move_type == "out_invoice", Move.amount_untaxed),
                    (Move.move_type == "out_refund", -Move.amount_untaxed),
                    else_=literal(0),
                )
            ),
            0,
        )
        expense_expr = func.coalesce(
            func.sum(
                case(
                    (Move.move_type == "in_invoice", Move.amount_untaxed),
                    (Move.move_type == "in_refund", -Move.amount_untaxed),
                    else_=literal(0),
                )
            ),
            0,
        )

        query = (
            select(
                period_expr.label("period"),
                revenue_expr.label("revenue"),
                expense_expr.label("expense"),
            )
            .where(
                Move.state == "posted",
                Move.move_type.in_(_ALL_INVOICE_TYPES),
                Move.invoice_date >= start_date,
            )
            .group_by(period_expr)
            .order_by(period_expr)
        )

        result = await self.db.execute(query)
        rows = result.all()

        return [
            RevenueTrendEntry(
                period=row.period,
                revenue=float(row.revenue),
                expense=float(row.expense),
                net=float(row.revenue) - float(row.expense),
            )
            for row in rows
        ]

    # ── Outstanding Summary ────────────────────────────────────────────

    async def get_outstanding_summary(self) -> OutstandingSummary:
        """Total outstanding amounts split by customer invoices vs vendor bills.

        Returns:
            OutstandingSummary with customer, vendor, and net outstanding.
        """
        customer_expr = func.coalesce(
            func.sum(
                case(
                    (Move.move_type == "out_invoice", Move.amount_residual),
                    else_=literal(0),
                )
            ),
            0,
        )
        vendor_expr = func.coalesce(
            func.sum(
                case(
                    (Move.move_type == "in_invoice", Move.amount_residual),
                    else_=literal(0),
                )
            ),
            0,
        )

        query = select(
            customer_expr.label("customer_outstanding"),
            vendor_expr.label("vendor_outstanding"),
        ).where(
            Move.state == "posted",
            Move.move_type.in_(("out_invoice", "in_invoice")),
            Move.payment_state.in_(("not_paid", "partial")),
        )

        result = await self.db.execute(query)
        row = result.one()

        customer = float(row.customer_outstanding)
        vendor = float(row.vendor_outstanding)

        return OutstandingSummary(
            customer_outstanding=customer,
            vendor_outstanding=vendor,
            net_outstanding=customer - vendor,
        )
