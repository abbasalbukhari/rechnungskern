# Rechnungskern – E-Rechnung Service

HTTP service and website that turn invoice data (JSON) into **EN 16931** compliant electronic invoices
(ZUGFeRD / Factur-X PDF/A-3, XRechnung XML) and validate existing ones. Live at https://rechnungskern.de.

Documentation: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) (architecture, local setup, checklists, GitHub preparation)
and [docs/SERVER.md](docs/SERVER.md) (production runbook).

Endpoints:

| Endpoint | Returns |
|---|---|
| `POST /v1/invoices/pdf` | Hybrid **PDF/A-3** with embedded CII XML (**ZUGFeRD 2.x / Factur-X**), profile `EN16931` or `XRECHNUNG` |
| `POST /v1/invoices/xml` | **XRechnung 3.0** (CII) or Factur-X EN 16931 XML only |
| `POST /v1/invoices/html` | HTML preview of the PDF layout |
| `POST /v1/invoices/totals` | Computed amounts (net, VAT breakdown, gross, amount due) |
| `POST /v1/validate` | Validation report from the official **Mustang** validator (PDF/A, XSD, Schematron) |
| `GET /health` | Status |
| `GET /`, `/en` | Landing page (German / English, SEO: hreflang, JSON-LD, sitemap) |
| `GET /rechnung`, `/en/invoice` | Browser invoice editor – remembers entries in the browser's local storage |
| `GET /pruefung`, `/en/validate` | Browser validator (drag & drop PDF/XML, Mustang report) |
| `GET /impressum`, `/datenschutz` (`/legal-notice`, `/privacy`) | Legal pages, operator data from `.env` (`OPERATOR_*`, `CONTACT_EMAIL`) |
| `POST /v1/public/...` | Same operations as `/v1/...` **without API key**, rate limited per IP (`PUBLIC_RATE_LIMIT`, `PUBLIC_VALIDATE_LIMIT`); used by the browser pages |

Interactive API docs: `http://localhost:8090/docs` · Browser test client: `http://localhost:8090/client/`

