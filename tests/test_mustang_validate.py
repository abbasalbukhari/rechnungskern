"""Integration tests: validate generated documents with the official Mustang validator.

Needs Java and the Mustang-CLI jar (MUSTANG_JAR env or tools/Mustang-CLI.jar).
Checks XSD + Schematron (EN 16931 / XRechnung) for the XML and additionally
PDF/A-3 + XMP for the hybrid PDF.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from lxml import etree

from app.calc import calculate
from app.schemas import InvoiceRequest
from app.xml_builder import build_xml
from tests.conftest import mustang_jar, needs_mustang, needs_pdf, with_logo

pytestmark = needs_mustang


def run_validator(data: bytes, suffix: str) -> tuple[bool, list[str]]:
    jar = mustang_jar()
    with tempfile.TemporaryDirectory(prefix="mustang-") as td:
        src = Path(td) / f"doc{suffix}"
        src.write_bytes(data)
        cmd = [os.getenv("JAVA_BIN", "java"), "-jar", str(jar), "--action", "validate", "--source", str(src), "--no-notices"]
        proc = subprocess.run(cmd, cwd=td, capture_output=True, timeout=300)
    out = proc.stdout.decode("utf-8", "replace")
    start = out.find("<validation")
    assert start >= 0, proc.stderr.decode("utf-8", "replace")[-3000:]
    root = etree.fromstring(out[start:].encode("utf-8"))
    status = root.find("summary").get("status")
    msgs = [f"[{el.tag}/{el.get('type')}] {el.get('location') or ''} {(el.text or '').strip()}" for el in root.iter("error", "warning")]
    return status == "valid", msgs


def make_xml(data: dict) -> bytes:
    req = InvoiceRequest.model_validate(data)
    return build_xml(req, calculate(req))


def test_xml_en16931_valid(sample):
    valid, msgs = run_validator(make_xml(sample), ".xml")
    assert valid, "\n".join(msgs)


def test_xml_xrechnung_valid(sample_xrechnung):
    valid, msgs = run_validator(make_xml(sample_xrechnung), ".xml")
    assert valid, "\n".join(msgs)


def test_xml_exempt_and_credit_note_valid(sample):
    sample["invoice"]["type_code"] = "381"
    sample["items"] = [
        {"name": "Reverse charge service", "quantity": "2", "unit_price": "100", "tax_rate": "0", "tax_category": "AE"},
        {"name": "Standard", "quantity": "1", "unit_price": "50", "tax_rate": "19", "tax_category": "S"},
    ]
    sample["allowances"] = [{"percent": "5", "tax_category": "S", "tax_rate": "19", "reason": "Rabatt"}]
    sample["charges"] = []
    valid, msgs = run_validator(make_xml(sample), ".xml")
    assert valid, "\n".join(msgs)


@needs_pdf
@pytest.mark.parametrize("fixture_name", ["sample", "sample_xrechnung"])
def test_pdf_valid(fixture_name, request, out_dir):
    from app.embed import embed_xml
    from app.logo import logo_data_uri
    from app.pdf_renderer import html_to_pdf, render_html

    data = request.getfixturevalue(fixture_name)
    if fixture_name == "sample":
        with_logo(data)  # PDF/A must stay valid with an embedded image
    req = InvoiceRequest.model_validate(data)
    totals = calculate(req)
    xml = build_xml(req, totals)
    pdf = embed_xml(html_to_pdf(render_html(req, totals, logo_data_uri(req.seller))), xml, req)
    (out_dir / f"{fixture_name}_validated.pdf").write_bytes(pdf)
    valid, msgs = run_validator(pdf, ".pdf")
    assert valid, "\n".join(msgs)
