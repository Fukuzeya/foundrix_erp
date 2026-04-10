"""E-Invoice generation service.

Generates standards-compliant electronic invoices in UBL 2.1, Peppol BIS 3.0,
Factur-X (CII), and XRechnung formats from journal entries (moves).
"""

from __future__ import annotations

import logging
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError, ValidationError
from src.core.events import event_bus
from src.modules.accounting.models.move import Move, MoveLine, INVOICE_TYPES
from src.modules.accounting.repositories.move_repo import MoveRepository
from src.modules.invoicing.models.einvoice import EInvoiceConfig, EInvoiceLog
from src.modules.invoicing.schemas.einvoice import (
    EInvoiceConfigCreate,
    EInvoiceConfigRead,
    EInvoiceConfigUpdate,
    EInvoiceLogRead,
    EInvoiceStatus,
)

logger = logging.getLogger(__name__)

# ── XML Namespaces ────────────────────────────────────────────────────

UBL_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CAC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CBC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

CII_NS = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
CII_RAM_NS = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
CII_QDT_NS = "urn:un:unece:uncefact:data:standard:QualifiedDataType:100"
CII_UDT_NS = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"

PEPPOL_CUSTOMIZATION_ID = (
    "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
)
PEPPOL_PROFILE_ID = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
UBL_CUSTOMIZATION_ID = "urn:cen.eu:en16931:2017"
XRECHNUNG_CUSTOMIZATION_ID = (
    "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_2.3"
)

# Invoice type codes (UN/CEFACT 1001)
TYPE_CODE_INVOICE = "380"
TYPE_CODE_CREDIT_NOTE = "381"


