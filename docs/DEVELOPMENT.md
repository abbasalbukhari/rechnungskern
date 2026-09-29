# Development guide

How the project is built, how to work on it on a new machine, and how to prepare it for GitHub.

## 1. What the service does

Rechnungskern turns invoice data (JSON) into EN 16931 e-invoices and validates existing ones:

| Output | Standard | How |
|---|---|---|
| Hybrid PDF | ZUGFeRD 2.x / Factur-X, PDF/A-3b, profile `EN16931` or `XRECHNUNG` | HTML template → WeasyPrint → PDF/A-3b → XML embedded with Factur-X XMP metadata |
| XML | CII (UN/CEFACT) – Factur-X EN 16931 or XRechnung 3.0 | drafthorse object model → serialised and XSD-validated |
| Validation report | Mustang validator (XSD + Schematron EN 16931 / XRechnung + PDF/A via veraPDF) | `java -jar Mustang-CLI.jar --action validate` as subprocess |

Three ways to use it: the REST API with `X-API-Key`, the key-less rate limited `/v1/public/*` endpoints, and the
browser pages (`/rechnung`, `/pruefung`) that call the public endpoints.

## 2. Architecture and request flow

```
POST /v1/invoices/pdf  (JSON)
   │
   ▼
schemas.py      Pydantic models + business rules (BR-xx): types, required fields per profile, tax categories
   │
   ▼
calc.py         Decimal arithmetic, ROUND_HALF_UP: line totals, allowances/charges, VAT breakdown, BT-106..BT-115
   │
   ├──▶ xml_builder.py   drafthorse Document → CII XML, validated against Factur-X EN16931 XSD
   │
   ├──▶ logo.py          base64 or URL → data URI (size/type checks, SSRF guard)
   │
   ├──▶ pdf_renderer.py  Jinja2 templates/invoice.html + static/invoice.css → HTML → WeasyPrint (pdf/a-3b)
   │
   └──▶ embed.py         drafthorse.pdf.attach_xml: embeds factur-x.xml, writes XMP (EN 16931 / XRECHNUNG)
   │
   ▼
Response  application/pdf, Content-Disposition: attachment
```

Nothing is persisted anywhere: no database, no temp files except the validator's temporary directory, which is
removed after each run.

### Modules (`app/`)

| File | Responsibility |
|---|---|
| `main.py` | FastAPI app, routes (`/v1/...` keyed, `/v1/public/...` key-less), validator subprocess, static mounts |
| `schemas.py` | Request model. Every field carries the EN 16931 business term (BT-xx) as a comment |
| `calc.py` | All amount calculations. Returns `Totals` (lines, allowances, charges, VAT breakdown, totals) |
| `xml_builder.py` | Maps request + `Totals` to CII XML with drafthorse; element order follows the XSD |
| `pdf_renderer.py` | Jinja environment, number/date/money filters (de/en), WeasyPrint call with a `data:`-only URL fetcher |
| `embed.py` | XML → PDF embedding + XMP level (`EN 16931` or `XRECHNUNG`) |
| `logo.py` | Logo decoding/fetching with limits |
| `i18n.py` | German/English labels for the printed invoice and unit codes |
| `auth.py` | `X-API-Key` dependency (constant-time comparison) |
| `ratelimit.py` | In-memory per-IP sliding window limiter for public endpoints |
| `summary.py` | Extracts number, seller, buyer, totals from CII/UBL XML (used by the validator page) |
| `site.py` | Public website routes: landing (de/en), editor, validator, about, Impressum, Datenschutz, sitemap, robots |
| `config.py` | All settings from environment variables (see `.env.example`) |
| `templates/invoice.html`, `static/invoice.css` | Printed invoice (CSS Paged Media: running header/footer, page counter) |
| `templates/site/*.html`, `static/site/*` | Website; `app.js` = invoice editor, `validate.js` = validator page |

### Design decisions worth knowing

- **drafthorse for XML and for embedding.** The `factur-x` library is only used for XSD checks and XML extraction
  because it cannot write the `XRECHNUNG` XMP conformance level; drafthorse can.
- **Amounts are strings in the API** (`"120.00"`), parsed to `Decimal` with at most 2 decimals. Percentages
  are rounded to cents per allowance *before* summing, which is what the BR-CO-* Schematron rules expect.
- **Document allowances need a VAT group.** If the invoice has exactly one category/rate the group is inferred,
  otherwise the request is rejected with 422 (the norm requires the allowance to belong to one VAT breakdown).
- **Exemption reasons** for categories E/AE/K/G/O have German/English defaults and VATEX codes (`schemas.py`).
- **Validation is not optional in tests.** `tests/test_mustang_validate.py` runs the real validator; negative
  tests exist to prove it fails tampered documents (BR-CO-15, BR-DE-15).
- **Public endpoints** are the same handler functions registered a second time under `/v1/public` with a
  rate-limit dependency instead of the API key dependency. Real client IPs come from Caddy via
  `--proxy-headers --forwarded-allow-ips=*` (safe because the API port is not published).
- **The browser editor keeps state in `localStorage`** (key `rechnungskern.invoice.v2`); the state shape is the
  editor's own, converted to the API body by `toRequest()` in `app.js`.

## 3. Setting up on a new machine

### Prerequisites

