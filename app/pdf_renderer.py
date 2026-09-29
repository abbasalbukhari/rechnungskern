"""HTML rendering (Jinja2) and PDF/A-3b generation (WeasyPrint)."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from functools import lru_cache

from jinja2 import Environment, FileSystemLoader, pass_context
from markupsafe import Markup, escape

from .calc import Totals
from .config import APP_DIR
from .i18n import labels, unit_label
from .schemas import InvoiceRequest

log = logging.getLogger("e-rechnung")

TEMPLATE_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£"}


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #


def fmt_number(value: Decimal, lang: str, places: int | None = None) -> str:
    if places is None:
        text = f"{value.normalize():f}"
    else:
        text = f"{value:.{places}f}"
    negative = text.startswith("-")
    text = text.lstrip("-")
    int_part, _, frac = text.partition(".")
    grouped = f"{int(int_part):,}"
    if lang == "de":
        grouped, dec = grouped.replace(",", "."), ","
    else:
        dec = "."
    out = grouped + (dec + frac if frac else "")
    return ("-" + out) if negative else out


def fmt_money(value: Decimal, currency: str, lang: str) -> str:
    number = fmt_number(value, lang, 2)
    symbol = CURRENCY_SYMBOLS.get(currency)
    if lang == "de" or not symbol:
        return f"{number} {symbol or currency}"
    if number.startswith("-"):
        return f"-{symbol}{number[1:]}"
    return f"{symbol}{number}"


def fmt_date(value: date | None, lang: str) -> str:
    if value is None:
        return ""
    return value.strftime("%d.%m.%Y") if lang == "de" else value.strftime("%d %b %Y")


def fmt_percent(value: Decimal, lang: str) -> str:
    return fmt_number(value, lang)


def nl2br(value: str | None) -> Markup:
    if not value:
        return Markup("")
    return Markup("<br>".join(str(escape(part)) for part in value.split("\n")))


# --------------------------------------------------------------------------- #
# Jinja environment
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    @pass_context
    def money(ctx, value):
        return fmt_money(value, ctx["currency"], ctx["lang"])

    @pass_context
    def number(ctx, value, places=None):
        return fmt_number(value, ctx["lang"], places)

    @pass_context
    def dt(ctx, value):
        return fmt_date(value, ctx["lang"])

    @pass_context
    def pct(ctx, value):
        return fmt_percent(value, ctx["lang"])

    @pass_context
    def unit(ctx, code):
        return unit_label(ctx["lang"], code)

    env.filters.update(money=money, number=number, date=dt, pct=pct, unit=unit, nl2br=nl2br)
    return env


@lru_cache(maxsize=1)
def _css() -> str:
    return (STATIC_DIR / "invoice.css").read_text(encoding="utf-8")


def render_html(req: InvoiceRequest, totals: Totals, logo: str | None) -> str:
    lang = req.language.value
    lb = labels(lang)
    title = req.layout.title or lb.get(f"doc_{req.invoice.type_code}", lb["doc_380"])
    means_label = lb.get(f"means_{req.payment.means_code}", req.payment.means_code)
    return _env().get_template("invoice.html").render(
        req=req,
        inv=req.invoice,
        seller=req.seller,
        buyer=req.buyer,
        pay=req.payment,
        layout=req.layout,
        totals=totals,
        t=lb,
        lang=lang,
        currency=req.invoice.currency,
        title=title,
        means_label=means_label,
        logo=logo if req.layout.show_logo else None,
        css=_css(),
    )


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #


def weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except Exception:  # pragma: no cover - depends on system libraries
        return False
    return True


def html_to_pdf(html: str) -> bytes:
    from weasyprint import HTML
    from weasyprint.urls import URLFetcher

    # Only inline data: URIs (the logo) may be loaded while rendering: no network, no files.
    fetcher = URLFetcher(allowed_protocols={"data"}, fail_on_errors=True)
    document = HTML(string=html, url_fetcher=fetcher)
    return document.write_pdf(pdf_variant="pdf/a-3b")
