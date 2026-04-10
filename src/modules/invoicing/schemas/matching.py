"""Pydantic schemas for the 3-way matching system.

Covers purchase orders, receipts, bill matches, and matching results.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel


# ── Purchase Order Lines ─────────────────────────────────────────────

class PurchaseOrderLineCreate(BaseModel):
    product_id: uuid.UUID | None = None
    description: str
    quantity_ordered: float
    price_unit: float
    discount: float = 0.0
    tax_ids: list[uuid.UUID] | None = None
    sequence: int = 10


class PurchaseOrderLineRead(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    product_id: uuid.UUID | None
    description: str
    quantity_ordered: float
    quantity_received: float
    quantity_billed: float
    price_unit: float
    discount: float
    tax_ids: list[uuid.UUID] | None
    sequence: int
    line_total: float
    model_config = {"from_attributes": True}


# ── Purchase Orders ──────────────────────────────────────────────────

class PurchaseOrderCreate(BaseModel):
    po_number: str
    partner_id: uuid.UUID
    order_date: date
    expected_date: date | None = None
    total_amount: float
    currency_code: str = "USD"
    notes: str | None = None
    lines: list[PurchaseOrderLineCreate] = []


class PurchaseOrderRead(BaseModel):
    id: uuid.UUID
    po_number: str
    partner_id: uuid.UUID
    order_date: date
    expected_date: date | None
    total_amount: float
    currency_code: str
    state: str
    notes: str | None
    lines: list[PurchaseOrderLineRead] = []
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class PurchaseOrderUpdate(BaseModel):
    expected_date: date | None = None
    state: str | None = None
    notes: str | None = None


# ── Receipt Lines ────────────────────────────────────────────────────

class ReceiptLineCreate(BaseModel):
    po_line_id: uuid.UUID | None = None
    product_id: uuid.UUID | None = None
    description: str
    quantity_received: float
    sequence: int = 10


class ReceiptLineRead(BaseModel):
    id: uuid.UUID
    receipt_id: uuid.UUID
    po_line_id: uuid.UUID | None
    product_id: uuid.UUID | None
    description: str
    quantity_received: float
    sequence: int
    model_config = {"from_attributes": True}


# ── Receipts ─────────────────────────────────────────────────────────

class ReceiptCreate(BaseModel):
    receipt_number: str
    po_id: uuid.UUID | None = None
    partner_id: uuid.UUID
    receipt_date: date
    notes: str | None = None
    lines: list[ReceiptLineCreate] = []


class ReceiptRead(BaseModel):
    id: uuid.UUID
    receipt_number: str
    po_id: uuid.UUID | None
    partner_id: uuid.UUID
    receipt_date: date
    state: str
    notes: str | None
    lines: list[ReceiptLineRead] = []
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ── Bill Match ───────────────────────────────────────────────────────

class BillMatchRead(BaseModel):
    id: uuid.UUID
    bill_id: uuid.UUID
    po_id: uuid.UUID | None
    receipt_id: uuid.UUID | None
    match_type: str
    match_status: str
    po_amount: float | None
    receipt_amount: float | None
    bill_amount: float
    variance_amount: float
    variance_percent: float
    matched_by: uuid.UUID | None
    matched_at: datetime | None
    exception_reason: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ── Matching Results ─────────────────────────────────────────────────

class MatchResult(BaseModel):
    bill_id: uuid.UUID
    po_id: uuid.UUID | None
    receipt_id: uuid.UUID | None
    match_status: str
    match_type: str
    variance_amount: float
    variance_percent: float
    details: list[str] = []


class MatchingSummary(BaseModel):
    total_bills: int
    matched: int
    exceptions: int
    pending: int
    overridden: int
