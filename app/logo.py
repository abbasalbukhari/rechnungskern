"""Logo handling: base64 payload or (optionally) a URL, returned as a data URI."""

from __future__ import annotations

import base64
import binascii
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from .config import settings
from .schemas import Seller

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


class LogoError(ValueError):
    pass


def sniff(data: bytes) -> str | None:
    if data.startswith(PNG_MAGIC):
        return "image/png"
    if data.startswith(JPEG_MAGIC):
        return "image/jpeg"
    head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head.startswith(b"<") and b"<svg" in head:
        return "image/svg+xml"
    return None


def _assert_public_host(url: str) -> None:
    """Refuse URLs that resolve to private / loopback addresses (SSRF guard)."""
    host = urlparse(url).hostname
    if not host:
        raise LogoError("logo_url has no host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise LogoError(f"logo_url host cannot be resolved: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise LogoError("logo_url must not point to a private or local address")


def _fetch(url: str) -> bytes:
    if not settings.allow_logo_url:
        raise LogoError("fetching logo_url is disabled on this server (ALLOW_LOGO_URL)")
    _assert_public_host(url)
    limit = settings.max_logo_bytes
    try:
        with httpx.Client(timeout=settings.logo_fetch_timeout, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                buf = bytearray()
                for chunk in resp.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > limit:
                        raise LogoError(f"logo_url payload exceeds {limit} bytes")
    except httpx.HTTPError as exc:
        raise LogoError(f"logo_url could not be fetched: {exc}") from exc
    return bytes(buf)


def logo_data_uri(seller: Seller) -> str | None:
    """Return ``data:<type>;base64,...`` for the seller logo, or None."""
    if seller.logo:
        try:
            data = base64.b64decode(seller.logo.data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise LogoError("seller.logo.data_base64 is not valid base64") from exc
        if len(data) > settings.max_logo_bytes:
            raise LogoError(f"logo exceeds {settings.max_logo_bytes} bytes")
        media_type = sniff(data)
        if media_type != seller.logo.media_type:
            raise LogoError(f"logo content is not {seller.logo.media_type}")
    elif seller.logo_url:
        data = _fetch(seller.logo_url)
        media_type = sniff(data)
        if media_type is None:
            raise LogoError("logo_url does not point to a PNG, JPEG or SVG image")
    else:
        return None
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"