class EInvoiceService:
    """Generates and manages electronic invoices in various EU formats."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.move_repo = MoveRepository(db)

    # ── UBL 2.1 Generation ────────────────────────────────────────────

    async def generate_ubl_invoice(self, move_id: uuid.UUID) -> str:
        """Generate a UBL 2.1 compliant XML invoice.

        Returns the full XML string with proper namespaces for
        Invoice-2, CommonAggregateComponents-2, and CommonBasicComponents-2.
        """
        move = await self._get_invoice_or_raise(move_id)

        ET.register_namespace("", UBL_NS)
        ET.register_namespace("cac", CAC_NS)
        ET.register_namespace("cbc", CBC_NS)

        root = ET.Element(f"{{{UBL_NS}}}Invoice")
        ns = {"ubl": UBL_NS, "cac": CAC_NS, "cbc": CBC_NS}

        # ── Header ────────────────────────────────────────────────
        ET.SubElement(root, f"{{{CBC_NS}}}CustomizationID").text = UBL_CUSTOMIZATION_ID
        ET.SubElement(root, f"{{{CBC_NS}}}ProfileID").text = (
            "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
        )
        ET.SubElement(root, f"{{{CBC_NS}}}ID").text = move.name
        ET.SubElement(root, f"{{{CBC_NS}}}IssueDate").text = (
            move.invoice_date.isoformat() if move.invoice_date else move.date.isoformat()
        )
        if move.invoice_date_due:
            ET.SubElement(root, f"{{{CBC_NS}}}DueDate").text = (
                move.invoice_date_due.isoformat()
            )

        type_code = TYPE_CODE_CREDIT_NOTE if move.move_type in ("out_refund", "in_refund") else TYPE_CODE_INVOICE
        ET.SubElement(root, f"{{{CBC_NS}}}InvoiceTypeCode").text = type_code
        ET.SubElement(root, f"{{{CBC_NS}}}DocumentCurrencyCode").text = move.currency_code

        if move.ref:
            ET.SubElement(root, f"{{{CBC_NS}}}BuyerReference").text = move.ref

        # ── Parties ───────────────────────────────────────────────
        supplier_party = ET.SubElement(root, f"{{{CAC_NS}}}AccountingSupplierParty")
        self._build_party_xml(supplier_party, {"name": "Supplier", "country": "US"}, ns)

        customer_party = ET.SubElement(root, f"{{{CAC_NS}}}AccountingCustomerParty")
        self._build_party_xml(customer_party, {"name": "Customer", "country": "US"}, ns)

        # ── Tax Total ─────────────────────────────────────────────
        self._build_tax_xml(root, {"amount": move.amount_tax, "currency": move.currency_code}, ns)

        # ── Legal Monetary Total ──────────────────────────────────
        monetary = ET.SubElement(root, f"{{{CAC_NS}}}LegalMonetaryTotal")
        line_ext = ET.SubElement(monetary, f"{{{CBC_NS}}}LineExtensionAmount")
        line_ext.text = f"{move.amount_untaxed:.2f}"
        line_ext.set("currencyID", move.currency_code)

        tax_excl = ET.SubElement(monetary, f"{{{CBC_NS}}}TaxExclusiveAmount")
        tax_excl.text = f"{move.amount_untaxed:.2f}"
        tax_excl.set("currencyID", move.currency_code)

        tax_incl = ET.SubElement(monetary, f"{{{CBC_NS}}}TaxInclusiveAmount")
        tax_incl.text = f"{move.amount_total:.2f}"
        tax_incl.set("currencyID", move.currency_code)

        payable = ET.SubElement(monetary, f"{{{CBC_NS}}}PayableAmount")
        payable.text = f"{move.amount_residual:.2f}"
        payable.set("currencyID", move.currency_code)

        # ── Invoice Lines ─────────────────────────────────────────
        product_lines = [
            line for line in move.lines if line.display_type == "product"
        ]
        for idx, line in enumerate(product_lines, start=1):
            self._build_line_xml(root, line, ns, line_id=str(idx))

        return self._tree_to_string(root)

    # ── Peppol BIS 3.0 ───────────────────────────────────────────────

    async def generate_peppol_invoice(self, move_id: uuid.UUID) -> str:
        """Generate a Peppol BIS 3.0 invoice (UBL with Peppol customization).

        Extends UBL 2.1 with the Peppol BIS 3.0 CustomizationID and
        EndpointID elements for network routing.
        """
        move = await self._get_invoice_or_raise(move_id)

        ET.register_namespace("", UBL_NS)
        ET.register_namespace("cac", CAC_NS)
        ET.register_namespace("cbc", CBC_NS)

        root = ET.Element(f"{{{UBL_NS}}}Invoice")
        ns = {"ubl": UBL_NS, "cac": CAC_NS, "cbc": CBC_NS}

        # ── Peppol-specific header ────────────────────────────────
        ET.SubElement(root, f"{{{CBC_NS}}}CustomizationID").text = PEPPOL_CUSTOMIZATION_ID
        ET.SubElement(root, f"{{{CBC_NS}}}ProfileID").text = PEPPOL_PROFILE_ID
        ET.SubElement(root, f"{{{CBC_NS}}}ID").text = move.name
        ET.SubElement(root, f"{{{CBC_NS}}}IssueDate").text = (
            move.invoice_date.isoformat() if move.invoice_date else move.date.isoformat()
        )
        if move.invoice_date_due:
            ET.SubElement(root, f"{{{CBC_NS}}}DueDate").text = (
                move.invoice_date_due.isoformat()
            )

        type_code = TYPE_CODE_CREDIT_NOTE if move.move_type in ("out_refund", "in_refund") else TYPE_CODE_INVOICE
        ET.SubElement(root, f"{{{CBC_NS}}}InvoiceTypeCode").text = type_code
        ET.SubElement(root, f"{{{CBC_NS}}}DocumentCurrencyCode").text = move.currency_code

        if move.ref:
            ET.SubElement(root, f"{{{CBC_NS}}}BuyerReference").text = move.ref

        # ── Parties with EndpointID ───────────────────────────────
        supplier_party = ET.SubElement(root, f"{{{CAC_NS}}}AccountingSupplierParty")
        self._build_party_xml(
            supplier_party,
            {"name": "Supplier", "country": "US", "endpoint_id": "sender@peppol", "eas_code": "0088"},
            ns,
        )

        customer_party = ET.SubElement(root, f"{{{CAC_NS}}}AccountingCustomerParty")
        self._build_party_xml(
            customer_party,
            {"name": "Customer", "country": "US", "endpoint_id": "receiver@peppol", "eas_code": "0088"},
            ns,
        )

        # ── Tax Total ─────────────────────────────────────────────
        self._build_tax_xml(root, {"amount": move.amount_tax, "currency": move.currency_code}, ns)

        # ── Legal Monetary Total ──────────────────────────────────
        monetary = ET.SubElement(root, f"{{{CAC_NS}}}LegalMonetaryTotal")
        line_ext = ET.SubElement(monetary, f"{{{CBC_NS}}}LineExtensionAmount")
        line_ext.text = f"{move.amount_untaxed:.2f}"
        line_ext.set("currencyID", move.currency_code)

        tax_excl = ET.SubElement(monetary, f"{{{CBC_NS}}}TaxExclusiveAmount")
        tax_excl.text = f"{move.amount_untaxed:.2f}"
        tax_excl.set("currencyID", move.currency_code)

        tax_incl = ET.SubElement(monetary, f"{{{CBC_NS}}}TaxInclusiveAmount")
        tax_incl.text = f"{move.amount_total:.2f}"
        tax_incl.set("currencyID", move.currency_code)

        payable = ET.SubElement(monetary, f"{{{CBC_NS}}}PayableAmount")
        payable.text = f"{move.amount_residual:.2f}"
        payable.set("currencyID", move.currency_code)

        # ── Invoice Lines ─────────────────────────────────────────
        product_lines = [
            line for line in move.lines if line.display_type == "product"
        ]
        for idx, line in enumerate(product_lines, start=1):
            self._build_line_xml(root, line, ns, line_id=str(idx))

        return self._tree_to_string(root)

    # ── Factur-X / ZUGFeRD (CII) ─────────────────────────────────────

    async def generate_facturx(self, move_id: uuid.UUID) -> str:
        """Generate a Factur-X / ZUGFeRD CrossIndustryInvoice (CII) XML.

        Used primarily in France (Factur-X) and Germany (ZUGFeRD).
        """
        move = await self._get_invoice_or_raise(move_id)

        ET.register_namespace("rsm", CII_NS)
        ET.register_namespace("ram", CII_RAM_NS)
        ET.register_namespace("qdt", CII_QDT_NS)
        ET.register_namespace("udt", CII_UDT_NS)

        root = ET.Element(f"{{{CII_NS}}}CrossIndustryInvoice")

        # ── Exchange Document Context ─────────────────────────────
        context = ET.SubElement(root, f"{{{CII_NS}}}ExchangedDocumentContext")
        guideline = ET.SubElement(context, f"{{{CII_RAM_NS}}}GuidelineSpecifiedDocumentContextParameter")
        ET.SubElement(guideline, f"{{{CII_RAM_NS}}}ID").text = (
            "urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended"
        )

        # ── Exchanged Document ────────────────────────────────────
        doc = ET.SubElement(root, f"{{{CII_NS}}}ExchangedDocument")
        ET.SubElement(doc, f"{{{CII_RAM_NS}}}ID").text = move.name

        type_code = "381" if move.move_type in ("out_refund", "in_refund") else "380"
        ET.SubElement(doc, f"{{{CII_RAM_NS}}}TypeCode").text = type_code

        issue_dt = ET.SubElement(doc, f"{{{CII_RAM_NS}}}IssueDateTime")
        dt_string = ET.SubElement(issue_dt, f"{{{CII_UDT_NS}}}DateTimeString")
        issue_date = move.invoice_date if move.invoice_date else move.date
        dt_string.text = issue_date.strftime("%Y%m%d")
        dt_string.set("format", "102")

        # ── Supply Chain Trade Transaction ────────────────────────
        transaction = ET.SubElement(root, f"{{{CII_NS}}}SupplyChainTradeTransaction")

        # Trade Agreement
        agreement = ET.SubElement(transaction, f"{{{CII_RAM_NS}}}ApplicableHeaderTradeAgreement")
        seller = ET.SubElement(agreement, f"{{{CII_RAM_NS}}}SellerTradeParty")
        ET.SubElement(seller, f"{{{CII_RAM_NS}}}Name").text = "Supplier"
        buyer = ET.SubElement(agreement, f"{{{CII_RAM_NS}}}BuyerTradeParty")
        ET.SubElement(buyer, f"{{{CII_RAM_NS}}}Name").text = "Customer"

        # Trade Delivery
        ET.SubElement(transaction, f"{{{CII_RAM_NS}}}ApplicableHeaderTradeDelivery")

        # Trade Settlement
        settlement = ET.SubElement(transaction, f"{{{CII_RAM_NS}}}ApplicableHeaderTradeSettlement")
        ET.SubElement(settlement, f"{{{CII_RAM_NS}}}InvoiceCurrencyCode").text = move.currency_code

        # Tax
        tax_elem = ET.SubElement(settlement, f"{{{CII_RAM_NS}}}ApplicableTradeTax")
        tax_amt = ET.SubElement(tax_elem, f"{{{CII_RAM_NS}}}CalculatedAmount")
        tax_amt.text = f"{move.amount_tax:.2f}"
        ET.SubElement(tax_elem, f"{{{CII_RAM_NS}}}TypeCode").text = "VAT"
        basis_amt = ET.SubElement(tax_elem, f"{{{CII_RAM_NS}}}BasisAmount")
        basis_amt.text = f"{move.amount_untaxed:.2f}"

        # Monetary Summation
        summation = ET.SubElement(settlement, f"{{{CII_RAM_NS}}}SpecifiedTradeSettlementHeaderMonetarySummation")
        line_total = ET.SubElement(summation, f"{{{CII_RAM_NS}}}LineTotalAmount")
        line_total.text = f"{move.amount_untaxed:.2f}"
        tax_basis = ET.SubElement(summation, f"{{{CII_RAM_NS}}}TaxBasisTotalAmount")
        tax_basis.text = f"{move.amount_untaxed:.2f}"
        tax_total = ET.SubElement(summation, f"{{{CII_RAM_NS}}}TaxTotalAmount")
        tax_total.text = f"{move.amount_tax:.2f}"
        tax_total.set("currencyID", move.currency_code)
        grand_total = ET.SubElement(summation, f"{{{CII_RAM_NS}}}GrandTotalAmount")
        grand_total.text = f"{move.amount_total:.2f}"
        due_payable = ET.SubElement(summation, f"{{{CII_RAM_NS}}}DuePayableAmount")
        due_payable.text = f"{move.amount_residual:.2f}"

        # ── Line Items ────────────────────────────────────────────
        product_lines = [
            line for line in move.lines if line.display_type == "product"
        ]
        for idx, line in enumerate(product_lines, start=1):
            line_item = ET.SubElement(transaction, f"{{{CII_RAM_NS}}}IncludedSupplyChainTradeLineItem")

            line_doc = ET.SubElement(line_item, f"{{{CII_RAM_NS}}}AssociatedDocumentLineDocument")
            ET.SubElement(line_doc, f"{{{CII_RAM_NS}}}LineID").text = str(idx)

            trade_product = ET.SubElement(line_item, f"{{{CII_RAM_NS}}}SpecifiedTradeProduct")
            ET.SubElement(trade_product, f"{{{CII_RAM_NS}}}Name").text = line.name or f"Line {idx}"

            line_agreement = ET.SubElement(line_item, f"{{{CII_RAM_NS}}}SpecifiedLineTradeAgreement")
            price = ET.SubElement(line_agreement, f"{{{CII_RAM_NS}}}NetPriceProductTradePrice")
            charge_amt = ET.SubElement(price, f"{{{CII_RAM_NS}}}ChargeAmount")
            charge_amt.text = f"{line.price_unit:.2f}"

            line_delivery = ET.SubElement(line_item, f"{{{CII_RAM_NS}}}SpecifiedLineTradeDelivery")
            billed_qty = ET.SubElement(line_delivery, f"{{{CII_RAM_NS}}}BilledQuantity")
            billed_qty.text = f"{line.quantity:.2f}"
            billed_qty.set("unitCode", "EA")

            line_settlement = ET.SubElement(line_item, f"{{{CII_RAM_NS}}}SpecifiedLineTradeSettlement")
            line_summation = ET.SubElement(line_settlement, f"{{{CII_RAM_NS}}}SpecifiedTradeSettlementLineMonetarySummation")
            line_amt = ET.SubElement(line_summation, f"{{{CII_RAM_NS}}}LineTotalAmount")
            line_amt.text = f"{line.price_subtotal:.2f}"

        return self._tree_to_string(root)

    # ── XRechnung ─────────────────────────────────────────────────────

    async def generate_xrechnung(self, move_id: uuid.UUID) -> str:
        """Generate a German XRechnung invoice based on UBL 2.1.

        XRechnung is mandatory for B2G invoicing in Germany and uses
        a specific customization ID on top of EN 16931.
        """
        move = await self._get_invoice_or_raise(move_id)

        ET.register_namespace("", UBL_NS)
        ET.register_namespace("cac", CAC_NS)
        ET.register_namespace("cbc", CBC_NS)

        root = ET.Element(f"{{{UBL_NS}}}Invoice")
        ns = {"ubl": UBL_NS, "cac": CAC_NS, "cbc": CBC_NS}

        # ── XRechnung-specific header ─────────────────────────────
        ET.SubElement(root, f"{{{CBC_NS}}}CustomizationID").text = XRECHNUNG_CUSTOMIZATION_ID
        ET.SubElement(root, f"{{{CBC_NS}}}ProfileID").text = PEPPOL_PROFILE_ID
        ET.SubElement(root, f"{{{CBC_NS}}}ID").text = move.name
        ET.SubElement(root, f"{{{CBC_NS}}}IssueDate").text = (
            move.invoice_date.isoformat() if move.invoice_date else move.date.isoformat()
        )
        if move.invoice_date_due:
            ET.SubElement(root, f"{{{CBC_NS}}}DueDate").text = (
                move.invoice_date_due.isoformat()
            )

        type_code = TYPE_CODE_CREDIT_NOTE if move.move_type in ("out_refund", "in_refund") else TYPE_CODE_INVOICE
        ET.SubElement(root, f"{{{CBC_NS}}}InvoiceTypeCode").text = type_code
        ET.SubElement(root, f"{{{CBC_NS}}}DocumentCurrencyCode").text = move.currency_code

        # BuyerReference is mandatory for XRechnung
        ET.SubElement(root, f"{{{CBC_NS}}}BuyerReference").text = move.ref or move.name

        # ── Parties ───────────────────────────────────────────────
        supplier_party = ET.SubElement(root, f"{{{CAC_NS}}}AccountingSupplierParty")
        self._build_party_xml(supplier_party, {"name": "Supplier", "country": "DE"}, ns)

        customer_party = ET.SubElement(root, f"{{{CAC_NS}}}AccountingCustomerParty")
        self._build_party_xml(customer_party, {"name": "Customer", "country": "DE"}, ns)

        # ── Tax Total ─────────────────────────────────────────────
        self._build_tax_xml(root, {"amount": move.amount_tax, "currency": move.currency_code}, ns)

        # ── Legal Monetary Total ──────────────────────────────────
        monetary = ET.SubElement(root, f"{{{CAC_NS}}}LegalMonetaryTotal")
        line_ext = ET.SubElement(monetary, f"{{{CBC_NS}}}LineExtensionAmount")
        line_ext.text = f"{move.amount_untaxed:.2f}"
        line_ext.set("currencyID", move.currency_code)

        tax_excl = ET.SubElement(monetary, f"{{{CBC_NS}}}TaxExclusiveAmount")
        tax_excl.text = f"{move.amount_untaxed:.2f}"
        tax_excl.set("currencyID", move.currency_code)

        tax_incl = ET.SubElement(monetary, f"{{{CBC_NS}}}TaxInclusiveAmount")
        tax_incl.text = f"{move.amount_total:.2f}"
        tax_incl.set("currencyID", move.currency_code)

        payable = ET.SubElement(monetary, f"{{{CBC_NS}}}PayableAmount")
        payable.text = f"{move.amount_residual:.2f}"
        payable.set("currencyID", move.currency_code)

        # ── Invoice Lines ─────────────────────────────────────────
        product_lines = [
            line for line in move.lines if line.display_type == "product"
        ]
        for idx, line in enumerate(product_lines, start=1):
            self._build_line_xml(root, line, ns, line_id=str(idx))

        return self._tree_to_string(root)

    # ── Validation ────────────────────────────────────────────────────

    async def validate_einvoice(self, xml_content: str, format_type: str) -> list[str]:
        """Validate an e-invoice XML document for required fields.

        Returns a list of validation error messages (empty = valid).
        """
        errors: list[str] = []

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as exc:
            return [f"XML parse error: {exc}"]

        if format_type in ("ubl", "peppol", "xrechnung"):
            errors.extend(self._validate_ubl(root, format_type))
        elif format_type == "facturx":
            errors.extend(self._validate_cii(root))
        else:
            errors.append(f"Unknown format type: {format_type}")

        return errors

    def _validate_ubl(self, root: ET.Element, format_type: str) -> list[str]:
        """Validate UBL-based invoice XML for required elements."""
        errors: list[str] = []

        required_cbc = [
            "CustomizationID", "ID", "IssueDate",
            "InvoiceTypeCode", "DocumentCurrencyCode",
        ]
        for tag_name in required_cbc:
            elem = root.find(f".//{{{CBC_NS}}}{tag_name}")
            if elem is None or not elem.text:
                errors.append(f"Missing required element: cbc:{tag_name}")

        # Check parties
        supplier = root.find(f".//{{{CAC_NS}}}AccountingSupplierParty")
        if supplier is None:
            errors.append("Missing required element: cac:AccountingSupplierParty")

        customer = root.find(f".//{{{CAC_NS}}}AccountingCustomerParty")
        if customer is None:
            errors.append("Missing required element: cac:AccountingCustomerParty")

        # Check monetary total
        monetary = root.find(f".//{{{CAC_NS}}}LegalMonetaryTotal")
        if monetary is None:
            errors.append("Missing required element: cac:LegalMonetaryTotal")

        # Peppol/XRechnung require BuyerReference
        if format_type in ("peppol", "xrechnung"):
            buyer_ref = root.find(f".//{{{CBC_NS}}}BuyerReference")
            if buyer_ref is None or not buyer_ref.text:
                errors.append(f"Missing required element for {format_type}: cbc:BuyerReference")

        # XRechnung requires EndpointID or Leitweg-ID via BuyerReference
        if format_type == "xrechnung":
            customization = root.find(f".//{{{CBC_NS}}}CustomizationID")
            if customization is not None and "xrechnung" not in (customization.text or "").lower():
                errors.append("XRechnung CustomizationID must reference the XRechnung standard")

        return errors

    def _validate_cii(self, root: ET.Element) -> list[str]:
        """Validate CII (Factur-X) invoice XML for required elements."""
        errors: list[str] = []

        doc = root.find(f".//{{{CII_NS}}}ExchangedDocument")
        if doc is None:
            errors.append("Missing required element: ExchangedDocument")
        else:
            doc_id = doc.find(f".//{{{CII_RAM_NS}}}ID")
            if doc_id is None or not doc_id.text:
                errors.append("Missing required element: ExchangedDocument/ID")
            type_code = doc.find(f".//{{{CII_RAM_NS}}}TypeCode")
            if type_code is None or not type_code.text:
                errors.append("Missing required element: ExchangedDocument/TypeCode")

        transaction = root.find(f".//{{{CII_NS}}}SupplyChainTradeTransaction")
        if transaction is None:
            errors.append("Missing required element: SupplyChainTradeTransaction")
        else:
            agreement = transaction.find(f".//{{{CII_RAM_NS}}}ApplicableHeaderTradeAgreement")
            if agreement is None:
                errors.append("Missing required element: ApplicableHeaderTradeAgreement")
            settlement = transaction.find(f".//{{{CII_RAM_NS}}}ApplicableHeaderTradeSettlement")
            if settlement is None:
                errors.append("Missing required element: ApplicableHeaderTradeSettlement")

        return errors

    # ── Transmission ──────────────────────────────────────────────────

    async def send_to_peppol(
        self,
        move_id: uuid.UUID,
        config_id: uuid.UUID | None = None,
    ) -> EInvoiceStatus:
        """Generate a Peppol invoice, log it, and mark as sent.

        This is a stub for actual Peppol network transmission. In production,
        the XML would be submitted to an Access Point.
        """
        move = await self._get_invoice_or_raise(move_id)

        # Resolve config
        config: EInvoiceConfig | None = None
        if config_id:
            result = await self.db.execute(
                select(EInvoiceConfig).where(EInvoiceConfig.id == config_id)
            )
            config = result.scalar_one_or_none()
            if config is None:
                raise NotFoundError("EInvoiceConfig", str(config_id))
        else:
            result = await self.db.execute(
                select(EInvoiceConfig).where(
                    EInvoiceConfig.format_type == "peppol",
                    EInvoiceConfig.is_active.is_(True),
                    EInvoiceConfig.is_default.is_(True),
                )
            )
            config = result.scalar_one_or_none()

        # Generate XML
        xml_content = await self.generate_peppol_invoice(move_id)
        now = datetime.utcnow()
        file_name = f"{move.name.replace('/', '_')}_peppol.xml"

        # Create log entry
        log = EInvoiceLog(
            move_id=move_id,
            format_type="peppol",
            direction="outbound",
            status="sent",
            xml_content=xml_content,
            file_name=file_name,
            sent_at=now,
        )
        self.db.add(log)
        await self.db.flush()
        await self.db.refresh(log)

        await event_bus.publish("einvoice.sent", {
            "move_id": str(move_id),
            "format_type": "peppol",
            "log_id": str(log.id),
        })

        logger.info("Peppol invoice sent for move %s (log %s)", move_id, log.id)

        return EInvoiceStatus(
            move_id=move_id,
            format_type="peppol",
            status="sent",
            sent_at=now,
            delivered_at=None,
        )

    # ── Status & Logs ─────────────────────────────────────────────────

    async def get_invoice_einvoice_status(
        self, move_id: uuid.UUID
    ) -> list[EInvoiceLogRead]:
        """Get all e-invoice log entries for a given move."""
        result = await self.db.execute(
            select(EInvoiceLog)
            .where(EInvoiceLog.move_id == move_id)
            .order_by(EInvoiceLog.created_at.desc())
        )
        logs = result.scalars().all()
        return [EInvoiceLogRead.model_validate(log) for log in logs]

    # ── Config CRUD ───────────────────────────────────────────────────

    async def list_configs(self) -> list[EInvoiceConfigRead]:
        """List all e-invoice configurations."""
        result = await self.db.execute(
            select(EInvoiceConfig).order_by(EInvoiceConfig.name)
        )
        configs = result.scalars().all()
        return [EInvoiceConfigRead.model_validate(c) for c in configs]

    async def create_config(self, data: EInvoiceConfigCreate) -> EInvoiceConfigRead:
        """Create a new e-invoice configuration."""
        valid_formats = {"ubl", "peppol", "facturx", "xrechnung"}
        if data.format_type not in valid_formats:
            raise ValidationError(
                f"Invalid format_type '{data.format_type}'. Must be one of: {', '.join(sorted(valid_formats))}"
            )

        config = EInvoiceConfig(
            name=data.name,
            format_type=data.format_type,
            country_code=data.country_code,
            eas_code=data.eas_code,
            endpoint_id=data.endpoint_id,
            is_default=data.is_default,
            settings=data.settings,
        )
        self.db.add(config)
        await self.db.flush()
        await self.db.refresh(config)

        logger.info("Created e-invoice config %s (%s)", config.id, config.name)
        return EInvoiceConfigRead.model_validate(config)

    async def update_config(
        self, config_id: uuid.UUID, data: EInvoiceConfigUpdate
    ) -> EInvoiceConfigRead:
        """Update an existing e-invoice configuration."""
        result = await self.db.execute(
            select(EInvoiceConfig).where(EInvoiceConfig.id == config_id)
        )
        config = result.scalar_one_or_none()
        if config is None:
            raise NotFoundError("EInvoiceConfig", str(config_id))

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(config, key, value)

        await self.db.flush()
        await self.db.refresh(config)

        logger.info("Updated e-invoice config %s", config_id)
        return EInvoiceConfigRead.model_validate(config)

    # ── Private Helpers ───────────────────────────────────────────────

    async def _get_invoice_or_raise(self, move_id: uuid.UUID) -> Move:
        """Fetch a move and validate it is a posted invoice."""
        move = await self.move_repo.get_by_id_or_raise(move_id, "Move")

        if move.move_type not in INVOICE_TYPES:
            raise BusinessRuleError(
                f"Move {move.name} is type '{move.move_type}', not an invoice. "
                "E-invoices can only be generated for invoice-type moves."
            )
        if move.state != "posted":
            raise BusinessRuleError(
                f"Move {move.name} is in state '{move.state}'. "
                "E-invoices can only be generated for posted invoices."
            )
        return move

    def _build_party_xml(
        self,
        parent_elem: ET.Element,
        party_data: dict,
        ns: dict[str, str],
    ) -> None:
        """Build a UBL AccountingSupplierParty or AccountingCustomerParty element."""
        cac = ns["cac"]
        cbc = ns["cbc"]

        party = ET.SubElement(parent_elem, f"{{{cac}}}Party")

        # EndpointID (for Peppol)
        if party_data.get("endpoint_id"):
            endpoint = ET.SubElement(party, f"{{{cbc}}}EndpointID")
            endpoint.text = party_data["endpoint_id"]
            endpoint.set("schemeID", party_data.get("eas_code", "0088"))

        # Party name
        party_name_elem = ET.SubElement(party, f"{{{cac}}}PartyName")
        ET.SubElement(party_name_elem, f"{{{cbc}}}Name").text = party_data.get("name", "")

        # Postal address
        address = ET.SubElement(party, f"{{{cac}}}PostalAddress")
        country_elem = ET.SubElement(address, f"{{{cac}}}Country")
        ET.SubElement(country_elem, f"{{{cbc}}}IdentificationCode").text = (
            party_data.get("country", "")
        )

        # Legal entity
        legal = ET.SubElement(party, f"{{{cac}}}PartyLegalEntity")
        ET.SubElement(legal, f"{{{cbc}}}RegistrationName").text = party_data.get("name", "")

    def _build_line_xml(
        self,
        parent_elem: ET.Element,
        line: MoveLine,
        ns: dict[str, str],
        *,
        line_id: str = "1",
    ) -> None:
        """Build a UBL InvoiceLine element from a MoveLine."""
        cac = ns["cac"]
        cbc = ns["cbc"]

        inv_line = ET.SubElement(parent_elem, f"{{{cac}}}InvoiceLine")
        ET.SubElement(inv_line, f"{{{cbc}}}ID").text = line_id

        qty = ET.SubElement(inv_line, f"{{{cbc}}}InvoicedQuantity")
        qty.text = f"{line.quantity:.2f}"
        qty.set("unitCode", "EA")

        amount = ET.SubElement(inv_line, f"{{{cbc}}}LineExtensionAmount")
        amount.text = f"{line.price_subtotal:.2f}"
        amount.set("currencyID", line.currency_code)

        # Item
        item = ET.SubElement(inv_line, f"{{{cac}}}Item")
        ET.SubElement(item, f"{{{cbc}}}Name").text = line.name or f"Line {line_id}"

        # Price
        price_elem = ET.SubElement(inv_line, f"{{{cac}}}Price")
        price_amount = ET.SubElement(price_elem, f"{{{cbc}}}PriceAmount")
        price_amount.text = f"{line.price_unit:.2f}"
        price_amount.set("currencyID", line.currency_code)

    def _build_tax_xml(
        self,
        parent_elem: ET.Element,
        tax_data: dict,
        ns: dict[str, str],
    ) -> None:
        """Build a UBL TaxTotal element."""
        cac = ns["cac"]
        cbc = ns["cbc"]

        tax_total = ET.SubElement(parent_elem, f"{{{cac}}}TaxTotal")
        tax_amount = ET.SubElement(tax_total, f"{{{cbc}}}TaxAmount")
        tax_amount.text = f"{tax_data['amount']:.2f}"
        tax_amount.set("currencyID", tax_data["currency"])

        # Tax subtotal (aggregated)
        subtotal = ET.SubElement(tax_total, f"{{{cac}}}TaxSubtotal")
        taxable = ET.SubElement(subtotal, f"{{{cbc}}}TaxableAmount")
        taxable.text = "0.00"
        taxable.set("currencyID", tax_data["currency"])

        sub_tax_amount = ET.SubElement(subtotal, f"{{{cbc}}}TaxAmount")
        sub_tax_amount.text = f"{tax_data['amount']:.2f}"
        sub_tax_amount.set("currencyID", tax_data["currency"])

        category = ET.SubElement(subtotal, f"{{{cac}}}TaxCategory")
        ET.SubElement(category, f"{{{cbc}}}ID").text = "S"
        ET.SubElement(category, f"{{{cbc}}}Percent").text = "0"
        scheme = ET.SubElement(category, f"{{{cac}}}TaxScheme")
        ET.SubElement(scheme, f"{{{cbc}}}ID").text = "VAT"

    @staticmethod
    def _tree_to_string(root: ET.Element) -> str:
        """Serialize an ElementTree element to an XML string with declaration."""
        ET.indent(root, space="  ")
        xml_bytes = ET.tostring(root, encoding="unicode", xml_declaration=False)
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes
