#!/bin/bash
# Kaaran's server, set up by itself: Google Cloud runs this as root at every
# boot of the VM (gcp-create.sh attaches it). The first boot installs
# everything from docs/deploy.md; later boots only point the DuckDNS name at
# this server again and leave the rest to systemd. Progress:
#   sudo tail -f /var/log/kaaran-setup.log
set -euo pipefail
exec >> /var/log/kaaran-setup.log 2>&1
echo "=== $(date): Kaaran setup"

# Settings that gcp-create.sh stored with the VM ("metadata")
setting() {
  curl -fs -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1" || true
}
DOMAIN=$(setting kaaran-domain)
DUCKDNS_TOKEN=$(setting duckdns-token)
SMTP_USER=$(setting kaaran-smtp-user)
SMTP_PASSWORD=$(setting kaaran-smtp-password)

# Point the DuckDNS name at this server (an empty ip= means "the address this request comes from")
if [[ -n "$DUCKDNS_TOKEN" && "$DOMAIN" == *.duckdns.org ]]; then
  echo "DuckDNS: $(curl -fs "https://www.duckdns.org/update?domains=${DOMAIN%.duckdns.org}&token=${DUCKDNS_TOKEN}&ip=" || echo failed)"
fi

if [[ -f /opt/kaaran/.installed ]]; then
  echo "Already installed; systemd keeps it running."
  exit 0
fi

# 1 GB of memory is tight for building the sandbox image: add 2 GB of swap
if [[ ! -f /swapfile ]]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git python3-venv docker.io caddy unattended-upgrades curl

id kaaran >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin kaaran
[[ -d /opt/kaaran ]] || git clone --depth 1 https://github.com/devrajrawat9027562124-web/kaaran.git /opt/kaaran
cd /opt/kaaran

python3 -m venv backend/.venv
backend/.venv/bin/pip install --quiet -r backend/requirements.txt
echo "Building the sandbox image (several minutes on this small machine)"
docker build -t kaaran-runner backend/runner

# The server's settings
cp deploy/production.env.example backend/.env
if [[ -n "$SMTP_USER" && -n "$SMTP_PASSWORD" ]]; then
  sed -i -e "s|^SMTP_HOST=.*|SMTP_HOST=smtp.gmail.com|" \
         -e "s|^SMTP_USER=.*|SMTP_USER=${SMTP_USER}|" \
         -e "s|^SMTP_PASSWORD=.*|SMTP_PASSWORD=${SMTP_PASSWORD}|" \
         -e "s|^MAIL_FROM=.*|MAIL_FROM=\"Kaaran <${SMTP_USER}>\"|" backend/.env
else
  echo "No Gmail given: sign-up codes can't be emailed until SMTP_* is set in /opt/kaaran/backend/.env"
fi
chown root:kaaran backend/.env
chmod 640 backend/.env
install -d -o kaaran -g kaaran -m 700 /var/backups/kaaran

# The backend as a service, and the daily backup
cp deploy/kaaran.service deploy/kaaran-backup.service deploy/kaaran-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now kaaran kaaran-backup.timer

# HTTPS: Caddy gets the certificate once the name points here (it keeps retrying until then)
if [[ -n "$DOMAIN" ]]; then
  sed "s/kaaran.example.com/${DOMAIN}/" deploy/Caddyfile > /etc/caddy/Caddyfile
  systemctl reload-or-restart caddy
fi

sleep 3
echo "Backend says: $(curl -fs http://127.0.0.1:8000/health || echo 'not answering yet: journalctl -u kaaran -n 50')"
touch /opt/kaaran/.installed
echo "=== $(date): done. Try https://${DOMAIN}/health"
