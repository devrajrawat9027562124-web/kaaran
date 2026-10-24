# Deploying Kaaran so it runs all the time

The website already runs on GitHub Pages. This guide puts the **backend** (accounts and saved programs, C/C++ runs, the explainer) on a Google Cloud VM that is always on, so students can sign up and log in at any time, not only while your laptop is running.

```
Students' browsers
   ├── the website ─────────────── GitHub Pages (as now)
   └── https://YOUR-DOMAIN ──────► Google Compute Engine VM
                                     ├── Caddy: HTTPS (free certificate, renewed by itself)
                                     ├── Kaaran backend: a system service, started at boot,
                                     │     restarted if it stops
                                     │     └── /var/lib/kaaran/kaaran.db   accounts + saved programs
                                     ├── Docker: one locked-down container per C/C++ run
                                     └── daily backup → /var/backups/kaaran (newest 14 kept)
```

**Why a VM and not Cloud Run:** Cloud Run wipes its disk whenever it restarts a container, which would delete every account, and it can't start the Docker containers that C/C++ runs need. A VM is an ordinary always-on Linux machine, so Kaaran runs on it unchanged.

Commands below are typed in the VM's terminal (the **SSH** button in the Google Cloud console). Replace `YOUR-DOMAIN` with your domain everywhere.

## 1. Create the VM

In the [Google Cloud console](https://console.cloud.google.com/), create a project and turn on billing (new accounts usually get trial credit; check the current offer).

Compute Engine → VM instances → **Create instance**:

| Setting | Choose | Why |
|---|---|---|
| Region | `asia-south1` (Mumbai) or `asia-south2` (Delhi) for students in India | Faster for them. Google's always-free `e2-micro` has been offered only in some US regions: check the current free-tier terms if cost matters most. |
| Machine type | `e2-small` (2 GB) | `e2-micro` (1 GB) works for a demo: set `KAARAN_PARALLEL_RUNS=2` (the default in the template) |
| Boot disk | **Debian 12** or **Ubuntu 24.04 LTS**, 20 GB | Kaaran needs Python 3.11 or newer; both have it |
| Firewall | Tick **Allow HTTP traffic** and **Allow HTTPS traffic** | Caddy needs ports 80 and 443 |

Then:
- **Keep its address fixed:** VPC network → IP addresses → find the VM's external address → **Reserve** (make it static). Otherwise it can change when the VM restarts, and your domain would point nowhere.
- **Snapshots of the whole disk** (second line of backup): Compute Engine → Snapshots → **Create snapshot schedule** (daily, keep 7), then attach it to the VM's boot disk.

## 2. A domain name

HTTPS needs a domain. At your domain provider, add an **A record** pointing to the VM's static address. A free option is a DuckDNS subdomain (`yourname.duckdns.org`). Wait until `ping YOUR-DOMAIN` shows the VM's address.

## 3. Install the software

```
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3-venv docker.io caddy unattended-upgrades
```

(If `caddy` isn't found, add Caddy's own package source: https://caddyserver.com/docs/install.) `unattended-upgrades` installs security updates by itself.

## 4. Get Kaaran and set it up

```
sudo useradd --system --no-create-home --shell /usr/sbin/nologin kaaran
sudo git clone https://github.com/devrajrawat9027562124-web/kaaran.git /opt/kaaran
cd /opt/kaaran
sudo python3 -m venv backend/.venv
sudo backend/.venv/bin/pip install -r backend/requirements.txt
sudo docker build -t kaaran-runner backend/runner
```

The settings file (the server's own `.env`):

```
sudo cp deploy/production.env.example backend/.env
sudo nano backend/.env
sudo chown root:kaaran backend/.env && sudo chmod 640 backend/.env
sudo install -d -o kaaran -g kaaran -m 700 /var/backups/kaaran
```

In `nano`, check `ALLOWED_ORIGINS` is your Pages address, and add `ANTHROPIC_API_KEY` only if you want "Explain this step" (it's billed to you). Save with Ctrl+O, Enter, Ctrl+X. `KAARAN_SANDBOX` must stay `docker`: `local` would run students' code directly on the server.

## 5. Start the backend (and keep it running)

```
sudo cp deploy/kaaran.service deploy/kaaran-backup.service deploy/kaaran-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kaaran kaaran-backup.timer
curl http://127.0.0.1:8000/health
```

The last line should print `{"ok":true,"sandbox":"docker",...,"accounts":true}`. `enable` makes it start at every boot; the service restarts it within 3 seconds if it ever stops.

## 6. Turn on HTTPS

```
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo sed -i 's/kaaran.example.com/YOUR-DOMAIN/' /etc/caddy/Caddyfile
sudo systemctl reload caddy
curl https://YOUR-DOMAIN/health
```

Caddy gets the certificate on the first request (a few seconds) and renews it by itself.

## 7. Point the website at the backend

On GitHub, in the repository:
1. **Settings → Secrets and variables → Actions → Variables → New repository variable**: name `KAARAN_BACKEND_URL`, value `https://YOUR-DOMAIN` (no `/` at the end).
2. **Settings → Pages → Source: GitHub Actions** (if not done yet).
3. **Actions → Deploy to GitHub Pages → Run workflow.**

Then open `https://devrajrawat9027562124-web.github.io/kaaran/`, sign up, save a program, and run a C example. All of it now goes to the VM.

## Looking after it

| To | Run (on the VM) |
|---|---|
| See the accounts | `sudo -u kaaran /opt/kaaran/backend/.venv/bin/python /opt/kaaran/backend/show_users.py` |
| See what the backend is doing | `journalctl -u kaaran -f` (Ctrl+C to stop watching) |
| Check it's running | `systemctl status kaaran` |
| List backups | `sudo ls -l /var/backups/kaaran` |
| Back up now | `sudo systemctl start kaaran-backup` |
| Install a new version | `cd /opt/kaaran && sudo git pull && sudo backend/.venv/bin/pip install -r backend/requirements.txt && sudo docker build -t kaaran-runner backend/runner && sudo systemctl restart kaaran` |

**Restoring a backup** (replaces the current accounts with the backup's):

```
sudo systemctl stop kaaran
sudo cp /var/backups/kaaran/kaaran-DATE.db /var/lib/kaaran/kaaran.db
sudo chown kaaran:kaaran /var/lib/kaaran/kaaran.db
sudo systemctl start kaaran
```

The daily backups are on the same disk as the database, so they protect against mistakes, not against losing the VM; the disk snapshots from step 1 cover that. For a copy outside Google Cloud, download one now and then with the SSH window's **Download file** button.

## What the data looks like on the server

Everything is in `/var/lib/kaaran/kaaran.db`, readable only by the `kaaran` service user. Passwords are stored only as salted scrypt hashes and login tokens only as SHA-256 hashes (see `docs/design.md`, section 6). Accounts don't expire: a student can log in again whenever they like. After 14 days without logging out, they just type their password again.

## If something goes wrong

- `curl http://127.0.0.1:8000/health` fails: `journalctl -u kaaran -n 50` shows why (often a typo in `.env`).
- The HTTPS step fails: the domain doesn't point at the VM yet, or ports 80/443 aren't open (step 1, Firewall). `journalctl -u caddy -n 50` says which.
- The site says the backend isn't reachable: check `KAARAN_BACKEND_URL` (step 7) and `ALLOWED_ORIGINS` (step 4), then run the Pages workflow again.
- C/C++ runs fail: `sudo docker images` should list `kaaran-runner`; if not, repeat the `docker build` line.

This guide was written for this repository but not tried on a real Google Cloud VM: if a step behaves differently, the logs above will say why.
