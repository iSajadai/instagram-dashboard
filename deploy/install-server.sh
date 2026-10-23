#!/usr/bin/env bash
# Install (or update) the panel on a Linux server with Docker, behind nginx, without touching
# anything else on the server. Safe to run again: it pulls the latest code and restarts the panel.
#
#   sudo ADMIN_PASSWORD='…' bash install-server.sh <domain> <admin-username> [--import DIR]
#
# - code in /opt/instagram-dashboard, data in /opt/instagram-dashboard/var (back this folder up)
# - the panel listens on 127.0.0.1 only, on the first free port from 8000
# - the admin is created here, before the site is reachable, so nobody else can claim it
# - nginx: adds one site for <domain>; TLS from /etc/ssl/cloudflare/<domain>.pem/.key (a Cloudflare
#   Origin Certificate) when present, else plain HTTP (put Cloudflare or certbot in front)
# - --import DIR copies an existing dashboard (data/, raw/, content/) into the admin's account
set -euo pipefail
DOMAIN="${1:?domain, e.g. dash.example.com}"
ADMIN="${2:?admin username}"
IMPORT=""
[ "${3:-}" = "--import" ] && IMPORT="${4:?folder to import}"
REPO="${REPO:-https://github.com/iSajadai/instagram-dashboard.git}"
DIR=/opt/instagram-dashboard

[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
command -v docker >/dev/null || { echo "Docker is needed: https://docs.docker.com/engine/install/"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "the Docker Compose plugin is needed"; exit 1; }

# 1) code
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only --quiet; else git clone --quiet "$REPO" "$DIR"; fi
cd "$DIR"

# 2) settings, and a free local port (kept from an earlier run)
touch .env
PORT=$(sed -n 's/^SAJADAI_PORT=//p' .env)
if [ -z "$PORT" ]; then
  PORT=8000
  while ss -ltn "sport = :$PORT" | grep -q LISTEN; do PORT=$((PORT + 1)); done
  echo "SAJADAI_PORT=$PORT" >> .env
fi
grep -q '^SAJADAI_PUBLIC_URL=' .env || echo "SAJADAI_PUBLIC_URL=https://$DOMAIN" >> .env
grep -q '^SAJADAI_SECURE_COOKIES=' .env || echo "SAJADAI_SECURE_COOKIES=1" >> .env
chmod 600 .env
mkdir -p var

# 3) run it
docker compose up -d --build --quiet-pull
for _ in $(seq 1 60); do curl -fs "http://127.0.0.1:$PORT/api/state" >/dev/null && break; sleep 1; done
curl -fs "http://127.0.0.1:$PORT/api/state" >/dev/null || { echo "the panel didn't start: docker compose logs panel"; exit 1; }

# 4) the admin, before the site is public
if curl -fs "http://127.0.0.1:$PORT/api/state" | grep -q '"setup_needed":true'; then
  [ -n "${ADMIN_PASSWORD:-}" ] || { echo "set ADMIN_PASSWORD (8+ characters) to create the admin"; exit 1; }
  printf '%s\n' "$ADMIN_PASSWORD" | docker compose exec -T panel python -m sajadai create-user "$ADMIN" --admin --password-stdin
fi

# 5) existing data
if [ -n "$IMPORT" ]; then
  rm -rf var/import && mkdir -p var/import
  for sub in data raw content; do [ -d "$IMPORT/$sub" ] && cp -r "$IMPORT/$sub" var/import/; done
  docker compose exec -T panel python -m sajadai import "$ADMIN" /data/import
  rm -rf var/import
fi

# 6) nginx site for this domain only
if command -v nginx >/dev/null; then
  SITE=/etc/nginx/sites-available/instagram-dashboard-$DOMAIN
  if [ -s "/etc/ssl/cloudflare/$DOMAIN.pem" ] && [ -s "/etc/ssl/cloudflare/$DOMAIN.key" ]; then
    sed -e "s/__HOST__/$DOMAIN/g" -e "s#127.0.0.1:8000#127.0.0.1:$PORT#" deploy/nginx-panel.conf > "$SITE"
  else
    cat > "$SITE" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;
    client_max_body_size 1m;
    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 180s;
    }
}
EOF
    echo "note: no certificate in /etc/ssl/cloudflare/$DOMAIN.*; serving HTTP (fine behind Cloudflare 'Flexible', or run certbot --nginx -d $DOMAIN)"
  fi
  ln -sf "$SITE" "/etc/nginx/sites-enabled/instagram-dashboard-$DOMAIN"
  nginx -t && systemctl reload nginx
else
  echo "nginx isn't installed: point your reverse proxy at http://127.0.0.1:$PORT for $DOMAIN"
fi

echo
echo "Panel running on 127.0.0.1:$PORT for https://$DOMAIN (data: $DIR/var)."
echo "Check before switching DNS: curl -sk --resolve $DOMAIN:443:127.0.0.1 https://$DOMAIN/api/state"
