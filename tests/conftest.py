import json
import os
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
OUT_DIR = Path(__file__).resolve().parent.parent / "out"

# Tests must not depend on the environment (e.g. API_KEYS from .env inside the container).
os.environ["API_KEYS"] = "test-key"
os.environ["ALLOW_LOGO_URL"] = "false"
os.environ["PROJECT_REPO"] = "https://github.com/example/rechnungskern"
os.environ["AUTHOR_NAME"] = "Erika Musterfrau"
os.environ["SITE_URL"] = "https://example.test"
os.environ["CANONICAL_REDIRECT_HOSTS"] = "www.example.test, api.example.test"
_local_jar = Path(__file__).resolve().parent.parent / "tools" / "Mustang-CLI.jar"
if not os.getenv("MUSTANG_JAR") and _local_jar.is_file():
    os.environ["MUSTANG_JAR"] = str(_local_jar)  # lets the app's /v1/validate work in local runs too


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# 1x1 transparent PNG, base64 encoded (usable as seller.logo.data_base64)
PNG_1PX_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def with_logo(data: dict) -> dict:
    data["seller"]["logo"] = {"media_type": "image/png", "data_base64": PNG_1PX_B64}
    data["seller"].pop("logo_url", None)
    return data


@pytest.fixture
def sample() -> dict:
    return load("sample_request.json")


@pytest.fixture
def sample_xrechnung() -> dict:
    return load("sample_xrechnung.json")


@pytest.fixture(scope="session")
def out_dir() -> Path:
    OUT_DIR.mkdir(exist_ok=True)
    return OUT_DIR


def mustang_jar() -> Path | None:
    candidates = [os.getenv("MUSTANG_JAR", ""), str(Path(__file__).resolve().parent.parent / "tools" / "Mustang-CLI.jar")]
    for c in candidates:
        if c and Path(c).is_file() and shutil.which(os.getenv("JAVA_BIN", "java")):
            return Path(c)
    return None


def weasyprint_ok() -> bool:
    try:
        import weasyprint  # noqa: F401
    except Exception:
        return False
    return True


needs_pdf = pytest.mark.skipif(not weasyprint_ok(), reason="WeasyPrint system libraries not available")
needs_mustang = pytest.mark.skipif(mustang_jar() is None, reason="Mustang jar / java not available")
