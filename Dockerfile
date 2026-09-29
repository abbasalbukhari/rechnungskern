FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MUSTANG_JAR=/opt/mustang/Mustang-CLI.jar \
    JAVA_BIN=java

# WeasyPrint runtime (Pango/HarfBuzz), fonts with full embedding rights, Java for the Mustang validator
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 libffi8 \
        fonts-liberation fonts-dejavu-core fontconfig \
        openjdk-17-jre-headless \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f

ARG MUSTANG_VERSION=2.26.0
RUN mkdir -p /opt/mustang \
    && curl -fsSL -o /opt/mustang/Mustang-CLI.jar \
       https://github.com/ZUGFeRD/mustangproject/releases/download/core-${MUSTANG_VERSION}/Mustang-CLI-${MUSTANG_VERSION}.jar

WORKDIR /srv
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY app ./app
COPY examples ./examples
COPY tests ./tests
COPY pyproject.toml ./

RUN useradd -r -u 10001 -d /srv app && mkdir -p /srv/logs && chown -R app /srv
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fs http://localhost:8000/health || exit 1
# --proxy-headers: the container only sits behind Caddy (docker network), so trust X-Forwarded-For for rate limiting
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
