"""Request models for the e-invoice API.

Every request is validated here first (structure + business rules that can be
checked without computing totals). Rules that depend on computed amounts live
in ``calc.py``. Field names follow the EN 16931 business terms (BT-xx) where a
mapping is useful; comments name the BT so the XML mapping is traceable.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

# --------------------------------------------------------------------------- #
# Enumerations / constants
# --------------------------------------------------------------------------- #


class Profile(str, Enum):
    EN16931 = "EN16931"  # ZUGFeRD / Factur-X profile EN 16931 ("COMFORT")
    XRECHNUNG = "XRECHNUNG"  # German public sector (XRechnung 3.0, CII syntax)


class Language(str, Enum):
    de = "de"
    en = "en"


class TaxCategory(str, Enum):
    """UNTDID 5305 subset used by EN 16931 (BT-151 / BT-118)."""

    S = "S"  # Standard rate
    Z = "Z"  # Zero rated goods
    E = "E"  # Exempt from tax
    AE = "AE"  # VAT reverse charge
    K = "K"  # Intra-community supply
    G = "G"  # Export outside the EU
    O = "O"  # Services outside scope of tax


# Document type codes (UNTDID 1001). XRechnung restricts to this list (BR-DE-17).
DOCUMENT_TYPE_CODES = {"326", "380", "381", "384", "389", "875", "876", "877"}

# Codes in UNTDID 4461 that XRechnung accepts (BR-DE-1 / BR-DE-13 need one of them).
PAYMENT_MEANS_CODES = {
    "1",  # Instrument not defined
    "10",  # In cash
    "20",  # Cheque
    "30",  # Credit transfer
    "42",  # Payment to bank account
    "48",  # Bank card
    "49",  # Direct debit
    "54",  # Credit card
    "55",  # Debit card
    "57",  # Standing agreement
    "58",  # SEPA credit transfer
    "59",  # SEPA direct debit
    "68",  # Online payment service
    "97",  # Clearing between partners
    "ZZZ",  # Mutually defined
}

# Default exemption reason texts / VATEX codes per category (BT-120 / BT-121).
DEFAULT_EXEMPTION_TEXT = {
    TaxCategory.E: {"de": "Steuerbefreit", "en": "Exempt from VAT"},
    TaxCategory.AE: {
        "de": "Steuerschuldnerschaft des Leistungsempfängers (Reverse Charge)",
        "en": "Reverse charge – VAT to be paid by the recipient",
    },
    TaxCategory.K: {
        "de": "Steuerfreie innergemeinschaftliche Lieferung",
        "en": "Tax-exempt intra-community supply",
    },
    TaxCategory.G: {
        "de": "Steuerfreie Ausfuhrlieferung",
        "en": "Tax-exempt export outside the EU",
    },
    TaxCategory.O: {
        "de": "Nicht steuerbarer Umsatz",
        "en": "Not subject to VAT",
    },
}
DEFAULT_EXEMPTION_CODE = {
    TaxCategory.AE: "VATEX-EU-AE",
    TaxCategory.K: "VATEX-EU-IC",
    TaxCategory.G: "VATEX-EU-G",
    TaxCategory.O: "VATEX-EU-O",
}

# --------------------------------------------------------------------------- #
# Reusable field types
# --------------------------------------------------------------------------- #

Str = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
ShortStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
CountryCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z]{2}$")]
CurrencyCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z]{3}$")]
HexColor = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^#[0-9a-fA-F]{6}$")]
Money = Annotated[Decimal, Field(decimal_places=2, max_digits=17)]
Quantity = Annotated[Decimal, Field(decimal_places=4, max_digits=19)]
Percent = Annotated[Decimal, Field(ge=0, le=100, decimal_places=2, max_digits=5)]

_IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
# Parties
# --------------------------------------------------------------------------- #


class Address(_Model):
    line1: ShortStr  # BT-35 / BT-50
    line2: Optional[ShortStr] = None
    line3: Optional[ShortStr] = None
    postcode: ShortStr  # BT-38 / BT-53
    city: ShortStr  # BT-37 / BT-52
    country: CountryCode  # BT-40 / BT-55 (ISO 3166-1 alpha-2)
    subdivision: Optional[ShortStr] = None  # BT-39 / BT-54


class Contact(_Model):
    name: Optional[ShortStr] = None  # BT-41 / BT-56
    department: Optional[ShortStr] = None
    phone: Optional[ShortStr] = None  # BT-42 / BT-57
    email: Optional[ShortStr] = None  # BT-43 / BT-58

    @field_validator("email")
    @classmethod
    def _email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _EMAIL_RE.match(v):
            raise ValueError("invalid e-mail address")
        return v


class ElectronicAddress(_Model):
    """BT-34 / BT-49 with scheme from EAS code list (EM = e-mail, 0204 = Leitweg-ID, ...)."""

    scheme: ShortStr = "EM"
    id: ShortStr


class Bank(_Model):
    iban: ShortStr  # BT-84
    bic: Optional[ShortStr] = None  # BT-86
    account_holder: Optional[ShortStr] = None  # BT-85
    bank_name: Optional[ShortStr] = None  # PDF only

    @field_validator("iban")
    @classmethod
    def _iban(cls, v: str) -> str:
        v = v.replace(" ", "").upper()
        if not _IBAN_RE.match(v):
            raise ValueError("invalid IBAN format")
        return v


class Logo(_Model):
    media_type: Literal["image/png", "image/jpeg", "image/svg+xml"]
    data_base64: Annotated[str, StringConstraints(min_length=4)]


class Seller(_Model):
    name: ShortStr  # BT-27
    trading_name: Optional[ShortStr] = None  # BT-28
    address: Address
    vat_id: Optional[ShortStr] = None  # BT-31
    tax_number: Optional[ShortStr] = None  # BT-32 (German Steuernummer)
    legal_id: Optional[ShortStr] = None  # BT-30 (e.g. Handelsregister number)
    legal_info: Optional[LongText] = None  # BT-33 additional legal information
    contact: Optional[Contact] = None  # BG-6
    electronic_address: Optional[ElectronicAddress] = None  # BT-34
    bank: Optional[Bank] = None  # BG-17
    logo: Optional[Logo] = None
    logo_url: Optional[Annotated[str, StringConstraints(pattern=r"^https?://")]] = None

    @field_validator("vat_id")
    @classmethod
    def _vat(cls, v: Optional[str]) -> Optional[str]:
        return v.replace(" ", "").upper() if v else v

    @model_validator(mode="after")
    def _rules(self) -> "Seller":
        if not self.vat_id and not self.tax_number:
            raise ValueError("seller needs vat_id or tax_number (BR-CO-26)")
        if self.logo and self.logo_url:
            raise ValueError("provide either seller.logo or seller.logo_url, not both")
        return self


class Buyer(_Model):
    name: ShortStr  # BT-44
    trading_name: Optional[ShortStr] = None  # BT-45
    customer_id: Optional[ShortStr] = None  # BT-46
    legal_id: Optional[ShortStr] = None  # BT-47
    address: Address
    vat_id: Optional[ShortStr] = None  # BT-48
    contact: Optional[Contact] = None  # BG-9
    electronic_address: Optional[ElectronicAddress] = None  # BT-49

    @field_validator("vat_id")
    @classmethod
    def _vat(cls, v: Optional[str]) -> Optional[str]:
        return v.replace(" ", "").upper() if v else v


# --------------------------------------------------------------------------- #
# Allowances / charges
# --------------------------------------------------------------------------- #


class AllowanceCharge(_Model):
    """Line level allowance (BG-27) or charge (BG-28).

    Exactly one of ``amount`` or ``percent`` must be given. ``percent`` is applied
    to the line net amount before allowances/charges (BT-137 base amount).
    """

    amount: Optional[Money] = None  # BT-136 / BT-141
    percent: Optional[Percent] = None  # BT-138 / BT-143
    reason: Optional[ShortStr] = None  # BT-139 / BT-144
    reason_code: Optional[ShortStr] = None  # BT-140 (UNTDID 5189) / BT-145 (UNTDID 7161)

    @model_validator(mode="after")
    def _one_of(self) -> "AllowanceCharge":
        if (self.amount is None) == (self.percent is None):
            raise ValueError("give exactly one of amount or percent")
        if self.amount is not None and self.amount <= 0:
            raise ValueError("amount must be positive")
        if self.percent is not None and self.percent <= 0:
            raise ValueError("percent must be positive")
        return self


class DocumentAllowanceCharge(AllowanceCharge):
    """Document level allowance (BG-20) or charge (BG-21).

    Needs a VAT category and rate (BT-95/96, BT-102/103). If omitted and all
    items share one category/rate, it is inferred; otherwise the request is
    rejected. ``percent`` is applied to the sum of line net amounts in that
    category/rate group.
    """

    tax_category: Optional[TaxCategory] = None
    tax_rate: Optional[Percent] = None


# --------------------------------------------------------------------------- #
# Items
# --------------------------------------------------------------------------- #


class Item(_Model):
    name: ShortStr  # BT-153
    description: Optional[LongText] = None  # BT-154
    seller_item_id: Optional[ShortStr] = None  # BT-155
    buyer_item_id: Optional[ShortStr] = None  # BT-156
    quantity: Quantity  # BT-129
    unit: ShortStr = "C62"  # BT-130 (UN/ECE Rec 20: C62 piece, HUR hour, DAY, KGM, MTR, LTR, ...)
    unit_price: Money  # BT-146 net price, or BT-148 gross price when price_discount is set
    price_discount: Optional[Money] = None  # BT-147 discount per unit on the gross price
    price_basis_quantity: Quantity = Decimal("1")  # BT-149
    tax_category: TaxCategory = TaxCategory.S  # BT-151
    tax_rate: Percent = Decimal("19")  # BT-152
    tax_exemption_reason: Optional[ShortStr] = None  # BT-120 text (categories != S/Z)
    tax_exemption_reason_code: Optional[ShortStr] = None  # BT-121 (VATEX code list)
    allowances: list[AllowanceCharge] = Field(default_factory=list)  # BG-27
    charges: list[AllowanceCharge] = Field(default_factory=list)  # BG-28
    note: Optional[LongText] = None  # BT-127

    @model_validator(mode="after")
    def _rules(self) -> "Item":
        if self.quantity == 0:
            raise ValueError("quantity must not be 0")
        if self.price_basis_quantity <= 0:
            raise ValueError("price_basis_quantity must be > 0")
        if self.price_discount is not None:
            if self.price_discount < 0:
                raise ValueError("price_discount must be >= 0")
            if self.price_discount > self.unit_price:
                raise ValueError("price_discount must not exceed unit_price (BR-28)")
        if self.unit_price < 0:
            raise ValueError("unit_price must not be negative (BR-27)")
        if self.tax_category == TaxCategory.S and self.tax_rate <= 0:
            raise ValueError("tax_rate must be > 0 for category S (BR-S-5)")
        if self.tax_category != TaxCategory.S and self.tax_rate != 0:
            raise ValueError(f"tax_rate must be 0 for category {self.tax_category.value}")
        return self


# --------------------------------------------------------------------------- #
# Invoice header, payment, layout
# --------------------------------------------------------------------------- #


class Note(_Model):
    text: LongText  # BT-22
    subject_code: Optional[ShortStr] = None  # BT-21 (UNTDID 4451, e.g. AAI, REG, ABL)


class PrecedingInvoice(_Model):
    number: ShortStr  # BT-25
    issue_date: Optional[date] = None  # BT-26


class Invoice(_Model):
    number: ShortStr  # BT-1
    type_code: ShortStr = "380"  # BT-3
    issue_date: date  # BT-2
    due_date: Optional[date] = None  # BT-9
    delivery_date: Optional[date] = None  # BT-72
    period_start: Optional[date] = None  # BT-73
    period_end: Optional[date] = None  # BT-74
    currency: CurrencyCode = "EUR"  # BT-5
    buyer_reference: Optional[ShortStr] = None  # BT-10 (Leitweg-ID for XRechnung)
    order_reference: Optional[ShortStr] = None  # BT-13
    seller_order_reference: Optional[ShortStr] = None  # BT-14
    contract_reference: Optional[ShortStr] = None  # BT-12
    project_reference: Optional[ShortStr] = None  # BT-11
    payment_reference: Optional[ShortStr] = None  # BT-83 (Verwendungszweck)
    preceding_invoices: list[PrecedingInvoice] = Field(default_factory=list, max_length=1)  # BG-3
    prepaid_amount: Money = Decimal("0")  # BT-113
    notes: list[Note] = Field(default_factory=list)  # BG-1

    @field_validator("type_code")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in DOCUMENT_TYPE_CODES:
            raise ValueError(f"type_code must be one of {sorted(DOCUMENT_TYPE_CODES)}")
        return v

    @model_validator(mode="after")
    def _rules(self) -> "Invoice":
        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("period_start and period_end must be given together (BR-CO-19)")
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("period_end must not be before period_start (BR-29)")
        if self.prepaid_amount < 0:
            raise ValueError("prepaid_amount must not be negative")
        if self.type_code == "384" and not self.preceding_invoices:
            raise ValueError("corrected invoice (384) needs preceding_invoices (BR-DE-26)")
        return self


class Payment(_Model):
    means_code: ShortStr = "58"  # BT-81 (UNTDID 4461)
    means_text: Optional[ShortStr] = None  # BT-82
    terms_text: Optional[LongText] = None  # BT-20
    mandate_reference: Optional[ShortStr] = None  # BT-89 (direct debit)
    creditor_id: Optional[ShortStr] = None  # BT-90 (direct debit)

    @field_validator("means_code")
    @classmethod
    def _means(cls, v: str) -> str:
        if v not in PAYMENT_MEANS_CODES:
            raise ValueError(f"means_code must be one of {sorted(PAYMENT_MEANS_CODES)}")
        return v


class Layout(_Model):
    """Texts and styling that only affect the PDF."""

    header_text: Optional[LongText] = None
    intro_text: Optional[LongText] = None
    closing_text: Optional[LongText] = None
    footer_text: Optional[LongText] = None
    footer_columns: list[LongText] = Field(default_factory=list, max_length=3)
    accent_color: HexColor = "#1f3a5f"
    show_logo: bool = True
    title: Optional[ShortStr] = None  # overrides the document title (e.g. "Rechnung")


# --------------------------------------------------------------------------- #
# Root request
# --------------------------------------------------------------------------- #


class InvoiceRequest(_Model):
    profile: Profile = Profile.EN16931
    language: Language = Language.de
    invoice: Invoice
    seller: Seller
    buyer: Buyer
    items: list[Item] = Field(min_length=1, max_length=2000)
    allowances: list[DocumentAllowanceCharge] = Field(default_factory=list)  # BG-20
    charges: list[DocumentAllowanceCharge] = Field(default_factory=list)  # BG-21
    payment: Payment = Field(default_factory=Payment)
    layout: Layout = Field(default_factory=Layout)

    @model_validator(mode="after")
    def _rules(self) -> "InvoiceRequest":
        errors: list[str] = []
        cats = {i.tax_category for i in self.items}

        if self.payment.means_code in {"58", "30", "42"} and not self.seller.bank:
            errors.append("payment means credit transfer needs seller.bank (BR-DE-23 / BG-17)")
        if self.payment.means_code in {"59", "49"}:
            if not self.payment.mandate_reference or not self.payment.creditor_id:
                errors.append("direct debit needs payment.mandate_reference and payment.creditor_id (BR-DE-25)")

        if TaxCategory.AE in cats or TaxCategory.K in cats:
            if not self.buyer.vat_id and not self.buyer.legal_id:
                errors.append("reverse charge / intra-community supply needs buyer.vat_id (BR-AE-2 / BR-IC-2)")
            if not self.seller.vat_id:
                errors.append("reverse charge / intra-community supply needs seller.vat_id")
        if TaxCategory.K in cats and not (self.invoice.delivery_date or self.invoice.period_start):
            errors.append("intra-community supply needs invoice.delivery_date or period (BR-IC-11)")

        if self.profile == Profile.XRECHNUNG:
            if not self.invoice.buyer_reference:
                errors.append("XRechnung needs invoice.buyer_reference (Leitweg-ID, BR-DE-15)")
            c = self.seller.contact
            if not c or not (c.name and c.phone and c.email):
                errors.append("XRechnung needs seller.contact with name, phone and email (BR-DE-2/5/6/7)")
            if not self.seller.electronic_address:
                errors.append("XRechnung needs seller.electronic_address (BT-34)")
            if not self.buyer.electronic_address:
                errors.append("XRechnung needs buyer.electronic_address (BT-49)")
            if c and c.phone and len(re.sub(r"\D", "", c.phone)) < 3:
                errors.append("seller contact phone needs at least 3 digits (BR-DE-27)")

        if errors:
            raise ValueError("; ".join(errors))
        return self
