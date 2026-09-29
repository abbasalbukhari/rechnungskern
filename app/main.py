"""FastAPI application: EN 16931 e-invoice generation (Factur-X/ZUGFeRD PDF and XRechnung XML)."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from lxml import etree

from . import __version__
from .auth import require_api_key
from .calc import CalculationError, Totals, calculate
from .config import APP_DIR, ROOT_DIR, settings
from .embed import embed_xml
from .logo import LogoError, logo_data_uri
from .pdf_renderer import html_to_pdf, render_html, weasyprint_available
from .ratelimit import rate_limit
from .schemas import InvoiceRequest
from .site import PAGES
from .site import router as site_router
from .summary import summarize
from .xml_builder import build_xml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("e-rechnung")

CLIENT_DIR = ROOT_DIR / "examples" / "client"

DESCRIPTION = """
Generates **EN 16931** compliant electronic invoices from JSON:

* `POST /v1/invoices/pdf` – hybrid **PDF/A-3** with embedded CII XML (ZUGFeRD 2.x / Factur-X, profile EN 16931 or XRECHNUNG)
* `POST /v1/invoices/xml` – **XRechnung / Factur-X XML** only
* `POST /v1/invoices/html` – HTML preview of the PDF layout
* `POST /v1/invoices/totals` – computed amounts (net, VAT breakdown, gross, due)
* `POST /v1/validate` – validate a PDF or XML with the Mustang validator (if configured)