Stack: Python 3.12, FastAPI, [drafthorse](https://github.com/pretix/python-drafthorse) (CII XML, XSD validated),
[WeasyPrint](https://weasyprint.org/) (HTML → PDF/A-3b), [Mustang](https://www.mustangproject.org/) (validation).

## Quick start (Docker)

```bash
cp .env.example .env          # set API_KEYS
docker compose up --build     # http://localhost:8090
```

```bash
curl -s -H "X-API-Key: dev-key-change-me" -H "Content-Type: application/json" \
     -d @tests/fixtures/sample_request.json \
     http://localhost:8090/v1/invoices/pdf -o out/RE-2026-00042.pdf

curl -s -H "X-API-Key: dev-key-change-me" -H "Content-Type: application/json" \
     -d @tests/fixtures/sample_xrechnung.json \
     http://localhost:8090/v1/invoices/xml -o out/RE-2026-00043.xml

# validate the result with Mustang
curl -s -H "X-API-Key: dev-key-change-me" -F file=@out/RE-2026-00042.pdf http://localhost:8090/v1/validate
```

Node.js example: `node examples/client/node-client.js tests/fixtures/sample_request.json [logo.png]`

## Request body

Same JSON for every endpoint. Amounts are **strings with at most 2 decimals**, quantities up to 4 decimals.
The service computes all totals itself (ROUND_HALF_UP), so a client never has to send sums.

```jsonc
{
  "profile": "EN16931",            // or "XRECHNUNG" (German public sector)
  "language": "de",                // "de" | "en" – language of the printed PDF
  "invoice": {
    "number": "RE-2026-00042",     // BT-1
    "type_code": "380",            // 380 invoice, 381 credit note, 384 corrected invoice, 326 partial, ...
    "issue_date": "2026-09-28",
    "due_date": "2026-10-28",
    "delivery_date": "2026-09-25", // or period_start / period_end
    "currency": "EUR",
    "buyer_reference": "04011000-12345-03",   // Leitweg-ID, mandatory for XRECHNUNG
    "order_reference": "PO-7781",
    "payment_reference": "RE-2026-00042",
    "prepaid_amount": "0.00",
    "notes": [ { "text": "free text, printed and written to the XML (BG-1)", "subject_code": "AAI" } ]
  },
  "seller": {
    "name": "Muster Technik GmbH",
    "address": { "line1": "Industriestraße 12", "postcode": "70565", "city": "Stuttgart", "country": "DE" },
    "vat_id": "DE123456789",       // vat_id or tax_number required
    "tax_number": "99/123/45678",
    "legal_id": "HRB 123456",
    "contact": { "name": "Max Mustermann", "phone": "+49 711 1234560", "email": "rechnung@example.com" },
    "electronic_address": { "scheme": "EM", "id": "rechnung@example.com" },
    "bank": { "iban": "DE89370400440532013000", "bic": "COBADEFFXXX", "account_holder": "Muster Technik GmbH" },
    "logo": { "media_type": "image/png", "data_base64": "iVBORw0..." },   // or "logo_url": "https://..."
  },
  "buyer": {
    "name": "Beispiel Kunde AG",
    "customer_id": "K-10023",
    "address": { "line1": "Musterweg 5", "postcode": "80331", "city": "München", "country": "DE" },
    "vat_id": "DE987654321",
    "electronic_address": { "scheme": "EM", "id": "einkauf@kunde.example" }
  },
  "items": [
    {
      "name": "Software-Lizenz Pro",
      "description": "Jahreslizenz, 5 Benutzer",
      "seller_item_id": "LIC-PRO-5",
      "quantity": "2",
      "unit": "C62",               // UN/ECE Rec. 20: C62 piece, HUR hour, DAY, KGM, MTR, LTR, LS lump sum ...
      "unit_price": "500.00",      // net price – or gross price when price_discount is given
      "price_discount": "50.00",   // optional discount per unit (BT-147) -> net price 450.00
      "tax_category": "S",         // S, Z, E, AE (reverse charge), K (intra-EU), G (export), O
      "tax_rate": "19",
      "allowances": [ { "percent": "10", "reason": "Treuerabatt", "reason_code": "95" } ],
      "charges":    [ { "amount": "4.50", "reason": "Expressversand" } ]
    }
  ],
  "allowances": [ { "percent": "3", "reason": "Skonto-Vorabzug", "tax_category": "S", "tax_rate": "19" } ],
  "charges":    [ { "amount": "12.00", "reason": "Verpackung", "tax_category": "S", "tax_rate": "19" } ],
  "payment": { "means_code": "58", "terms_text": "Zahlbar innerhalb von 30 Tagen ohne Abzug." },
  "layout": {
    "header_text": "shown top right on page 1",
    "intro_text": "text before the item table",
    "closing_text": "text after payment details",
    "footer_columns": [ "col 1", "col 2", "col 3" ],   // or "footer_text"
    "accent_color": "#1f3a5f",
    "title": "Rechnung"            // optional override of the document title
  }
}
```

### Which texts end up where

| Field | PDF | XML |
|---|---|---|
| `layout.header_text`, `intro_text`, `closing_text`, `footer_text` / `footer_columns` | yes | no |
| `invoice.notes[]` | yes | BG-1 `IncludedNote` |
| `payment.terms_text` | yes | BT-20 payment terms |
| `items[].tax_exemption_reason` (categories E, AE, K, G, O; default texts exist) | yes | BT-120 |

### Discounts and surcharges

| Level | Field | XML |
|---|---|---|
| Unit price discount | `items[].price_discount` | BT-147 / BT-148 (gross price + allowance + net price) |
| Line allowance / charge | `items[].allowances[]`, `items[].charges[]` (`amount` or `percent`) | BG-27 / BG-28 |
| Document allowance / charge | `allowances[]`, `charges[]` (need `tax_category` + `tax_rate`, inferred if the invoice has only one VAT group) | BG-20 / BG-21 |

Line net = net price × quantity − line allowances + line charges. Document allowances reduce the taxable
amount of their VAT group before VAT is calculated. Percentages are rounded to cents per allowance.

### Multi-page invoices

Page 1 has the full letter head; pages 2+ repeat a compact header (seller, invoice number, date). The footer
(with `Seite x von y`) and the table header repeat on every page. Rows are never split across pages.

## Validation

The XML is validated against the Factur-X EN 16931 XSD on every request. For full compliance checks
(Schematron rules EN 16931 + XRechnung, PDF/A-3 + XMP) the Docker image ships the Mustang validator:

```bash
docker compose exec api java -jar /opt/mustang/Mustang-CLI.jar --action validate --source out/RE-2026-00042.pdf
```

or `POST /v1/validate` with the file as multipart upload (`file`).

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `API_KEYS` | *(empty = auth disabled)* | Comma separated keys accepted in `X-API-Key` |
| `CORS_ORIGINS` | `*` | Allowed browser origins |
| `MAX_LOGO_BYTES` | `2097152` | Logo size limit |
| `ALLOW_LOGO_URL` | `true` | Allow the server to download `seller.logo_url` (private/local addresses are always refused) |
| `MUSTANG_JAR`, `JAVA_BIN` | set in image | Enables `/v1/validate` |
| `SERVE_CLIENT` | `true` | Serve `examples/client` at `/client/` |
| `PDF_PRODUCER` | `e-rechnung service` | PDF `Creator` metadata |

Put the service behind a reverse proxy with TLS and a request size limit in production.

## Development

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # Windows
.venv/Scripts/python -m pytest                                              # unit + XML tests
```

WeasyPrint needs Pango/GTK; on Windows the PDF tests are skipped automatically. Run the full suite in Docker:

```bash
docker compose run --rm api python -m pytest
```

Test outputs (XML/PDF) are written to `out/`. Mustang tests run when `tools/Mustang-CLI.jar` (or `MUSTANG_JAR`) and Java exist.

## Project layout

```
app/
  main.py          FastAPI routes
  schemas.py       request model + business rules (BR-xx)
  calc.py          amount calculation (Decimal, EN 16931 rules)
  xml_builder.py   CII XML via drafthorse
  pdf_renderer.py  Jinja2 -> HTML -> WeasyPrint PDF/A-3b
  embed.py         XML + Factur-X XMP into the PDF
  logo.py          base64 / URL logo handling
  i18n.py          German / English labels
  templates/invoice.html, static/invoice.css
examples/client/   vanilla JS browser client + Node.js script
tests/             pytest (calc, xml, api, mustang)
```

## Deployment (Linux server, Docker + Caddy)

`docker-compose.prod.yml` runs the API behind [Caddy](https://caddyserver.com/), which terminates TLS and
obtains Let's Encrypt certificates automatically when `SITE_ADDRESS` is a domain.

```bash
deploy/deploy.sh root@203.0.113.10                      # first test: plain HTTP on the IP
deploy/deploy.sh root@203.0.113.10 invoice.example.com  # HTTPS (DNS A record -> server, ports 80/443 open)
```

The script installs Docker if needed, uploads the project to `/opt/e-rechnung`, creates `.env` with a random
`API_KEYS` value on the first run (printed once) and starts the stack. Re-running it updates the code and
keeps the existing `.env`. Manual steps on the server:

```bash
cd /opt/e-rechnung
docker compose -f docker-compose.prod.yml logs -f api     # logs
docker compose -f docker-compose.prod.yml up -d --build   # rebuild after changes
nano .env                                                 # API_KEYS, CORS_ORIGINS, SITE_ADDRESS
```

Checklist for production: open only ports 22, 80 and 443 in the provider firewall, log in with SSH keys
instead of the initial root password, set `CORS_ORIGINS` to the origins of your applications, and set
`SERVE_CLIENT=false` if the test client should not be public.

## Author and license

Built and operated by [Abbas Albukhari](https://rechnungskern.de/ueber) – live at <https://rechnungskern.de>.

Released under the [MIT License](LICENSE). ZUGFeRD is a trademark of the Forum elektronische Rechnung
Deutschland (FeRD); XRechnung is a standard of KoSIT. Both are mentioned descriptively. The Mustang validator
is a separate project (Apache License 2.0) and is downloaded at image build time, not redistributed here.
