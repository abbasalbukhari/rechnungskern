"""Public website: landing page (DE/EN), invoice creator, validator, Impressum, Datenschutz."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from .config import settings
from .pdf_renderer import _env

router = APIRouter(include_in_schema=False)

PAGES = [
    ("/", "de"), ("/en", "en"),
    ("/rechnung", "de"), ("/en/invoice", "en"),
    ("/pruefung", "de"), ("/en/validate", "en"),
    ("/ueber", "de"), ("/en/about", "en"),
    ("/impressum", "de"), ("/legal-notice", "en"),
    ("/datenschutz", "de"), ("/privacy", "en"),
]


def _base_url(request: Request) -> str:
    return settings.site_url or str(request.base_url).rstrip("/")


def _render(template: str, request: Request, lang: str, **extra) -> HTMLResponse:
    html = _env().get_template(f"site/{template}").render(
        s=settings,
        lang=lang,
        base_url=_base_url(request),
        path=request.url.path,
        year=date.today().year,
        **extra,
    )
    return HTMLResponse(html)


@router.get("/", response_class=HTMLResponse)
def home_de(request: Request) -> HTMLResponse:
    return _render("index_de.html", request, "de")


@router.get("/en", response_class=HTMLResponse)
def home_en(request: Request) -> HTMLResponse:
    return _render("index_en.html", request, "en")


@router.get("/rechnung", response_class=HTMLResponse)
def invoice_app_de(request: Request) -> HTMLResponse:
    return _render("invoice_app.html", request, "de")


@router.get("/en/invoice", response_class=HTMLResponse)
def invoice_app_en(request: Request) -> HTMLResponse:
    return _render("invoice_app.html", request, "en")


@router.get("/pruefung", response_class=HTMLResponse)
def validate_app_de(request: Request) -> HTMLResponse:
    return _render("validate_app.html", request, "de")


@router.get("/en/validate", response_class=HTMLResponse)
def validate_app_en(request: Request) -> HTMLResponse:
    return _render("validate_app.html", request, "en")


@router.get("/ueber", response_class=HTMLResponse)
def about_de(request: Request) -> HTMLResponse:
    return _render("about.html", request, "de")


@router.get("/en/about", response_class=HTMLResponse)
def about_en(request: Request) -> HTMLResponse:
    return _render("about.html", request, "en")


@router.get("/impressum", response_class=HTMLResponse)
def impressum(request: Request) -> HTMLResponse:
    return _render("impressum.html", request, "de")


@router.get("/legal-notice", response_class=HTMLResponse)
def legal_notice(request: Request) -> HTMLResponse:
    return _render("impressum.html", request, "en")


@router.get("/datenschutz", response_class=HTMLResponse)
def datenschutz(request: Request) -> HTMLResponse:
    return _render("datenschutz.html", request, "de")


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request) -> HTMLResponse:
    return _render("datenschutz.html", request, "en")


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request) -> str:
    return f"User-agent: *\nAllow: /\nDisallow: /client/\nDisallow: /v1/\nSitemap: {_base_url(request)}/sitemap.xml\n"


@router.get("/sitemap.xml")
def sitemap(request: Request) -> Response:
    base = _base_url(request)
    today = date.today().isoformat()
    items = "".join(
        f"<url><loc>{base}{path}</loc><lastmod>{today}</lastmod>"
        f"<xhtml:link rel=\"alternate\" hreflang=\"{lang}\" href=\"{base}{path}\"/></url>"
        for path, lang in PAGES
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">'
        f"{items}</urlset>"
    )
    return Response(content=xml, media_type="application/xml")