All `/v1/...` endpoints require the `X-API-Key` header (unless `API_KEYS` is empty).
The same operations exist under `/v1/public/...` **without a key but rate limited per IP**; they power the
browser pages `/rechnung` (create) and `/pruefung` (validate).
"""

app = FastAPI(
    title="E-Rechnung Service",
    version=__version__,
    description=DESCRIPTION,
    contact={"name": "E-Rechnung Service"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

SITE_PATHS = {path for path, _ in PAGES} | {"/sitemap.xml", "/robots.txt"}


@app.middleware("http")
async def canonical_host(request: Request, call_next):
    """One canonical host for search engines.

    On alias hosts (CANONICAL_REDIRECT_HOSTS, e.g. www and api) website pages answer with a permanent
    redirect to SITE_URL; everything else (API, docs, health) is served but marked noindex.
    """
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if settings.site_url and host in settings.canonical_redirect_hosts:
        path = request.url.path.rstrip("/") or "/"
        if request.method in ("GET", "HEAD") and path in SITE_PATHS:
            query = f"?{request.url.query}" if request.url.query else ""
            return RedirectResponse(f"{settings.site_url}{path}{query}", status_code=301)
        response = await call_next(request)
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response
    return await call_next(request)


app.include_router(site_router)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
if settings.serve_client and CLIENT_DIR.is_dir():
    app.mount("/client", StaticFiles(directory=str(CLIENT_DIR), html=True), name="client")

PDF_RESPONSES = {200: {"content": {"application/pdf": {}}, "description": "Hybrid PDF/A-3 (ZUGFeRD / Factur-X)"}}
XML_RESPONSES = {200: {"content": {"application/xml": {}}, "description": "CII XML (Factur-X EN 16931 / XRechnung)"}}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "invoice"


def _prepare(req: InvoiceRequest) -> tuple[Totals, bytes]:
    try:
        totals = calculate(req)
    except CalculationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        xml = build_xml(req, totals)
    except etree.XMLSyntaxError as exc:  # XSD violation => mapping bug, not a client error
        log.exception("generated XML failed XSD validation")
        raise HTTPException(status_code=500, detail=f"generated XML is not schema valid: {exc}") from exc
    return totals, xml


def _logo(req: InvoiceRequest) -> str | None:
    try:
        return logo_data_uri(req.seller)
    except LogoError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _require_pdf_support() -> None:
    if not weasyprint_available():
        raise HTTPException(
            status_code=503,
            detail="PDF rendering unavailable: WeasyPrint system libraries (Pango/GTK) are missing. "
            "Run the service in the provided Docker image.",
        )


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "pdf": weasyprint_available(),
        "validator": bool(settings.mustang_jar and Path(settings.mustang_jar).is_file() and shutil.which(settings.java_bin)),
        "auth": bool(settings.api_keys),
    }


@app.post(
    "/v1/invoices/xml",
    tags=["invoices"],
    dependencies=[Depends(require_api_key)],
    response_class=Response,
    responses=XML_RESPONSES,
)
def invoice_xml(req: InvoiceRequest) -> Response:
    _, xml = _prepare(req)
    name = _safe_filename(req.invoice.number)
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{name}.xml"'},
    )


@app.post(
    "/v1/invoices/pdf",
    tags=["invoices"],
    dependencies=[Depends(require_api_key)],
    response_class=Response,
    responses=PDF_RESPONSES,
)
def invoice_pdf(req: InvoiceRequest) -> Response:
    _require_pdf_support()
    totals, xml = _prepare(req)
    logo = _logo(req)
    html = render_html(req, totals, logo)
    pdf = html_to_pdf(html)
    pdf = embed_xml(pdf, xml, req)
    name = _safe_filename(req.invoice.number)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'},
    )


@app.post("/v1/invoices/html", tags=["invoices"], dependencies=[Depends(require_api_key)], response_class=HTMLResponse)
def invoice_html(req: InvoiceRequest) -> HTMLResponse:
    """HTML preview of the invoice layout (what the PDF is rendered from)."""
    totals, _ = _prepare(req)
    return HTMLResponse(render_html(req, totals, _logo(req)))


@app.post("/v1/invoices/totals", tags=["invoices"], dependencies=[Depends(require_api_key)])
def invoice_totals(req: InvoiceRequest) -> dict:
    """Computed amounts without generating a document (useful to preview totals in a client)."""
    totals, _ = _prepare(req)
    return {
        "currency": totals.currency,
        "lines": [
            {
                "position": ln.position,
                "name": ln.item.name,
                "quantity": str(ln.quantity),
                "net_unit_price": str(ln.net_unit_price),
                "gross_unit_price": str(ln.gross_unit_price) if ln.gross_unit_price is not None else None,
                "allowances": [str(a.amount) for a in ln.allowances],
                "charges": [str(c.amount) for c in ln.charges],
                "total": str(ln.total),
            }
            for ln in totals.lines
        ],
        "allowances": [{"amount": str(a.amount), "tax_category": a.tax_category.value, "tax_rate": str(a.tax_rate)} for a in totals.allowances],
        "charges": [{"amount": str(c.amount), "tax_category": c.tax_category.value, "tax_rate": str(c.tax_rate)} for c in totals.charges],
        "vat_breakdown": [
            {
                "category": b.category.value,
                "rate": str(b.rate),
                "taxable_amount": str(b.taxable_amount),
                "tax_amount": str(b.tax_amount),
                "exemption_reason": b.exemption_reason,
            }
            for b in totals.breakdown
        ],
        "line_total": str(totals.line_total),
        "allowance_total": str(totals.allowance_total),
        "charge_total": str(totals.charge_total),
        "tax_basis_total": str(totals.tax_basis_total),
        "tax_total": str(totals.tax_total),
        "grand_total": str(totals.grand_total),
        "prepaid": str(totals.prepaid),
        "due": str(totals.due),
        "warnings": totals.warnings,
    }


# --------------------------------------------------------------------------- #
# validation with Mustang (optional)
# --------------------------------------------------------------------------- #


def run_mustang(data: bytes, suffix: str) -> dict:
    jar = Path(settings.mustang_jar) if settings.mustang_jar else None
    if not jar or not jar.is_file() or not shutil.which(settings.java_bin):
        raise HTTPException(status_code=503, detail="validator not configured (MUSTANG_JAR / java missing)")
    with tempfile.TemporaryDirectory(prefix="mustang-") as td:
        src = Path(td) / f"input{suffix}"
        src.write_bytes(data)
        cmd = [settings.java_bin, "-jar", str(jar), "--action", "validate", "--source", str(src), "--no-notices"]
        try:
            proc = subprocess.run(cmd, cwd=td, capture_output=True, timeout=180)
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=504, detail="validator timed out") from exc
    stdout = proc.stdout.decode("utf-8", "replace")
    start = stdout.find("<validation")
    if start < 0:
        raise HTTPException(status_code=500, detail=f"validator produced no report: {proc.stderr.decode('utf-8', 'replace')[-2000:]}")
    try:
        root = etree.fromstring(stdout[start:].encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        raise HTTPException(status_code=500, detail=f"validator report unreadable: {exc}") from exc
    summary = root.find("summary")
    messages = [
        {
            "level": el.tag,
            "type": el.get("type"),
            "location": el.get("location"),
            "criterion": el.get("criterion"),
            "message": (el.text or "").strip(),
        }
        for el in root.iter("error", "warning", "notice")
    ]
    return {
        "valid": summary is not None and summary.get("status") == "valid",
        "status": summary.get("status") if summary is not None else "unknown",
        "exit_code": proc.returncode,
        "messages": messages,
        "report": stdout[start:],
    }


@app.post("/v1/validate", tags=["validation"], dependencies=[Depends(require_api_key)])
def validate(file: UploadFile = File(...)) -> JSONResponse:
    """Validate a hybrid PDF or an XML with the Mustang validator (PDF/A, XSD and Schematron).

    Sync endpoint on purpose: the validator is a blocking subprocess and must not stall the event loop.
    """
    data = file.file.read()
    name = (file.filename or "").lower()
    if data.startswith(b"%PDF"):
        suffix = ".pdf"
    elif name.endswith(".xml") or data.lstrip().startswith(b"<"):
        suffix = ".xml"
    else:
        raise HTTPException(status_code=422, detail="upload a PDF or an XML file")
    result = run_mustang(data, suffix)
    result["filename"] = file.filename
    result["summary"] = summarize(data)
    return JSONResponse(result)


# --------------------------------------------------------------------------- #
# public endpoints (no API key, rate limited per IP) for the browser pages
# --------------------------------------------------------------------------- #

generate_limit = rate_limit(settings.public_rate_limit, 3600)
validate_limit = rate_limit(settings.public_validate_limit, 3600)

if settings.public_enabled:
    public = APIRouter(prefix="/v1/public", tags=["public (no API key, rate limited)"])
    public.add_api_route("/invoices/pdf", invoice_pdf, methods=["POST"], dependencies=[Depends(generate_limit)], response_class=Response, responses=PDF_RESPONSES)
    public.add_api_route("/invoices/xml", invoice_xml, methods=["POST"], dependencies=[Depends(generate_limit)], response_class=Response, responses=XML_RESPONSES)
    public.add_api_route("/invoices/html", invoice_html, methods=["POST"], dependencies=[Depends(generate_limit)], response_class=HTMLResponse)
    public.add_api_route("/invoices/totals", invoice_totals, methods=["POST"])
    public.add_api_route("/validate", validate, methods=["POST"], dependencies=[Depends(validate_limit)])
    app.include_router(public)
