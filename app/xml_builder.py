"""Build the EN 16931 CII XML (Factur-X / ZUGFeRD / XRechnung) with drafthorse.

The element order inside each aggregate follows the Factur-X 1.0.07 EN16931
XSD; drafthorse serialises fields in declaration order and validates the
result against that XSD, so a wrong mapping fails loudly here instead of at
the receiver.
"""

from __future__ import annotations

from decimal import Decimal

from drafthorse.models.accounting import ApplicableTradeTax, CategoryTradeTax, TradeAllowanceCharge
from drafthorse.models.document import Document
from drafthorse.models.note import IncludedNote
from drafthorse.models.party import TaxRegistration, TradeParty
from drafthorse.models.payment import PaymentMeans, PaymentTerms
from drafthorse.models.tradelines import AllowanceCharge as PriceAllowanceCharge
from drafthorse.models.tradelines import LineItem

from .calc import AllowanceChargeCalc, Totals, money
from .i18n import labels
from .schemas import Buyer, InvoiceRequest, Profile, Seller

GUIDELINE = {
    Profile.EN16931: "urn:cen.eu:en16931:2017",
    Profile.XRECHNUNG: "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0",
}
BUSINESS_PROCESS = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"  # BT-23
XSD_SCHEMA = "FACTUR-X_EN16931"
CREDIT_TRANSFER_CODES = {"30", "42", "58"}
DIRECT_DEBIT_CODES = {"49", "59"}


def _party(node: TradeParty, p: Seller | Buyer) -> None:
    if getattr(p, "customer_id", None):
        node.id = p.customer_id  # BT-46
    node.name = p.name
    if getattr(p, "legal_info", None):
        node.description = p.legal_info  # BT-33
    if p.legal_id:
        node.legal_organization.id = p.legal_id  # BT-30 / BT-47
    if p.trading_name:
        node.legal_organization.trade_name = p.trading_name  # BT-28 / BT-45
    if p.contact:
        c = p.contact
        if c.name:
            node.contact.person_name = c.name
        if c.department:
            node.contact.department_name = c.department
        if c.phone:
            node.contact.telephone.number = c.phone
        if c.email:
            node.contact.email.address = c.email
    a = p.address
    node.address.postcode = a.postcode
    node.address.line_one = a.line1
    if a.line2:
        node.address.line_two = a.line2
    if a.line3:
        node.address.line_three = a.line3
    node.address.city_name = a.city
    node.address.country_id = a.country
    if a.subdivision:
        node.address.country_subdivision = a.subdivision
    if p.electronic_address:
        node.electronic_address.uri_ID = (p.electronic_address.scheme, p.electronic_address.id)
    if getattr(p, "tax_number", None):
        node.tax_registrations.add(TaxRegistration(id=("FC", p.tax_number)))  # BT-32
    if p.vat_id:
        node.tax_registrations.add(TaxRegistration(id=("VA", p.vat_id)))  # BT-31 / BT-48


def _allowance_charge(ac: AllowanceChargeCalc, default_reason: str, with_tax: bool) -> TradeAllowanceCharge:
    node = TradeAllowanceCharge()
    node.indicator = ac.is_charge
    if ac.percent is not None:
        node.calculation_percent = money(ac.percent)
        node.basis_amount = ac.base_amount
    node.actual_amount = ac.amount
    if ac.reason_code:
        node.reason_code = ac.reason_code
    if ac.reason or not ac.reason_code:
        node.reason = ac.reason or default_reason  # BR-33/38/42/46: reason or code required
    if with_tax:
        node.trade_tax.add(
            CategoryTradeTax(
                type_code="VAT",
                category_code=ac.tax_category.value,
                rate_applicable_percent=money(ac.tax_rate),
            )
        )
    return node


