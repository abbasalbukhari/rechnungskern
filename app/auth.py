"""API key authentication (header ``X-API-Key``)."""

from __future__ import annotations

import logging
import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from .config import settings

log = logging.getLogger("e-rechnung")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

if not settings.api_keys:
    log.warning("API_KEYS is empty: authentication is DISABLED. Set API_KEYS in production.")


def require_api_key(key: str | None = Security(api_key_header)) -> str | None:
    if not settings.api_keys:
        return None
    if key and any(secrets.compare_digest(key, valid) for valid in settings.api_keys):
        return key
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing X-API-Key",
        headers={"WWW-Authenticate": "ApiKey"},
    )
