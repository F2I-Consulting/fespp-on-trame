#!/usr/bin/env bash
# One-time setup of the host's Apache in front of the site (Ubuntu or Debian):
#
#   sudo bash deploy/apache/setup.sh <domain> <user> [email]
#
# Installs Apache, htpasswd and certbot when missing, enables the proxy
# modules, writes /etc/apache2/sites-available/fespp.conf for <domain>, asks
# the password of <user>, gets the HTTPS certificate (Let's Encrypt, renewed
# by itself) and reloads Apache. Run it again to change the password or add a
# user. Before: <domain> points to this machine and its ports 80 and 443 are
# open; the application itself runs with bash deploy/linux/run.sh.
set -euo pipefail
DOMAIN="${1:-}"
WHO="${2:-}"
EMAIL="${3:-}"
[ -n "$DOMAIN" ] && [ -n "$WHO" ] || { echo "usage: sudo bash deploy/apache/setup.sh <domain> <user> [email]"; exit 1; }
[ "$(id -u)" = 0 ] || { echo "[ERROR] run it with sudo"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== Packages (apache2, apache2-utils, certbot)"
apt-get update -qq
apt-get install -y -qq apache2 apache2-utils certbot python3-certbot-apache >/dev/null

echo "== Apache modules"
a2enmod -q proxy proxy_http proxy_wstunnel headers rewrite ssl >/dev/null

SITE=/etc/apache2/sites-available/fespp.conf
if [ -f "$SITE" ]; then
    # kept as it is: certbot added its redirect to HTTPS there
    echo "== Site already installed ($SITE)"
else
    echo "== Site $DOMAIN"
    sed "s/FESPP_DOMAIN/$DOMAIN/g" "$HERE/fespp.conf" > "$SITE"
fi
a2ensite -q fespp >/dev/null

echo "== Password of $WHO"
if [ -f /etc/apache2/fespp.htpasswd ]; then
    htpasswd /etc/apache2/fespp.htpasswd "$WHO"
else
    htpasswd -c /etc/apache2/fespp.htpasswd "$WHO"
fi

apachectl configtest
systemctl reload apache2

if [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
    echo "== HTTPS certificate already there (renewed by itself)"
else
    echo "== HTTPS certificate (Let's Encrypt)"
    if [ -n "$EMAIL" ]; then contact=(-m "$EMAIL"); else contact=(--register-unsafely-without-email); fi
    certbot --apache -d "$DOMAIN" --redirect --non-interactive --agree-tos "${contact[@]}" || {
        echo "[ERROR] certbot failed: does $DOMAIN point to this machine, and do ports 80 and 443 reach it?"
        exit 1
    }
fi
systemctl reload apache2
echo "[OK] https://$DOMAIN/fespp/"
