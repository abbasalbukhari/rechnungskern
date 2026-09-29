import base64
import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import PNG_1PX_B64, needs_pdf, with_logo

HEADERS = {"X-API-Key": "test-key"}
PNG_1PX = base64.b64decode(PNG_1PX_B64)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_auth_required(client, sample):
    assert client.post("/v1/invoices/xml", json=sample).status_code == 401
    assert client.post("/v1/invoices/xml", json=sample, headers={"X-API-Key": "wrong"}).status_code == 401


def test_xml_endpoint(client, sample):
    r = client.post("/v1/invoices/xml", json=sample, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/xml")
    assert 'filename="RE-2026-00042.xml"' in r.headers["content-disposition"]
    assert b"CrossIndustryInvoice" in r.content


def test_totals_endpoint(client, sample):
    r = client.post("/v1/invoices/totals", json=sample, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["grand_total"] == "2190.28"


def test_validation_error_is_422(client, sample):
    sample["allowances"] = [{"amount": "10.00"}]  # ambiguous VAT group
    r = client.post("/v1/invoices/xml", json=sample, headers=HEADERS)
    assert r.status_code == 422
    assert "tax_category" in r.json()["detail"]

    del sample["items"]
    r = client.post("/v1/invoices/xml", json=sample, headers=HEADERS)
    assert r.status_code == 422


def test_html_preview(client, sample):
    sample["seller"]["logo"] = {"media_type": "image/png", "data_base64": base64.b64encode(PNG_1PX).decode()}
    r = client.post("/v1/invoices/html", json=sample, headers=HEADERS)
    assert r.status_code == 200, r.text
    html = r.text
    assert "RE-2026-00042" in html
    assert "data:image/png;base64," in html
    assert "2.190,28" in html  # German number format
    assert "&lt;" not in html.split("<body>")[0]  # nothing escaped in head


def test_logo_mismatch_rejected(client, sample):
    sample["seller"]["logo"] = {"media_type": "image/jpeg", "data_base64": base64.b64encode(PNG_1PX).decode()}
    r = client.post("/v1/invoices/html", json=sample, headers=HEADERS)
    assert r.status_code == 422


def test_html_english(client, sample):
    sample["language"] = "en"
    r = client.post("/v1/invoices/html", json=sample, headers=HEADERS)
    assert r.status_code == 200
    assert "Invoice" in r.text and "€2,190.28" in r.text


@needs_pdf
def test_pdf_endpoint(client, sample, out_dir):
    from facturx import get_facturx_xml_from_pdf

    r = client.post("/v1/invoices/pdf", json=with_logo(sample), headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    pdf = r.content
    assert pdf.startswith(b"%PDF")
    (out_dir / "sample.pdf").write_bytes(pdf)

    filename, xml = get_facturx_xml_from_pdf(io.BytesIO(pdf), check_xsd=True)
    assert filename == "factur-x.xml"
    assert b"RE-2026-00042" in xml


@needs_pdf
def test_pdf_xrechnung_profile(client, sample_xrechnung, out_dir):
    r = client.post("/v1/invoices/pdf", json=sample_xrechnung, headers=HEADERS)
    assert r.status_code == 200, r.text
    (out_dir / "sample_xrechnung.pdf").write_bytes(r.content)


@needs_pdf
def test_pdf_many_pages(client, sample, out_dir):
    sample["items"] = [
        {"name": f"Artikel {i}", "description": "Beschreibung der Position", "quantity": str(i % 5 + 1), "unit_price": f"{10 + i}.00", "tax_rate": "19"}
        for i in range(1, 101)
    ]
    sample["allowances"] = sample["charges"] = []
    r = client.post("/v1/invoices/pdf", json=sample, headers=HEADERS)
    assert r.status_code == 200, r.text
    (out_dir / "sample_100_items.pdf").write_bytes(r.content)
    from pypdf import PdfReader

    assert len(PdfReader(io.BytesIO(r.content)).pages) >= 3
