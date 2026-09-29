"""Embed the CII XML into the PDF/A-3 and write the Factur-X/ZUGFeRD XMP metadata."""

from __future__ import annotations

from drafthorse.pdf import attach_xml

from .config import settings
from .i18n import labels
from .schemas import InvoiceRequest, Profile

XMP_LEVEL = {Profile.EN16931: "EN 16931", Profile.XRECHNUNG: "XRECHNUNG"}
PDF_LANG = {"de": "de-DE", "en": "en-US"}


def embed_xml(pdf: bytes, xml: bytes, req: InvoiceRequest) -> bytes:
    lb = labels(req.language.value)
    doc_type = req.layout.title or lb.get(f"doc_{req.invoice.type_code}", lb["doc_380"])
    title = f"{doc_type} {req.invoice.number}"
    metadata = {
        "author": req.seller.name,
        "title": title,
        "subject": f"{title} - {req.seller.name} - {req.invoice.issue_date.isoformat()}",
        "keywords": "Factur-X, ZUGFeRD, EN 16931, Invoice",
        "creator": settings.producer,
    }
    return attach_xml(
        pdf,
        xml,
        level=XMP_LEVEL[req.profile],
        metadata=metadata,
        lang=PDF_LANG[req.language.value],
    )