def build_xml(req: InvoiceRequest, totals: Totals) -> bytes:
    inv, seller, buyer, pay = req.invoice, req.seller, req.buyer, req.payment
    lb = labels(req.language.value)
    doc = Document()

    # --- context -----------------------------------------------------------
    if req.profile == Profile.XRECHNUNG:
        doc.context.business_parameter.id = BUSINESS_PROCESS
    doc.context.guideline_parameter.id = GUIDELINE[req.profile]  # BT-24

    # --- header --------------------------------------------------------------
    doc.header.id = inv.number  # BT-1
    doc.header.type_code = inv.type_code  # BT-3
    doc.header.issue_date_time = inv.issue_date  # BT-2
    for n in inv.notes:  # BG-1
        note = IncludedNote(content=n.text)
        if n.subject_code:
            note.subject_code = n.subject_code
        doc.header.notes.add(note)

    # --- line items ----------------------------------------------------------
    for ln in totals.lines:
        item = ln.item
        li = LineItem()
        li.document.line_id = str(ln.position)  # BT-126
        if item.note:
            li.document.notes.add(IncludedNote(content=item.note))  # BT-127
        if item.seller_item_id:
            li.product.seller_assigned_id = item.seller_item_id  # BT-155
        if item.buyer_item_id:
            li.product.buyer_assigned_id = item.buyer_item_id  # BT-156
        li.product.name = item.name  # BT-153
        if item.description:
            li.product.description = item.description  # BT-154

        basis = (item.price_basis_quantity, item.unit)
        if ln.gross_unit_price is not None:  # BT-148 / BT-147
            li.agreement.gross.amount = ln.gross_unit_price
            li.agreement.gross.basis_quantity = basis
            li.agreement.gross.charge.add(PriceAllowanceCharge(indicator=False, actual_amount=ln.price_discount))
        li.agreement.net.amount = ln.net_unit_price  # BT-146
        li.agreement.net.basis_quantity = basis  # BT-149 / BT-150

        li.delivery.billed_quantity = (ln.quantity, item.unit)  # BT-129 / BT-130

        li.settlement.trade_tax.type_code = "VAT"
        li.settlement.trade_tax.category_code = item.tax_category.value  # BT-151
        li.settlement.trade_tax.rate_applicable_percent = money(item.tax_rate)  # BT-152
        for a in ln.allowances:  # BG-27
            li.settlement.allowance_charge.add(_allowance_charge(a, lb["allowance"], with_tax=False))
        for c in ln.charges:  # BG-28
            li.settlement.allowance_charge.add(_allowance_charge(c, lb["charge"], with_tax=False))
        li.settlement.monetary_summation.total_amount = ln.total  # BT-131
        doc.trade.items.add(li)

    # --- agreement -----------------------------------------------------------
    ag = doc.trade.agreement
    if inv.buyer_reference:
        ag.buyer_reference = inv.buyer_reference  # BT-10
    _party(ag.seller, seller)
    _party(ag.buyer, buyer)
    if inv.seller_order_reference:
        ag.seller_order.issuer_assigned_id = inv.seller_order_reference  # BT-14
    if inv.order_reference:
        ag.buyer_order.issuer_assigned_id = inv.order_reference  # BT-13
    if inv.contract_reference:
        ag.contract.issuer_assigned_id = inv.contract_reference  # BT-12
    if inv.project_reference:
        ag.procuring_project_type.id = inv.project_reference  # BT-11
        ag.procuring_project_type.name = inv.project_reference

    # --- delivery ------------------------------------------------------------
    if inv.delivery_date:
        doc.trade.delivery.event.occurrence = inv.delivery_date  # BT-72

    # --- settlement ----------------------------------------------------------
    st = doc.trade.settlement
    if pay.creditor_id:
        st.creditor_reference_id = pay.creditor_id  # BT-90
    if inv.payment_reference:
        st.payment_reference = inv.payment_reference  # BT-83
    st.currency_code = inv.currency  # BT-5

    pm = PaymentMeans()
    pm.type_code = pay.means_code  # BT-81
    if pay.means_text:
        pm.information.add(pay.means_text)  # BT-82
    if seller.bank and pay.means_code in CREDIT_TRANSFER_CODES:  # BG-17
        pm.payee_account.iban = seller.bank.iban  # BT-84
        if seller.bank.account_holder:
            pm.payee_account.account_name = seller.bank.account_holder  # BT-85
        if seller.bank.bic:
            pm.payee_institution.bic = seller.bank.bic  # BT-86
    st.payment_means.add(pm)

    for b in totals.breakdown:  # BG-23
        t = ApplicableTradeTax()
        t.calculated_amount = b.tax_amount  # BT-117
        t.type_code = "VAT"
        if b.exemption_reason:
            t.exemption_reason = b.exemption_reason  # BT-120
        t.basis_amount = b.taxable_amount  # BT-116
        t.category_code = b.category.value  # BT-118
        if b.exemption_reason_code:
            t.exemption_reason_code = b.exemption_reason_code  # BT-121
        t.rate_applicable_percent = money(b.rate)  # BT-119
        st.trade_tax.add(t)

    if inv.period_start and inv.period_end:  # BG-14
        st.period.start = inv.period_start
        st.period.end = inv.period_end

    for a in totals.allowances:  # BG-20
        st.allowance_charge.add(_allowance_charge(a, lb["allowance"], with_tax=True))
    for c in totals.charges:  # BG-21
        st.allowance_charge.add(_allowance_charge(c, lb["charge"], with_tax=True))

    if pay.terms_text or inv.due_date or pay.mandate_reference:  # BT-20 / BT-9 / BT-89
        terms = PaymentTerms()
        if pay.terms_text:
            terms.description = pay.terms_text
        if inv.due_date:
            terms.due = inv.due_date
        if pay.mandate_reference and pay.means_code in DIRECT_DEBIT_CODES:
            terms.debit_mandate_id = pay.mandate_reference
        st.terms.add(terms)

    ms = st.monetary_summation  # BG-22
    ms.line_total = totals.line_total  # BT-106
    ms.charge_total = totals.charge_total  # BT-108
    ms.allowance_total = totals.allowance_total  # BT-107
    ms.tax_basis_total = totals.tax_basis_total  # BT-109
    ms.tax_total = (totals.tax_total, inv.currency)  # BT-110
    ms.grand_total = totals.grand_total  # BT-112
    if totals.prepaid:
        ms.prepaid_total = totals.prepaid  # BT-113
    ms.due_amount = totals.due  # BT-115

    for prev in inv.preceding_invoices:  # BG-3
        st.invoice_referenced_document.issuer_assigned_id = prev.number  # BT-25
        if prev.issue_date:
            st.invoice_referenced_document.issue_date_time = prev.issue_date  # BT-26

    return doc.serialize(schema=XSD_SCHEMA)


def xml_filename(req: InvoiceRequest) -> str:
    return "xrechnung.xml" if req.profile == Profile.XRECHNUNG else "factur-x.xml"


__all__ = ["build_xml", "xml_filename", "GUIDELINE", "Decimal"]
