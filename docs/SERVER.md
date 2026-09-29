# Server runbook

How the production server is set up and operated. Generic on purpose – host name, IP and the exact history of
this installation are in `docs/server-notes.private.md` (git-ignored).

## 1. Layout

```
Internet ──▶ :80/:443  Caddy (TLS, Let's Encrypt, gzip, 25 MB body limit, security headers)
                          │  docker network
                          ▼
                       api:8000  uvicorn + FastAPI (image e-rechnung:prod)
                                  ├─ WeasyPrint + fonts        (PDF/A-3)
                                  └─ Java 17 + Mustang-CLI     (/opt/mustang/Mustang-CLI.jar, validator)
```

- Project directory on the server: `/opt/e-rechnung` (a copy of this repository without `.git`, `.venv`, `out`, `tools`).
- Stack definition: `docker-compose.prod.yml` (services `api`, `caddy`; volumes `caddy-data`, `caddy-config` for certificates).
- Configuration: `/opt/e-rechnung/.env` – the only file with secrets and personal data. **Back it up; it is not in git.**
- Both containers restart automatically (`restart: unless-stopped`); logs are JSON files rotated at 10 MB × 5.
- The API container is not published on the host; only Caddy listens on 80/443.

## 2. Server hardening applied

| Area | Setting |
|---|---|
| SSH | Keys only: `/etc/ssh/sshd_config.d/00-keys-only.conf` (`PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `PermitRootLogin prohibit-password`). The file name starts with `00-` so it wins over the provider's `50-cloud-init.conf`. |
| Firewall (ufw) | default deny incoming, allow 22/tcp, 80/tcp, 443/tcp, 443/udp (HTTP/3). Docker publishes only 80/443. Provider-level firewall must also allow 80/443. |
| Updates | `unattended-upgrades` installed (Ubuntu default) for security updates. |
| Secrets | API key generated with `openssl rand -hex 24` at first deploy, stored only in `.env`. |
| Data | The application stores nothing; there is no database and no upload directory. |

## 3. Environment variables (`.env`)

| Variable | Purpose |
|---|---|
| `API_KEYS` | Comma separated keys for `X-API-Key` (keyed endpoints). |
| `SITE_ADDRESS` | Caddy site address: `domain.tld, www.domain.tld, api.domain.tld` → automatic HTTPS; `:80` → plain HTTP for a first test. |
| `SITE_URL`, `SITE_NAME` | Canonical base URL and product name used on the website and in sitemap/JSON-LD. |
| `CANONICAL_REDIRECT_HOSTS` | Alias hosts (`www.…`, `api.…`). Website pages on these hosts answer `301` to `SITE_URL`; API, docs and health stay reachable there with `X-Robots-Tag: noindex`. Prevents duplicate content in search engines. |
| `CONTACT_EMAIL`, `OPERATOR_*` | Impressum / Datenschutz data (name, street, postcode+city, country, phone, VAT ID, register). |
| `AUTHOR_*`, `PROJECT_REPO` | About page: title line, LinkedIn/GitHub/XING, comma separated websites, source code URL. |
| `PUBLIC_ENABLED`, `PUBLIC_RATE_LIMIT`, `PUBLIC_VALIDATE_LIMIT` | Key-less endpoints for the browser pages and their per-IP hourly limits. |
| `CORS_ORIGINS` | Browser origins allowed to call the API (`*` by default). |
| `ALLOW_LOGO_URL`, `MAX_LOGO_BYTES`, `LOGO_FETCH_TIMEOUT` | Logo handling. |
| `SERVE_CLIENT` | Serve the developer test client at `/client/` (set `false` to hide it). |
| `MUSTANG_JAR`, `JAVA_BIN` | Validator location (preset in the image). |

Changing a variable: edit `.env`, then `docker compose -f docker-compose.prod.yml up -d` (recreates only the
containers whose environment changed). `SITE_ADDRESS` changes need the `caddy` container recreated, which the
same command does.

## 4. Deploying and updating

From the development machine (needs SSH key access as root):

```bash
deploy/deploy.sh root@SERVER "domain.tld, www.domain.tld, api.domain.tld"
```

The script: installs Docker if missing → uploads the project with `tar` over SSH (excluding `.venv`, `.git`,
`out`, `tools`, `logs`, `.env`) → creates `.env` from `.env.example` with a random API key on the **first** run
only → writes `SITE_ADDRESS` → `docker compose -f docker-compose.prod.yml up -d --build --remove-orphans`.
Re-running it is the normal way to ship code changes; the existing `.env` is kept.

Manual equivalent on the server:

```bash
cd /opt/e-rechnung
docker compose -f docker-compose.prod.yml up -d --build      # rebuild + restart after code changes
docker compose -f docker-compose.prod.yml ps                 # status / health
docker compose -f docker-compose.prod.yml logs -f api        # application log
docker compose -f docker-compose.prod.yml logs caddy | grep -i certificate   # TLS issuance
docker compose -f docker-compose.prod.yml restart api        # restart only the API
```

## 5. Routine operations

| Task | Command / where |
|---|---|
| Read the current API key | `grep ^API_KEYS= /opt/e-rechnung/.env` |
| Rotate / add an API key | edit `API_KEYS=key1,key2` in `.env`, then `up -d`; several keys allow one per customer |
| Give a customer access | send them a key + `https://<domain>/docs`; they call `/v1/invoices/pdf` with `X-API-Key` |
| Validate a file by hand | `docker compose -f docker-compose.prod.yml exec api java -jar /opt/mustang/Mustang-CLI.jar --action validate --source /srv/out/file.pdf` (copy the file into the mounted `out/` first) |
| Check health from outside | `curl https://<domain>/health` → `{"status":"ok","pdf":true,"validator":true,"auth":true}` |
| Disk space | `docker system df`; `docker image prune -f` removes old build layers |
| System updates | `apt update && apt upgrade -y && reboot` (containers come back automatically) |
| Certificates | Caddy renews automatically; no cron needed. Requires ports 80/443 reachable and DNS pointing here. |
| Backup | Only `/opt/e-rechnung/.env` matters (keys + operator data). Everything else is reproducible from the repository. |

## 6. DNS requirements

- `A` records for each name in `SITE_ADDRESS` → server IPv4.
- **No `AAAA` records unless the server has IPv6.** Let's Encrypt validates over IPv6 first when an AAAA record
  exists; a stale AAAA pointing to a parking page makes the HTTP challenge fail.
- Low TTL (300) while changing things; the provider's default 7200 is fine afterwards.

## 7. Troubleshooting

| Symptom | Check |
|---|---|
| `502` or connection refused | `docker compose ps` – is `api` healthy? `logs api` for a Python traceback |
| HTTPS certificate missing | `logs caddy`: DNS not pointing here, AAAA record wrong, or port 80/443 blocked by the provider firewall |
| `503 PDF rendering unavailable` | WeasyPrint libraries missing – only possible outside the provided image |
| `503 validator not configured` | `MUSTANG_JAR` unset or Java missing – both preset in the image |
| `429` on public pages | expected rate limiting; raise `PUBLIC_RATE_LIMIT` / `PUBLIC_VALIDATE_LIMIT` in `.env` if needed |
| Wrong client IP in rate limiting | API must run with `--proxy-headers --forwarded-allow-ips=*` (Dockerfile CMD) and only be reachable through Caddy |
| Locked out of SSH | provider web console (VNC) still allows password login; re-add a key to `/root/.ssh/authorized_keys` |

## 8. Security notes for the operator

- Keep the SSH private key (`~/.ssh/id_ed25519` on the machine that deploys) safe; add a second key from a new
  laptop via `ssh-copy-id` or by appending its `.pub` to `/root/.ssh/authorized_keys` **before** removing the old one.
- Change the initial root password in the provider panel if it was ever shared or shown on screen; it is still
  valid for the web console even though SSH password login is disabled.
- The site runs without a WAF or DDoS protection; if abuse appears, tighten `PUBLIC_*` limits or put the
  domain behind Cloudflare.
- Keep `CORS_ORIGINS` narrow once real integrations exist.
