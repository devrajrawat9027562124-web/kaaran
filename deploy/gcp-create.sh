#!/bin/bash
# Creates Kaaran's server on Google Cloud's free tier (one e2-micro VM).
# Run it in Cloud Shell (console.cloud.google.com, the >_ button at the top),
# from the kaaran folder:
#
#     git clone https://github.com/devrajrawat9027562124-web/kaaran.git && cd kaaran
#     bash deploy/gcp-create.sh
#
# Before: a Google Cloud project with billing on (the free trial is fine), and
# a free DuckDNS name (duckdns.org: sign in, add a name, copy the token).
# The VM then installs Kaaran by itself (deploy/gcp-startup.sh), in 10-20 minutes.
set -euo pipefail

REGION=us-central1   # the free tier is only in us-west1, us-central1 and us-east1
ZONE=us-central1-a
VM=kaaran

PROJECT=$(gcloud config get-value project 2>/dev/null || true)
if [[ -z "$PROJECT" ]]; then
  echo "Choose your project first:  gcloud config set project YOUR-PROJECT-ID"
  exit 1
fi
echo "Creating Kaaran's server in project $PROJECT ($ZONE, e2-micro, free tier)."
echo

read -rp "DuckDNS name (the part before .duckdns.org): " DUCK
DUCK=${DUCK%.duckdns.org}
read -rsp "DuckDNS token (not shown as you type): " TOKEN; echo
read -rp "Gmail address to send sign-up codes from (Enter to skip for now): " GMAIL
APP_PASSWORD=""
if [[ -n "$GMAIL" ]]; then
  read -rsp "That Gmail's App Password (not shown; spaces are fine): " APP_PASSWORD; echo
  APP_PASSWORD=${APP_PASSWORD// /}
fi
if [[ -z "$DUCK" || -z "$TOKEN" ]]; then
  echo "The DuckDNS name and token are needed for the HTTPS address."
  exit 1
fi

gcloud services enable compute.googleapis.com

# A fixed public address, so the DuckDNS name keeps pointing at the server
gcloud compute addresses describe kaaran-ip --region "$REGION" >/dev/null 2>&1 \
  || gcloud compute addresses create kaaran-ip --region "$REGION"
IP=$(gcloud compute addresses describe kaaran-ip --region "$REGION" --format='value(address)')

# Let web traffic in: port 80 for getting the certificate, 443 for students
gcloud compute firewall-rules describe kaaran-web >/dev/null 2>&1 \
  || gcloud compute firewall-rules create kaaran-web --allow tcp:80,tcp:443 --target-tags kaaran-web

# Secrets go to the VM from files, so they don't sit in the shell's history
SECRETS=$(mktemp -d)
trap 'rm -rf "$SECRETS"' EXIT
printf %s "$TOKEN" > "$SECRETS/token"
FROM_FILES="startup-script=deploy/gcp-startup.sh,duckdns-token=$SECRETS/token"
if [[ -n "$GMAIL" ]]; then
  printf %s "$GMAIL" > "$SECRETS/user"
  printf %s "$APP_PASSWORD" > "$SECRETS/pass"
  FROM_FILES="$FROM_FILES,kaaran-smtp-user=$SECRETS/user,kaaran-smtp-password=$SECRETS/pass"
fi

gcloud compute instances create "$VM" --zone "$ZONE" --machine-type e2-micro \
  --image-family debian-12 --image-project debian-cloud \
  --boot-disk-size 30GB --boot-disk-type pd-standard \
  --address "$IP" --tags kaaran-web \
  --metadata "kaaran-domain=$DUCK.duckdns.org" \
  --metadata-from-file "$FROM_FILES"

cat <<DONE

Done. The server is at $IP and is now installing Kaaran by itself (10-20 minutes).

Watch it:   gcloud compute ssh $VM --zone $ZONE --command 'sudo tail -f /var/log/kaaran-setup.log'
When it says "done", this should answer:   https://$DUCK.duckdns.org/health

Last step, on GitHub (repository Settings):
  1. Secrets and variables -> Actions -> Variables -> New: KAARAN_BACKEND_URL = https://$DUCK.duckdns.org
  2. Pages -> Source: GitHub Actions
  3. Actions -> "Deploy to GitHub Pages" -> Run workflow
DONE
