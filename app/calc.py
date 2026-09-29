"""Amount calculation according to EN 16931.

All arithmetic uses ``Decimal`` with ROUND_HALF_UP to two places. Every
intermediate amount that ends up in the XML is rounded *before* it is summed,
so the totals satisfy the BR-CO-* consistency rules exactly.

Formulas (business terms in brackets):

    line net price      [BT-146] = gross price [BT-148] - price discount [BT-147]
    line base                    = net price * quantity / price basis quantity
    line net amount     [BT-131] = line base - sum(line allowances) + sum(line charges)
    sum of lines        [BT-106] = sum(BT-131)
    allowances total    [BT-107] = sum(document allowances)
    charges total       [BT-108] = sum(document charges)
    tax basis           [BT-109] = BT-106 - BT-107 + BT-108
    per category/rate:  taxable [BT-116] = lines - allowances + charges of that group
                        tax     [BT-117] = round(BT-116 * rate / 100)
    tax total           [BT-110] = sum(BT-117)
    grand total         [BT-112] = BT-109 + BT-110
    amount due          [BT-115] = BT-112 - prepaid [BT-113]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from .schemas import (
    DEFAULT_EXEMPTION_CODE,
    DEFAULT_EXEMPTION_TEXT,
    AllowanceCharge,
    DocumentAllowanceCharge,
    InvoiceRequest,
    Item,
    TaxCategory,
)

CENT = Decimal("0.01")
QTY = Decimal("0.0001")


class CalculationError(ValueError):
    """Business rule violation detected while computing amounts."""


def money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def qty(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(QTY, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Result structures
# --------------------------------------------------------------------------- #


@dataclass
class AllowanceChargeCalc:
    is_charge: bool
    amount: Decimal  # BT-136 / BT-141 / BT-92 / BT-99
    base_amount: Optional[Decimal]  # BT-137 / BT-142 / BT-93 / BT-100
    percent: Optional[Decimal]  # BT-138 / BT-143 / BT-94 / BT-101
    reason: Optional[str]
    reason_code: Optional[str]
    tax_category: Optional[TaxCategory] = None  # document level only
    tax_rate: Optional[Decimal] = None  # document level only


@dataclass
class LineCalc:
    position: int
    item: Item
    gross_unit_price: Optional[Decimal]  # BT-148 (only when a price discount exists)
    price_discount: Optional[Decimal]  # BT-147
    net_unit_price: Decimal  # BT-146
    quantity: Decimal  # BT-129
    base_amount: Decimal  # net price * qty before line allowances/charges
    allowances: list[AllowanceChargeCalc]
    charges: list[AllowanceChargeCalc]
    total: Decimal  # BT-131


@dataclass
class TaxBreakdown:
    category: TaxCategory  # BT-118
    rate: Decimal  # BT-119
    taxable_amount: Decimal  # BT-116
    tax_amount: Decimal  # BT-117
    exemption_reason: Optional[str] = None  # BT-120
    exemption_reason_code: Optional[str] = None  # BT-121


@dataclass
class Totals:
    lines: list[LineCalc]
    allowances: list[AllowanceChargeCalc]
    charges: list[AllowanceChargeCalc]
    breakdown: list[TaxBreakdown]
    line_total: Decimal  # BT-106
    allowance_total: Decimal  # BT-107
    charge_total: Decimal  # BT-108
    tax_basis_total: Decimal  # BT-109
    tax_total: Decimal  # BT-110
    grand_total: Decimal  # BT-112
    prepaid: Decimal  # BT-113
    due: Decimal  # BT-115
    currency: str = "EUR"
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Calculation
# --------------------------------------------------------------------------- #


def _ac_amount(ac: AllowanceCharge, base: Decimal) -> AllowanceChargeCalc:
    if ac.percent is not None:
        amount = money(base * ac.percent / Decimal(100))
        return AllowanceChargeCalc(False, amount, money(base), ac.percent, ac.reason, ac.reason_code)
    return AllowanceChargeCalc(False, money(ac.amount), None, None, ac.reason, ac.reason_code)


def _calc_line(position: int, item: Item) -> LineCalc:
    if item.price_discount is not None:
        gross = money(item.unit_price)
        discount = money(item.price_discount)
        net_price = money(gross - discount)
    else:
        gross, discount, net_price = None, None, money(item.unit_price)

    quantity = qty(item.quantity)
    base = money(net_price * quantity / item.price_basis_quantity)

    allowances = [_ac_amount(a, base) for a in item.allowances]
    charges = [_ac_amount(c, base) for c in item.charges]
    for c in charges:
        c.is_charge = True

    total = money(base - sum(a.amount for a in allowances) + sum(c.amount for c in charges))
    return LineCalc(position, item, gross, discount, net_price, quantity, base, allowances, charges, total)


def _group_key(cat: TaxCategory, rate: Decimal) -> tuple[str, Decimal]:
    return cat.value, money(rate)


def _resolve_doc_ac(
    ac: DocumentAllowanceCharge,
    groups: dict[tuple[str, Decimal], Decimal],
    is_charge: bool,
) -> AllowanceChargeCalc:
    kind = "charge" if is_charge else "allowance"
    cat, rate = ac.tax_category, ac.tax_rate
    if cat is None or rate is None:
        if len(groups) != 1:
            raise CalculationError(
                f"document {kind} needs tax_category and tax_rate because the invoice "
                f"contains {len(groups)} different VAT category/rate groups"
            )
        (only_cat, only_rate), = groups.keys()
        cat = cat or TaxCategory(only_cat)
        rate = money(only_rate) if rate is None else rate
    key = _group_key(cat, rate)
    if key not in groups:
        raise CalculationError(
            f"document {kind} refers to VAT group {cat.value} {money(rate)}% "
            f"which no line item uses (BR-CO-18)"
        )
    if cat == TaxCategory.S and rate <= 0:
        raise CalculationError(f"document {kind} with category S needs tax_rate > 0")
    if cat != TaxCategory.S and rate != 0:
        raise CalculationError(f"document {kind} with category {cat.value} needs tax_rate 0")

    base = groups[key]
    if ac.percent is not None:
        amount = money(base * ac.percent / Decimal(100))
        res = AllowanceChargeCalc(is_charge, amount, money(base), ac.percent, ac.reason, ac.reason_code)
    else:
        res = AllowanceChargeCalc(is_charge, money(ac.amount), None, None, ac.reason, ac.reason_code)
    res.tax_category, res.tax_rate = cat, money(rate)
    if not res.reason_code:
        res.reason_code = "95" if not is_charge else None  # UNTDID 5189 "Discount"
    return res


def calculate(req: InvoiceRequest) -> Totals:
    lines = [_calc_line(i + 1, item) for i, item in enumerate(req.items)]

    # Sum of line net amounts per VAT group (category, rate) -> base for doc allowances
    groups: dict[tuple[str, Decimal], Decimal] = {}
    for ln in lines:
        key = _group_key(ln.item.tax_category, ln.item.tax_rate)
        groups[key] = money(groups.get(key, Decimal(0)) + ln.total)

    allowances = [_resolve_doc_ac(a, groups, False) for a in req.allowances]
    charges = [_resolve_doc_ac(c, groups, True) for c in req.charges]

    # VAT breakdown per group (BG-23)
    lang = req.language.value
    breakdown: list[TaxBreakdown] = []
    for (cat_s, rate), line_sum in groups.items():
        cat = TaxCategory(cat_s)
        taxable = money(
            line_sum
            - sum(a.amount for a in allowances if _group_key(a.tax_category, a.tax_rate) == (cat_s, rate))
            + sum(c.amount for c in charges if _group_key(c.tax_category, c.tax_rate) == (cat_s, rate))
        )
        tax = money(taxable * rate / Decimal(100)) if cat == TaxCategory.S else money(0)
        reason = reason_code = None
        if cat not in (TaxCategory.S, TaxCategory.Z):
            items_in_group = [ln.item for ln in lines if _group_key(ln.item.tax_category, ln.item.tax_rate) == (cat_s, rate)]
            reason = next((i.tax_exemption_reason for i in items_in_group if i.tax_exemption_reason), None)
            reason_code = next((i.tax_exemption_reason_code for i in items_in_group if i.tax_exemption_reason_code), None)
            reason = reason or DEFAULT_EXEMPTION_TEXT[cat][lang]
            reason_code = reason_code or DEFAULT_EXEMPTION_CODE.get(cat)
        breakdown.append(TaxBreakdown(cat, rate, taxable, tax, reason, reason_code))

    line_total = money(sum(ln.total for ln in lines))
    allowance_total = money(sum(a.amount for a in allowances))
    charge_total = money(sum(c.amount for c in charges))
    tax_basis = money(line_total - allowance_total + charge_total)
    tax_total = money(sum(b.tax_amount for b in breakdown))
    grand_total = money(tax_basis + tax_total)
    prepaid = money(req.invoice.prepaid_amount)
    due = money(grand_total - prepaid)

    warnings: list[str] = []
    if any(b.taxable_amount < 0 for b in breakdown):
        warnings.append("negative taxable amount in a VAT group")

    return Totals(
        lines=lines,
        allowances=allowances,
        charges=charges,
        breakdown=breakdown,
        line_total=line_total,
        allowance_total=allowance_total,
        charge_total=charge_total,
        tax_basis_total=tax_basis,
        tax_total=tax_total,
        grand_total=grand_total,
        prepaid=prepaid,
        due=due,
        currency=req.invoice.currency,
        warnings=warnings,
    )
