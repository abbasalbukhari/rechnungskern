#!/usr/bin/env bash
# Deploy / update the e-rechnung service on a Linux server (Debian/Ubuntu) over SSH.
#
#   deploy/deploy.sh root@203.0.113.10                      # HTTP on the IP (first test)
#   deploy/deploy.sh root@203.0.113.10 invoice.example.com  # HTTPS via Let's Encrypt
#
# Needs: ssh + tar locally (Git Bash on Windows is fine). SSH key or password login on the server.
# Installs Docker on the server if missing, uploads the project to /opt/e-rechnung,
# creates .env with a random API key on the first run, then starts docker-compose.prod.yml.
set -euo pipefail

HOST=${1:?usage: deploy/deploy.sh user@host [domain]}
DOMAIN=${2:-}
REMOTE_DIR=${REMOTE_DIR:-/opt/e-rechnung}
SSH=(ssh -o StrictHostKeyChecking=accept-new "$HOST")

cd "$(dirname "$0")/.."

echo "==> checking Docker on $HOST"
"${SSH[@]}" 'command -v docker >/dev/null 2>&1 || { curl -fsSL https://get.docker.com | sh; }; docker compose version'

echo "==> uploading project to $HOST:$REMOTE_DIR"
"${SSH[@]}" "mkdir -p $REMOTE_DIR"
tar czf - \
  --exclude=.venv --exclude=.git --exclude=out --exclude=tools --exclude=logs \
  --exclude=__pycache__ --exclude=.pytest_cache --exclude=.env \
  . | "${SSH[@]}" "tar xzf - -C $REMOTE_DIR"

echo "==> preparing .env"
"${SSH[@]}" "cd $REMOTE_DIR && if [ ! -f .env ]; then
  cp .env.example .env
  KEY=\$(openssl rand -hex 24 2>/dev/null || head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n')
  sed -i \"s|^API_KEYS=.*|API_KEYS=\$KEY|\" .env
  sed -i \"s|^CORS_ORIGINS=.*|CORS_ORIGINS=*|\" .env
  echo \"SITE_ADDRESS=${DOMAIN:-:80}\" >> .env
  echo
  echo '  New API key (keep it safe, it is only shown once):'
  echo \"  \$KEY\"
  echo
else
  if [ -n '$DOMAIN' ]; then sed -i \"s|^SITE_ADDRESS=.*|SITE_ADDRESS=$DOMAIN|\" .env; grep -q '^SITE_ADDRESS=' .env || echo 'SITE_ADDRESS=$DOMAIN' >> .env; fi
  echo '  .env already exists, keeping API_KEYS'
fi"

echo "==> building and starting containers"
"${SSH[@]}" "cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml up -d --build --remove-orphans && docker compose -f docker-compose.prod.yml ps"

if [ -n "$DOMAIN" ]; then
  echo "==> done: https://$DOMAIN/docs   (DNS A record must point to the server, ports 80/443 open)"
else
  echo "==> done: http://${HOST#*@}/docs   (plain HTTP; add a domain for HTTPS)"
fi
