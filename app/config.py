"""Runtime configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    # Comma separated list of accepted keys for the X-API-Key header.
    # Empty list => authentication disabled (only sensible for local development).
    api_keys: list[str] = field(default_factory=lambda: _split(os.getenv("API_KEYS", "")))
    # Allowed browser origins (CORS). "*" allows any origin.
    cors_origins: list[str] = field(default_factory=lambda: _split(os.getenv("CORS_ORIGINS", "*")))
    # Upper bound for logos (base64 payload or downloaded bytes).
    max_logo_bytes: int = int(os.getenv("MAX_LOGO_BYTES", str(2 * 1024 * 1024)))
    # Whether seller.logo_url may be fetched by the server.
    allow_logo_url: bool = os.getenv("ALLOW_LOGO_URL", "true").lower() in {"1", "true", "yes"}
    logo_fetch_timeout: float = float(os.getenv("LOGO_FETCH_TIMEOUT", "5"))
    # Path to Mustang-CLI jar; enables POST /v1/validate when set and java is available.
    mustang_jar: str = os.getenv("MUSTANG_JAR", "")
    java_bin: str = os.getenv("JAVA_BIN", "java")
    # Serve the example browser client at /client (handy for manual testing).
    serve_client: bool = os.getenv("SERVE_CLIENT", "true").lower() in {"1", "true", "yes"}
    # Name written into PDF metadata as producer/creator.
    producer: str = os.getenv("PDF_PRODUCER", "e-rechnung service")

    # Public (key-less, rate limited) endpoints used by the browser pages /rechnung and /pruefung.
    public_enabled: bool = os.getenv("PUBLIC_ENABLED", "true").lower() in {"1", "true", "yes"}
    public_rate_limit: int = int(os.getenv("PUBLIC_RATE_LIMIT", "60"))  # generations per IP per hour
    public_validate_limit: int = int(os.getenv("PUBLIC_VALIDATE_LIMIT", "30"))  # validations per IP per hour

    # Public website (landing page, Impressum, Datenschutz). Empty operator fields show a placeholder.
    site_name: str = os.getenv("SITE_NAME", "Rechnungskern")
    site_url: str = os.getenv("SITE_URL", "").rstrip("/")  # e.g. https://api.rechnungskern.de
    contact_email: str = os.getenv("CONTACT_EMAIL", "")
    operator_name: str = os.getenv("OPERATOR_NAME", "")
    operator_street: str = os.getenv("OPERATOR_STREET", "")
    operator_city: str = os.getenv("OPERATOR_CITY", "")  # postcode + city
    operator_country: str = os.getenv("OPERATOR_COUNTRY", "Deutschland")
    operator_phone: str = os.getenv("OPERATOR_PHONE", "")
    operator_vat_id: str = os.getenv("OPERATOR_VAT_ID", "")
    operator_register: str = os.getenv("OPERATOR_REGISTER", "")
    hosting_provider: str = os.getenv("HOSTING_PROVIDER", "IONOS SE, Elgendorfer Str. 57, 56410 Montabaur, Deutschland")

    # Author / "about" page (portfolio reference). Empty links are simply not shown.
    author_name: str = os.getenv("AUTHOR_NAME", "") or os.getenv("OPERATOR_NAME", "")
    author_title_de: str = os.getenv("AUTHOR_TITLE_DE", "")  # e.g. "IT-Spezialist aus Herne"
    author_title_en: str = os.getenv("AUTHOR_TITLE_EN", "")  # e.g. "IT specialist from Herne, Germany"
    author_linkedin: str = os.getenv("AUTHOR_LINKEDIN", "")
    author_github: str = os.getenv("AUTHOR_GITHUB", "")
    author_xing: str = os.getenv("AUTHOR_XING", "")
    author_websites: list[str] = field(default_factory=lambda: _split(os.getenv("AUTHOR_WEBSITE", "")))  # comma separated
    project_repo: str = os.getenv("PROJECT_REPO", "").rstrip("/")  # public source code URL, if any
    project_license: str = os.getenv("PROJECT_LICENSE", "MIT")


settings = Settings()
