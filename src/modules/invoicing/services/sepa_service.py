"""SEPA XML generation service.

Generates pain.001.001.03 (SCT — SEPA Credit Transfer) and
pain.008.001.02 (SDD — SEPA Direct Debit) XML files from batch
payments. Uses only stdlib xml.etree.ElementTree — no external deps.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, tostring

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors.exceptions import BusinessRuleError, NotFoundError
from src.modules.invoicing.models.batch_payment import InvoiceBatchPayment
from src.modules.invoicing.repositories.batch_payment_repo import (
    InvoiceBatchPaymentRepository,
)

logger = logging.getLogger(__name__)

# ISO 20022 namespaces
NS_PAIN_001 = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"
NS_PAIN_008 = "urn:iso:std:iso:20022:tech:xsd:pain.008.001.02"


class SEPAService:
    """Generates SEPA XML files for batch payments."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.batch_repo = InvoiceBatchPaymentRepository(db)

    # ── Public API ─────────────────────────────────────────────────────

    async def generate_sepa_credit_transfer(
        self, batch_id: uuid.UUID,
    ) -> bytes:
        """Generate a pain.001.001.03 SEPA Credit Transfer XML.

        Used for outbound payments (paying vendors).
        Returns the XML content as bytes.
        """
        batch = await self._get_validated_batch(batch_id, "sepa_credit")

        pending_lines = [l for l in batch.lines if l.state == "pending"]
        if not pending_lines:
            raise BusinessRuleError("No pending lines to generate SEPA file for")

        # Validate all lines have IBANs
        for line in pending_lines:
            if not line.partner_bank_account:
                raise BusinessRuleError(
                    f"Line for partner {line.partner_id} is missing IBAN"
                )
            if not self.validate_iban(line.partner_bank_account):
                raise BusinessRuleError(
                    f"Invalid IBAN '{line.partner_bank_account}' "
                    f"for partner {line.partner_id}"
                )

        # Build XML
        root = Element("Document", xmlns=NS_PAIN_001)
        cst_trf = SubElement(root, "CstmrCdtTrfInitn")

        # Group Header
        grp_hdr = SubElement(cst_trf, "GrpHdr")
        msg_id = f"BATCH-{batch.id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        SubElement(grp_hdr, "MsgId").text = msg_id
        SubElement(grp_hdr, "CreDtTm").text = datetime.utcnow().isoformat()
        SubElement(grp_hdr, "NbOfTxs").text = str(len(pending_lines))
        SubElement(grp_hdr, "CtrlSum").text = f"{batch.total_amount:.2f}"

        # Initiating Party
        initg_pty = SubElement(grp_hdr, "InitgPty")
        SubElement(initg_pty, "Nm").text = "Foundrix ERP"

        # Payment Information block
        pmt_inf = SubElement(cst_trf, "PmtInf")
        SubElement(pmt_inf, "PmtInfId").text = f"PMT-{batch.id}"
        SubElement(pmt_inf, "PmtMtd").text = "TRF"  # Transfer
        SubElement(pmt_inf, "NbOfTxs").text = str(len(pending_lines))
        SubElement(pmt_inf, "CtrlSum").text = f"{batch.total_amount:.2f}"

        # Payment Type Information
        pmt_tp_inf = SubElement(pmt_inf, "PmtTpInf")
        svc_lvl = SubElement(pmt_tp_inf, "SvcLvl")
        SubElement(svc_lvl, "Cd").text = "SEPA"

        # Requested Execution Date
        reqd_exctn_dt = batch.execution_date or datetime.utcnow().date()
        SubElement(pmt_inf, "ReqdExctnDt").text = reqd_exctn_dt.isoformat()

        # Debtor (company sending money)
        dbtr = SubElement(pmt_inf, "Dbtr")
        SubElement(dbtr, "Nm").text = "Foundrix ERP"

        # Debtor Account (placeholder — would come from journal config)
        dbtr_acct = SubElement(pmt_inf, "DbtrAcct")
        dbtr_id = SubElement(dbtr_acct, "Id")
        SubElement(dbtr_id, "IBAN").text = "PLACEHOLDER_DEBTOR_IBAN"

        # Debtor Agent (BIC)
        dbtr_agt = SubElement(pmt_inf, "DbtrAgt")
        fin_instn_id = SubElement(dbtr_agt, "FinInstnId")
        SubElement(fin_instn_id, "BIC").text = "PLACEHOLDER_BIC"

        # Credit Transfer Transactions
        for line in pending_lines:
            cdt_trf_tx = SubElement(pmt_inf, "CdtTrfTxInf")

            # Payment ID
            pmt_id = SubElement(cdt_trf_tx, "PmtId")
            SubElement(pmt_id, "EndToEndId").text = str(line.id)

            # Amount
            amt = SubElement(cdt_trf_tx, "Amt")
            inst_amt = SubElement(amt, "InstdAmt", Ccy=line.currency_code or "EUR")
            inst_amt.text = f"{line.amount:.2f}"

            # Creditor Agent (BIC)
            if line.partner_bic:
                cdtr_agt = SubElement(cdt_trf_tx, "CdtrAgt")
                cdtr_fin = SubElement(cdtr_agt, "FinInstnId")
                SubElement(cdtr_fin, "BIC").text = line.partner_bic

            # Creditor
            cdtr = SubElement(cdt_trf_tx, "Cdtr")
            SubElement(cdtr, "Nm").text = f"Partner-{line.partner_id}"

            # Creditor Account
            cdtr_acct = SubElement(cdt_trf_tx, "CdtrAcct")
            cdtr_acct_id = SubElement(cdtr_acct, "Id")
            SubElement(cdtr_acct_id, "IBAN").text = line.partner_bank_account

            # Remittance Information
            if line.communication:
                rmt_inf = SubElement(cdt_trf_tx, "RmtInf")
                SubElement(rmt_inf, "Ustrd").text = line.communication

        xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(
            root, encoding="unicode",
        ).encode("utf-8")

        # Store on batch
        batch.generated_file = xml_bytes
        batch.generated_filename = f"sepa_credit_{batch.name.replace('/', '_')}.xml"
        await self.db.flush()

        logger.info(
            "Generated SEPA credit transfer for batch %s (%d transactions)",
            batch.name, len(pending_lines),
        )
        return xml_bytes

    async def generate_sepa_direct_debit(
        self, batch_id: uuid.UUID,
    ) -> bytes:
        """Generate a pain.008.001.02 SEPA Direct Debit XML.

        Used for inbound payments (collecting from customers).
        Returns the XML content as bytes.
        """
        batch = await self._get_validated_batch(batch_id, "sepa_debit")

        pending_lines = [l for l in batch.lines if l.state == "pending"]
        if not pending_lines:
            raise BusinessRuleError("No pending lines to generate SEPA file for")

        for line in pending_lines:
            if not line.partner_bank_account:
                raise BusinessRuleError(
                    f"Line for partner {line.partner_id} is missing IBAN"
                )
            if not self.validate_iban(line.partner_bank_account):
                raise BusinessRuleError(
                    f"Invalid IBAN '{line.partner_bank_account}' "
                    f"for partner {line.partner_id}"
                )

        # Build XML
        root = Element("Document", xmlns=NS_PAIN_008)
        cst_dd = SubElement(root, "CstmrDrctDbtInitn")

        # Group Header
        grp_hdr = SubElement(cst_dd, "GrpHdr")
        msg_id = f"DD-BATCH-{batch.id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        SubElement(grp_hdr, "MsgId").text = msg_id
        SubElement(grp_hdr, "CreDtTm").text = datetime.utcnow().isoformat()
        SubElement(grp_hdr, "NbOfTxs").text = str(len(pending_lines))
        SubElement(grp_hdr, "CtrlSum").text = f"{batch.total_amount:.2f}"

        # Initiating Party
        initg_pty = SubElement(grp_hdr, "InitgPty")
        SubElement(initg_pty, "Nm").text = "Foundrix ERP"

        # Payment Information
        pmt_inf = SubElement(cst_dd, "PmtInf")
        SubElement(pmt_inf, "PmtInfId").text = f"DD-PMT-{batch.id}"
        SubElement(pmt_inf, "PmtMtd").text = "DD"  # Direct Debit
        SubElement(pmt_inf, "NbOfTxs").text = str(len(pending_lines))
        SubElement(pmt_inf, "CtrlSum").text = f"{batch.total_amount:.2f}"

        # Payment Type Information
        pmt_tp_inf = SubElement(pmt_inf, "PmtTpInf")
        svc_lvl = SubElement(pmt_tp_inf, "SvcLvl")
        SubElement(svc_lvl, "Cd").text = "SEPA"
        lcl_instrm = SubElement(pmt_tp_inf, "LclInstrm")
        SubElement(lcl_instrm, "Cd").text = "CORE"
        SubElement(pmt_tp_inf, "SeqTp").text = "OOFF"  # One-off

        # Requested Collection Date
        reqd_colltn_dt = batch.execution_date or datetime.utcnow().date()
        SubElement(pmt_inf, "ReqdColltnDt").text = reqd_colltn_dt.isoformat()

        # Creditor (company collecting money)
        cdtr = SubElement(pmt_inf, "Cdtr")
        SubElement(cdtr, "Nm").text = "Foundrix ERP"

        # Creditor Account
        cdtr_acct = SubElement(pmt_inf, "CdtrAcct")
        cdtr_id = SubElement(cdtr_acct, "Id")
        SubElement(cdtr_id, "IBAN").text = "PLACEHOLDER_CREDITOR_IBAN"

        # Creditor Agent
        cdtr_agt = SubElement(pmt_inf, "CdtrAgt")
        fin_instn_id = SubElement(cdtr_agt, "FinInstnId")
        SubElement(fin_instn_id, "BIC").text = "PLACEHOLDER_BIC"

        # Direct Debit Transactions
        for line in pending_lines:
            dd_tx = SubElement(pmt_inf, "DrctDbtTxInf")

            # Payment ID
            pmt_id = SubElement(dd_tx, "PmtId")
            SubElement(pmt_id, "EndToEndId").text = str(line.id)

            # Amount
            amt = SubElement(dd_tx, "InstdAmt", Ccy=line.currency_code or "EUR")
            amt.text = f"{line.amount:.2f}"

            # Mandate Related Information
            dd_tx_elem = SubElement(dd_tx, "DrctDbtTx")
            mndt_rltd_inf = SubElement(dd_tx_elem, "MndtRltdInf")
            SubElement(mndt_rltd_inf, "MndtId").text = f"MNDT-{line.id}"
            SubElement(mndt_rltd_inf, "DtOfSgntr").text = (
                datetime.utcnow().date().isoformat()
            )

            # Debtor Agent (BIC)
            if line.partner_bic:
                dbtr_agt = SubElement(dd_tx, "DbtrAgt")
                dbtr_fin = SubElement(dbtr_agt, "FinInstnId")
                SubElement(dbtr_fin, "BIC").text = line.partner_bic

            # Debtor
            dbtr = SubElement(dd_tx, "Dbtr")
            SubElement(dbtr, "Nm").text = f"Partner-{line.partner_id}"

            # Debtor Account
            dbtr_acct = SubElement(dd_tx, "DbtrAcct")
            dbtr_acct_id = SubElement(dbtr_acct, "Id")
            SubElement(dbtr_acct_id, "IBAN").text = line.partner_bank_account

            # Remittance Information
            if line.communication:
                rmt_inf = SubElement(dd_tx, "RmtInf")
                SubElement(rmt_inf, "Ustrd").text = line.communication

        xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(
            root, encoding="unicode",
        ).encode("utf-8")

        # Store on batch
        batch.generated_file = xml_bytes
        batch.generated_filename = f"sepa_dd_{batch.name.replace('/', '_')}.xml"
        await self.db.flush()

        logger.info(
            "Generated SEPA direct debit for batch %s (%d transactions)",
            batch.name, len(pending_lines),
        )
        return xml_bytes

    # ── Validation Helpers ─────────────────────────────────────────────

    @staticmethod
    def validate_iban(iban: str) -> bool:
        """Basic IBAN validation: format, length, and check digits.

        - Removes spaces and converts to uppercase.
        - Checks that it starts with 2 letters + 2 digits.
        - Validates length is between 15 and 34 characters.
        - Performs modulo-97 check digit validation (ISO 7064).
        """
        iban = iban.replace(" ", "").upper()

        # Basic format: 2 letters + 2 digits + up to 30 alphanumeric
        if not re.match(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$", iban):
            return False

        if len(iban) < 15 or len(iban) > 34:
            return False

        # Move first 4 chars to end for check digit calculation
        rearranged = iban[4:] + iban[:4]

        # Convert letters to numbers (A=10, B=11, ..., Z=35)
        numeric_str = ""
        for char in rearranged:
            if char.isdigit():
                numeric_str += char
            else:
                numeric_str += str(ord(char) - ord("A") + 10)

        # Modulo 97 check
        return int(numeric_str) % 97 == 1

    @staticmethod
    def validate_bic(bic: str) -> bool:
        """Basic BIC/SWIFT format validation.

        Valid BIC formats:
        - 8 characters: BANKCCLL (bank code + country + location)
        - 11 characters: BANKCCLLBBB (+ branch code)
        """
        bic = bic.replace(" ", "").upper()
        return bool(re.match(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$", bic))

    # ── Private Helpers ────────────────────────────────────────────────

    async def _get_validated_batch(
        self,
        batch_id: uuid.UUID,
        expected_method: str,
    ) -> InvoiceBatchPayment:
        """Fetch batch and validate it matches the expected payment method."""
        batch = await self.batch_repo.get_with_lines(batch_id)
        if batch is None:
            raise NotFoundError("InvoiceBatchPayment", str(batch_id))

        if batch.payment_method != expected_method:
            raise BusinessRuleError(
                f"Batch payment method is '{batch.payment_method}', "
                f"expected '{expected_method}'"
            )

        if batch.state not in ("confirmed", "sent"):
            raise BusinessRuleError(
                f"Batch must be confirmed before generating SEPA file. "
                f"Current state: '{batch.state}'"
            )

        return batch
