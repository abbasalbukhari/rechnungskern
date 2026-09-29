from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.calc import CalculationError, calculate
from app.schemas import InvoiceRequest


def D(x):
    return Decimal(x)


def test_sample_totals(sample):
    req = InvoiceRequest.model_validate(sample)
    t = calculate(req)

    # line 1: 8 h * 120 = 960
    assert t.lines[0].total == D("960.00")
    # line 2: gross 500 - 50 = 450 net price; 2 * 450 = 900; 10 % allowance = 90 -> 810
    assert t.lines[1].net_unit_price == D("450.00")
    assert t.lines[1].base_amount == D("900.00")
    assert t.lines[1].allowances[0].amount == D("90.00")
    assert t.lines[1].total == D("810.00")
    # line 3: 3 * 39.90 = 119.70 + 4.50 charge = 124.20
    assert t.lines[2].total == D("124.20")

    assert t.line_total == D("1894.20")
    # doc allowance 3 % of the 19 % group (960 + 810 = 1770) = 53.10
    assert t.allowances[0].amount == D("53.10")
    assert t.allowance_total == D("53.10")
    assert t.charge_total == D("12.00")
    assert t.tax_basis_total == D("1853.10")

    groups = {(b.category.value, b.rate): b for b in t.breakdown}
    g19 = groups[("S", D("19.00"))]
    g7 = groups[("S", D("7.00"))]
    assert g19.taxable_amount == D("1728.90")  # 1770 - 53.10 + 12
    assert g19.tax_amount == D("328.49")  # 1728.90 * 0.19 = 328.491
    assert g7.taxable_amount == D("124.20")
    assert g7.tax_amount == D("8.69")  # 124.20 * 0.07 = 8.694
    assert t.tax_total == D("337.18")
    assert t.grand_total == D("2190.28")
    assert t.due == D("2190.28")


def test_rounding_half_up(sample):
    sample["items"] = [{"name": "x", "quantity": "1", "unit_price": "0.125", "tax_rate": "19"}]
    with pytest.raises(ValidationError):
        InvoiceRequest.model_validate(sample)  # more than 2 decimals in a money field
    sample["items"] = [{"name": "x", "quantity": "3", "unit_price": "0.35", "tax_rate": "19"}]
    sample["allowances"] = sample["charges"] = []
    t = calculate(InvoiceRequest.model_validate(sample))
    assert t.lines[0].total == D("1.05")
    assert t.tax_total == D("0.20")  # 0.1995 -> 0.20


def test_doc_allowance_inferred_when_single_group(sample):
    sample["items"] = sample["items"][:2]
    sample["allowances"] = [{"amount": "10.00"}]
    sample["charges"] = []
    t = calculate(InvoiceRequest.model_validate(sample))
    assert t.allowances[0].tax_category.value == "S"
    assert t.allowances[0].tax_rate == D("19.00")
    assert t.allowances[0].reason_code == "95"


def test_doc_allowance_rejected_when_ambiguous(sample):
    sample["allowances"] = [{"amount": "10.00"}]
    with pytest.raises(CalculationError):
        calculate(InvoiceRequest.model_validate(sample))


def test_doc_allowance_unknown_group(sample):
    sample["allowances"] = [{"amount": "10.00", "tax_category": "S", "tax_rate": "5"}]
    with pytest.raises(CalculationError):
        calculate(InvoiceRequest.model_validate(sample))


def test_exemption_defaults(sample):
    sample["items"] = [{"name": "Export", "quantity": "1", "unit_price": "100", "tax_rate": "0", "tax_category": "G"}]
    sample["allowances"] = sample["charges"] = []
    t = calculate(InvoiceRequest.model_validate(sample))
    assert t.tax_total == D("0.00")
    assert t.breakdown[0].exemption_reason_code == "VATEX-EU-G"
    assert "Ausfuhr" in t.breakdown[0].exemption_reason


def test_prepaid(sample):
    sample["invoice"]["prepaid_amount"] = "1000.00"
    t = calculate(InvoiceRequest.model_validate(sample))
    assert t.due == t.grand_total - D("1000.00")


def test_schema_rules(sample):
    bad = dict(sample)
    bad["items"] = [{"name": "x", "quantity": "1", "unit_price": "10", "tax_rate": "19", "tax_category": "E"}]
    with pytest.raises(ValidationError):
        InvoiceRequest.model_validate(bad)  # E needs rate 0

    bad = dict(sample)
    bad["profile"] = "XRECHNUNG"
    with pytest.raises(ValidationError):
        InvoiceRequest.model_validate(bad)  # needs buyer_reference

    bad = dict(sample)
    bad["seller"] = {**sample["seller"], "vat_id": None, "tax_number": None}
    with pytest.raises(ValidationError):
        InvoiceRequest.model_validate(bad)
