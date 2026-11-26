#!/usr/bin/env bash
# Research-Hub Live-Dashboard auf einer Always-Free-VM (z. B. Oracle Cloud ARM, 2 VMs gratis).
# Daten liegen NICHT bei GitHub: serve.py liest die Mistral-Libraries serverseitig per API-Key.
#
# Voraussetzungen:
#   - Ubuntu/Debian 22.04+, root/sudo
#   - A-Record dashboard.deinedomain.at -> IP der VM, Ports 80/443 in der Cloud-Security-List offen
#   - API-Key liegt NUR in /etc/research-hub.env (chmod 600, nie in git)
#
# Usage:  sudo bash setup.sh dashboard.deinedomain.at
set -euo pipefail

DOMAIN="${1:?Usage: sudo bash setup.sh dashboard.deinedomain.at}"
APP_DIR=/opt/research-hub
REPO=https://github.com/wpy4t4hwh4-prog/GrammatikstattStil.git

echo "==> Pakete"
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx ufw git python3

echo "==> Repo klonen (nur Code; data/project.json ist gitignored)"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone --depth 1 "$REPO" "$APP_DIR"
else
  git -C "$APP_DIR" pull --ff-only
fi

echo "==> Env-Datei (manuell befuellen! — nie in git, chmod 600)"
if [ ! -f /etc/research-hub.env ]; then
  printf 'PROJECT_MISTRAL_API_KEY=\nDASHBOARD_PASSWORD=\nDASHBOARD_ALLOWED_HOSTS=%s\n#PROJECT_LIBRARY_ID=\n#APPARAT_LIBRARY_ID=\n' "$DOMAIN" > /etc/research-hub.env
  chmod 600 /etc/research-hub.env
  echo "    /etc/research-hub.env angelegt - jetzt eintragen: sudo nano /etc/research-hub.env"
  echo "      PROJECT_MISTRAL_API_KEY = Mistral-API-Key (La Plateforme)"
  echo "      DASHBOARD_PASSWORD     = Login-Passwort der Web-App (Session-Cookie + CSRF schuetzt /api/*)"
  echo "      DASHBOARD_ALLOWED_HOSTS= $DOMAIN (bereits gesetzt; DNS-Rebinding-Guard)"
fi

echo "==> systemd-Unit"
install -m 644 "$(dirname "$0")/research-hub.service" /etc/systemd/system/research-hub.service
systemctl daemon-reload
systemctl enable --now research-hub

echo "==> nginx Reverse Proxy (X-Forwarded-Proto=https -> serve.py setzt Secure-Cookie)"
cat > /etc/nginx/sites-available/research-hub <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    # optional zusaetzlich: auth_basic \"Research Hub\"; auth_basic_user_file /etc/nginx/.htpasswd;
    # (htpasswd -c /etc/nginx/.htpasswd philipp) — primaerer Schutz ist aber Cloudflare Access, s. RUNBOOK.md
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
EOF
ln -sf /etc/nginx/sites-available/research-hub /etc/nginx/sites-enabled/research-hub
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "==> HTTPS via Let's Encrypt"
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "admin@$DOMAIN" || echo "    certbot fehlgeschlagen (DNS/Port?) - spaeter: certbot --nginx -d $DOMAIN"

echo "==> Firewall: nur 80/443 nach aussen, serve.py bleibt auf 127.0.0.1"
echo "    WICHTIG: vorher SSH erlauben, sonst sperrt man sich aus: ufw allow 22/tcp (oder Cloudflare Tunnel nutzen, dann 22 nur von Admin-IP)"
ufw allow 80/tcp; ufw allow 443/tcp; ufw --force enable

echo "==> Keepalive (OCI Always-Free stoppt idle VMs) — alle 10 min die eigene Seite rufen"
printf '*/10 * * * * root curl -sk -o /dev/null --max-time 10 https://%s/ || true\n' "$DOMAIN" > /etc/cron.d/research-hub-keepalive
chmod 644 /etc/cron.d/research-hub-keepalive

echo "==> Fertig. Test: curl -s http://127.0.0.1:8765/api/live | head  -> danach https://$DOMAIN/"
echo "    Optionaler zusaetzlicher Schutz: Cloudflare-Worker-Gate (cloudflare/worker-gate.js) vor die Domain"
echo "    ODER nginx Basic-Auth (htpasswd). Key liegt nur in /etc/research-hub.env."
