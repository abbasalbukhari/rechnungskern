"""Extract a short human-readable summary from an e-invoice (PDF with embedded XML, or XML)."""

from __future__ import annotations

import io
import logging

from lxml import etree

log = logging.getLogger("e-rechnung")

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}


def _first(root: etree._Element, path: str) -> str | None:
    nodes = root.xpath(path, namespaces=NS)
    if not nodes:
        return None
    node = nodes[0]
    text = node.text if hasattr(node, "text") else str(node)
    return text.strip() if text else None


def _date(value: str | None) -> str | None:
    if value and len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def summarize_xml(xml: bytes) -> dict:
    root = etree.fromstring(xml)
    tag = etree.QName(root).localname
    if tag == "CrossIndustryInvoice":
        settlement = "//rsm:SupplyChainTradeTransaction/ram:ApplicableHeaderTradeSettlement"
        return {
            "syntax": "CII",
            "profile": _first(root, "//rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID"),
            "number": _first(root, "//rsm:ExchangedDocument/ram:ID"),
            "type_code": _first(root, "//rsm:ExchangedDocument/ram:TypeCode"),
            "issue_date": _date(_first(root, "//rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString")),
            "seller": _first(root, "//ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:Name"),
            "buyer": _first(root, "//ram:ApplicableHeaderTradeAgreement/ram:BuyerTradeParty/ram:Name"),
            "buyer_reference": _first(root, "//ram:ApplicableHeaderTradeAgreement/ram:BuyerReference"),
            "currency": _first(root, f"{settlement}/ram:InvoiceCurrencyCode"),
            "grand_total": _first(root, f"{settlement}/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:GrandTotalAmount"),
            "due_amount": _first(root, f"{settlement}/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:DuePayableAmount"),
            "due_date": _date(_first(root, f"{settlement}/ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString")),
            "iban": _first(root, f"{settlement}/ram:SpecifiedTradeSettlementPaymentMeans/ram:PayeePartyCreditorFinancialAccount/ram:IBANID"),
            "line_count": len(root.xpath("//ram:IncludedSupplyChainTradeLineItem", namespaces=NS)),
        }
    if tag in ("Invoice", "CreditNote"):
        return {
            "syntax": "UBL",
            "profile": _first(root, "//cbc:CustomizationID"),
            "number": _first(root, "//cbc:ID"),
            "type_code": _first(root, "//cbc:InvoiceTypeCode") or _first(root, "//cbc:CreditNoteTypeCode"),
            "issue_date": _first(root, "//cbc:IssueDate"),
            "seller": _first(root, "//cac:AccountingSupplierParty//cac:PartyLegalEntity/cbc:RegistrationName")
            or _first(root, "//cac:AccountingSupplierParty//cac:PartyName/cbc:Name"),
            "buyer": _first(root, "//cac:AccountingCustomerParty//cac:PartyLegalEntity/cbc:RegistrationName")
            or _first(root, "//cac:AccountingCustomerParty//cac:PartyName/cbc:Name"),
            "buyer_reference": _first(root, "//cbc:BuyerReference"),
            "currency": _first(root, "//cbc:DocumentCurrencyCode"),
            "grand_total": _first(root, "//cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount"),
            "due_amount": _first(root, "//cac:LegalMonetaryTotal/cbc:PayableAmount"),
            "due_date": _first(root, "//cbc:DueDate"),
            "iban": _first(root, "//cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID"),
            "line_count": len(root.xpath("//cac:InvoiceLine | //cac:CreditNoteLine", namespaces=NS)),
        }
    return {"syntax": tag}


def summarize(data: bytes) -> dict | None:
    """Return a summary dict or None when the document contains no readable e-invoice XML."""
    try:
        if data.startswith(b"%PDF"):
            from facturx import get_xml_from_pdf

            result = get_xml_from_pdf(io.BytesIO(data), check_xsd=False)
            if not result or not result[1]:
                return None
            xml = result[1]
            if isinstance(xml, str):
                xml = xml.encode("utf-8")
            info = summarize_xml(xml)
            info["embedded_file"] = result[0]
            return info
        return summarize_xml(data)
    except Exception as exc:  # any parse problem => no summary, validation still runs
        log.info("no summary extracted: %s", exc)
        return None
