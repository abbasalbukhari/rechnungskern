from decimal import Decimal

from facturx import xml_check_xsd
from lxml import etree

from app.calc import calculate
from app.schemas import InvoiceRequest
from app.xml_builder import GUIDELINE, build_xml

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}


def build(data: dict) -> tuple[bytes, etree._Element]:
    req = InvoiceRequest.model_validate(data)
    xml = build_xml(req, calculate(req))
    return xml, etree.fromstring(xml)


def x(root, path: str) -> str:
    nodes = root.xpath(path, namespaces=NS)
    assert nodes, path
    node = nodes[0]
    return node.text if hasattr(node, "text") else node


def test_en16931_xml_structure(sample, out_dir):
    xml, root = build(sample)
    (out_dir / "sample.xml").write_bytes(xml)
    assert xml_check_xsd(xml, flavor="factur-x", level="en16931")

    assert x(root, "//rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID") == GUIDELINE["EN16931"]
    assert x(root, "//rsm:ExchangedDocument/ram:ID") == "RE-2026-00042"
    assert x(root, "//rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString") == "20260928"
    assert len(root.xpath("//ram:IncludedSupplyChainTradeLineItem", namespaces=NS)) == 3

    # price discount on line 2 -> gross price + allowance + net price
    line2 = root.xpath("//ram:IncludedSupplyChainTradeLineItem[ram:AssociatedDocumentLineDocument/ram:LineID='2']", namespaces=NS)[0]
    assert x(line2, ".//ram:GrossPriceProductTradePrice/ram:ChargeAmount") == "500.00"
    assert x(line2, ".//ram:GrossPriceProductTradePrice/ram:AppliedTradeAllowanceCharge/ram:ActualAmount") == "50.00"
    assert x(line2, ".//ram:NetPriceProductTradePrice/ram:ChargeAmount") == "450.00"
    assert x(line2, ".//ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeAllowanceCharge/ram:ActualAmount") == "90.00"
    assert x(line2, ".//ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeAllowanceCharge/ram:CalculationPercent") == "10.00"
    assert x(line2, ".//ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount") == "810.00"

    # document level allowance carries VAT category
    doc_ac = root.xpath("//ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradeAllowanceCharge", namespaces=NS)
    assert len(doc_ac) == 2
    assert x(doc_ac[0], "ram:ChargeIndicator/udt:Indicator") == "false"
    assert x(doc_ac[0], "ram:CategoryTradeTax/ram:RateApplicablePercent") == "19.00"

    ms = root.xpath("//ram:SpecifiedTradeSettlementHeaderMonetarySummation", namespaces=NS)[0]
    assert x(ms, "ram:LineTotalAmount") == "1894.20"
    assert x(ms, "ram:AllowanceTotalAmount") == "53.10"
    assert x(ms, "ram:ChargeTotalAmount") == "12.00"
    assert x(ms, "ram:TaxBasisTotalAmount") == "1853.10"
    assert x(ms, "ram:TaxTotalAmount") == "337.18"
    assert ms.xpath("ram:TaxTotalAmount/@currencyID", namespaces=NS) == ["EUR"]
    assert x(ms, "ram:GrandTotalAmount") == "2190.28"
    assert x(ms, "ram:DuePayableAmount") == "2190.28"

    assert x(root, "//ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']") == "DE123456789"
    assert x(root, "//ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID[@schemeID='FC']") == "99/123/45678"
    assert x(root, "//ram:PayeePartyCreditorFinancialAccount/ram:IBANID") == "DE89370400440532013000"
    assert x(root, "//ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString") == "20261028"


def test_xrechnung_xml(sample_xrechnung, out_dir):
    xml, root = build(sample_xrechnung)
    (out_dir / "sample_xrechnung.xml").write_bytes(xml)
    assert xml_check_xsd(xml, flavor="factur-x", level="en16931")
    assert x(root, "//ram:GuidelineSpecifiedDocumentContextParameter/ram:ID") == GUIDELINE["XRECHNUNG"]
    assert x(root, "//ram:BusinessProcessSpecifiedDocumentContextParameter/ram:ID") == "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
    assert x(root, "//ram:ApplicableHeaderTradeAgreement/ram:BuyerReference") == "04011000-12345-03"
    assert x(root, "//ram:BuyerTradeParty/ram:URIUniversalCommunication/ram:URIID") == "04011000-12345-03"
    assert root.xpath("//ram:BuyerTradeParty/ram:URIUniversalCommunication/ram:URIID/@schemeID", namespaces=NS) == ["0204"]
    assert x(root, "//ram:SellerTradeParty/ram:DefinedTradeContact/ram:EmailURIUniversalCommunication/ram:URIID") == "rechnung@example.com"


def test_exempt_breakdown(sample):
    sample["items"] = [{"name": "Reverse", "quantity": "1", "unit_price": "100", "tax_rate": "0", "tax_category": "AE"}]
    sample["allowances"] = sample["charges"] = []
    xml, root = build(sample)
    assert x(root, "//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode") == "AE"
    assert x(root, "//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:ExemptionReasonCode") == "VATEX-EU-AE"
    assert Decimal(x(root, "//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:CalculatedAmount")) == 0


def test_many_items(sample):
    sample["items"] = [
        {"name": f"Artikel {i}", "quantity": str(i % 5 + 1), "unit_price": f"{10 + i}.{i % 100:02d}", "tax_rate": "19"}
        for i in range(1, 101)
    ]
    sample["allowances"] = sample["charges"] = []
    xml, root = build(sample)
    assert len(root.xpath("//ram:IncludedSupplyChainTradeLineItem", namespaces=NS)) == 100
