import pytest
from fastapi.testclient import TestClient

from app.main import app, generate_limit
from app.ratelimit import RateLimiter
from app.summary import summarize
from tests.conftest import needs_mustang


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize(
    "path,lang,marker",
    [
        ("/", "de", "E-Rechnungen erstellen und prüfen"),
        ("/en", "en", "Create and validate e-invoices"),
        ("/rechnung", "de", 'id="form"'),
        ("/en/invoice", "en", 'id="form"'),
        ("/pruefung", "de", 'id="drop"'),
        ("/en/validate", "en", 'id="drop"'),
        ("/ueber", "de", "Über"),
        ("/en/about", "en", "About"),
        ("/impressum", "de", "§ 5 DDG"),
        ("/legal-notice", "en", "Legal notice"),
        ("/datenschutz", "de", "unmittelbar nach der Auslieferung gelöscht"),
        ("/privacy", "en", "deleted immediately after delivery"),
    ],
)
def test_pages(client, path, lang, marker):
    r = client.get(path)
    assert r.status_code == 200, path
    assert f'<html lang="{lang}">' in r.text
    assert marker in r.text
    assert "<link rel=\"canonical\"" in r.text
    assert 'property="og:title"' in r.text


def test_seo_extras(client):
    home = client.get("/").text
    assert 'hreflang="en"' in home and 'application/ld+json' in home and '"FAQPage"' in home
    robots = client.get("/robots.txt").text
    assert "Sitemap:" in robots and "Disallow: /v1/" in robots
    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200 and "<loc>" in sitemap.text and "/en/invoice" in sitemap.text
    assert client.get("/static/site/app.js").status_code == 200
    assert client.get("/static/site/site.css").status_code == 200


def test_source_and_license_links(client):
    for path in ("/", "/en", "/ueber", "/en/about", "/rechnung"):
        html = client.get(path).text
        assert 'href="https://github.com/example/rechnungskern"' in html, path
        assert "https://github.com/example/rechnungskern/blob/main/LICENSE" in html, path
    assert '"SoftwareSourceCode"' in client.get("/").text
    assert "Erika Musterfrau" in client.get("/").text


def test_public_endpoints_need_no_key(client, sample):
    r = client.post("/v1/public/invoices/totals", json=sample)
    assert r.status_code == 200 and r.json()["grand_total"] == "2190.28"
    r = client.post("/v1/public/invoices/xml", json=sample)
    assert r.status_code == 200 and b"CrossIndustryInvoice" in r.content
    # keyed endpoints still require the key
    assert client.post("/v1/invoices/xml", json=sample).status_code == 401


def test_rate_limiter_class():
    rl = RateLimiter(limit=2, window_seconds=60)
    assert rl.hit("a") == 0 and rl.hit("a") == 0
    assert rl.hit("a") > 0  # third hit blocked
    assert rl.hit("b") == 0  # other client unaffected


def test_public_rate_limit_429(client, sample):
    limiter = generate_limit.limiter
    old = limiter.limit
    limiter.reset()
    limiter.limit = 2
    try:
        assert client.post("/v1/public/invoices/xml", json=sample).status_code == 200
        assert client.post("/v1/public/invoices/xml", json=sample).status_code == 200
        r = client.post("/v1/public/invoices/xml", json=sample)
        assert r.status_code == 429 and "Retry-After" in r.headers
    finally:
        limiter.limit = old
        limiter.reset()


def test_summary_from_xml(sample):
    from app.calc import calculate
    from app.schemas import InvoiceRequest
    from app.xml_builder import build_xml

    req = InvoiceRequest.model_validate(sample)
    info = summarize(build_xml(req, calculate(req)))
    assert info["number"] == "RE-2026-00042"
    assert info["seller"] == "Muster Technik GmbH"
    assert info["grand_total"] == "2190.28" and info["currency"] == "EUR"
    assert info["issue_date"] == "2026-09-28" and info["line_count"] == 3
    assert summarize(b"not xml at all") is None


@needs_mustang
def test_public_validate_returns_summary(client, sample):
    xml = client.post("/v1/public/invoices/xml", json=sample).content
    r = client.post("/v1/public/validate", files={"file": ("rechnung.xml", xml, "application/xml")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is True
    assert body["summary"]["number"] == "RE-2026-00042"