| Tool | Needed for | Notes |
|---|---|---|
| Python 3.11+ | unit tests, XML, API without PDF | on Windows WeasyPrint cannot import (no GTK) – PDF tests are skipped automatically |
| Docker Desktop / Docker Engine | PDF generation, full test suite, local server | the image contains Pango, fonts, Java 17 and the Mustang jar |
| Java 11+ (optional) | running Mustang locally without Docker | `tools/Mustang-CLI.jar` is downloaded, not committed |
| Node.js 18+ (optional) | `node --check` for the JS files, `examples/client/node-client.js` | no build step anywhere |
| Git Bash / any POSIX shell | `deploy/deploy.sh` | uses `ssh` and `tar` only |

### Steps

```bash
# 1. copy the project folder (or git clone once it is on GitHub); do NOT copy .venv, out/, .pytest_cache
cd e-rechnung

# 2. Python environment for fast local tests
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt      # Windows
# source .venv/bin/activate && pip install -r requirements-dev.txt   # Linux/macOS

# 3. optional: validator for local runs (59 MB)
mkdir -p tools && curl -L -o tools/Mustang-CLI.jar \
  https://github.com/ZUGFeRD/mustangproject/releases/download/core-2.26.0/Mustang-CLI-2.26.0.jar

# 4. local configuration
cp .env.example .env         # API_KEYS=dev-key-change-me, SERVE_CLIENT=true, ...

# 5. run the tests that work without Docker (XML, calc, API, site, Mustang on XML)
.venv/Scripts/python -m pytest

# 6. full suite (PDF + Mustang on PDF) and the dev server, both in Docker
docker compose build
docker compose run --rm api python -m pytest -o addopts=""
docker compose up                # http://localhost:8090  (host port 8090 → container 8000)
```

Dev compose mounts `app/`, `examples/`, `tests/`, `out/` into the container and runs uvicorn with `--reload`,
so Python changes reload automatically. Template/CSS/JS changes are picked up on the next request, except
`invoice.css`, which is cached in the process (`lru_cache`) – restart the container after editing it.

Test artefacts (PDF/XML) land in `out/` (git-ignored) – open them to eyeball layout changes.

### Useful commands

```bash
.venv/Scripts/python -m pytest tests/test_calc.py -q                  # only the amount rules
.venv/Scripts/python -m pytest -k mustang -o addopts=""               # validator tests with output
java -jar tools/Mustang-CLI.jar --action validate --source out/sample.pdf --no-notices
node --check app/static/site/app.js                                   # JS syntax
API_URL=http://localhost:8090 API_KEY=dev-key-change-me node examples/client/node-client.js tests/fixtures/sample_request.json
```

## 4. Making changes – checklists

**Adding a request field** (e.g. a new reference number):
1. `schemas.py` – add the field with its BT number and validation.
2. `xml_builder.py` – map it to the CII element (check element order in the Factur-X EN16931 XSD, drafthorse
   serialises fields in declaration order).
3. `templates/invoice.html` + `i18n.py` – show it on the PDF if it is visible information.
4. `static/site/app.js` – add it to `SECTIONS` and to `toRequest()` if the browser editor should offer it.
5. `tests/test_xml.py` – assert the XPath; run the Mustang tests.

**Changing amount logic:** only in `calc.py`; add a unit test in `tests/test_calc.py` with hand-calculated
expectations, then run `tests/test_mustang_validate.py` – Schematron catches inconsistent totals.

**Changing the PDF layout:** edit `invoice.html` / `invoice.css`, regenerate with the Docker test suite, read
`out/sample.pdf` and `out/sample_100_items.pdf` (multi-page behaviour), then re-run the Mustang PDF tests
(PDF/A-3 conformance can break through fonts or images).

**Website texts:** `templates/site/*.html` (German and English are separate blocks or files). Legal pages read
operator data from environment variables, never hard-code personal data in templates.

## 5. Testing overview

| File | Covers | Needs |
|---|---|---|
| `test_calc.py` | rounding, discounts, VAT groups, prepaid, schema rules | Python |
| `test_xml.py` | XML structure, XSD validity, XRechnung specifics, 100 items | Python |
| `test_api.py` | auth, XML/totals/html endpoints, logo handling, PDF endpoints | Python (PDF parts: Docker) |
| `test_site.py` | all website pages, SEO extras, public endpoints, rate limiter, summary | Python |
| `test_mustang_validate.py` | official validator on XML and PDF, both profiles | Java + jar (PDF parts: Docker) |

44 tests as of 2026-09-28; all pass inside Docker. Tests set `API_KEYS=test-key` themselves.

## 6. Known limitations and ideas

- No "Übertrag" (carry-over subtotal) at page breaks; needs a second rendering pass.
- Only one preceding invoice (BG-3) per document (drafthorse models it as a single element).
- CII syntax only; no UBL output (validation of UBL files works).
- The browser editor is covered by syntax checks and API tests, not by browser automation (Playwright would be
  the natural addition).
- No CI pipeline yet – a GitHub Actions workflow running `docker compose run --rm api python -m pytest` is the
  obvious first step after publishing.
- Rate limits are per process; with several API replicas they would need a shared store.

## 7. Preparing the GitHub repository

1. **Secrets audit** – `.env` (API key, operator data) and `docs/*.private.md` are git-ignored. `tests/fixtures`
   contain only fictional data. Search once before the first push: `grep -rn "212\.\|BEGIN OPENSSH\|API_KEYS=" --exclude-dir=.venv .`
2. **License** – MIT, see `LICENSE`.
3. **`.gitignore`** already excludes `.venv`, `out/`, `logs/`, `tools/*.jar`, `.env`, `__pycache__`.
4. **Set `PROJECT_REPO`** in the server `.env` afterwards so the about page links to the source code.
5. Suggested first commit: `git init && git add -A && git commit -m "Rechnungskern: EN 16931 e-invoice service"`.
