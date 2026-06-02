# Frappe Docker Automation (FDA)

An interactive CLI wizard for deploying and managing Frappe / ERPNext on Docker — from a single local dev stack to a full production setup with Traefik, MariaDB/PostgreSQL, multi-bench, and S3 backups.

## Requirements

- Python 3.8+
- Docker (can be installed via option 1)
- Git
- `openssl` (required for Traefik password hashing)

Tested on **Ubuntu 22.04+** and **macOS 13+**.

## Quick Start

```bash
git clone https://github.com/sankarprakash66/frappe_docker_automate
cd frappe_docker_automate
python3 fda_script.py
```

No pip dependencies — uses only the Python standard library.

## Menu Overview

On launch the wizard displays a live status panel (OS, Docker, repo, Gitops, Traefik, MariaDB, PostgreSQL) followed by the numbered menu.

```
╔══════════════════════════════════════════════════════╗
║      Frappe / ERPNext Docker Deployment Wizard       ║
╚══════════════════════════════════════════════════════╝
```

### Setup

| # | Option | Description |
|---|--------|-------------|
| 1 | Install Docker & Docker Compose | Runs the official Docker install script (Linux) or installs via Homebrew (macOS) |
| 2 | Set active frappe_docker repo | Clone or navigate to an existing `frappe_docker` repo — required before most other options |

---

### Local Deploy (pwd.yml)

Spins up the entire Frappe stack locally using `pwd.yml` — ideal for development and testing.

| # | Option | Description |
|---|--------|-------------|
| 3 | Local deploy via pwd.yml | Choose a local or remote Frappe image, configure site/DB settings, and start the stack on `http://localhost:8080` |
| 4 | Local deploy status & diagnostics | Show container states, `create-site` logs, backend errors, and offer automated fix suggestions |
| 5 | Stop local deploy | Stop containers while preserving all volumes and data |
| 6 | Drop local deploy | Stop-only, remove containers+network (keep volumes), or full drop with data deletion |

---

### Live Infrastructure

Persistent shared services for production multi-bench deployments.

| # | Option | Description |
|---|--------|-------------|
| 7  | Setup Traefik reverse proxy | Configure Traefik domain, dashboard password, and optional Let's Encrypt SSL |
| 8  | Setup shared MariaDB database | Start a shared MariaDB instance on `mariadb-network` |
| 9  | Setup shared PostgreSQL database | Start a shared PostgreSQL instance on `postgres-network` |
| 10 | Restart infrastructure servers | Restart Traefik, MariaDB, and/or PostgreSQL from saved `.env` files |
| 11 | Drop infrastructure services | Stop and optionally delete volumes for any infrastructure service |

---

### Live Bench & Sites

| # | Option | Description |
|---|--------|-------------|
| 12 | Deploy Frappe / ERPNext bench | Create a per-bench `.env` and resolved compose YAML; supports MariaDB/PostgreSQL, SSL, custom images |
| 13 | Create a new site | `bench new-site` with DB setup, `bench use`, migrate, and cache clear |
| 14 | Install an app on a site | `bench install-app` followed by `bench migrate` |
| 15 | Uninstall an app from a site | `bench uninstall-app` followed by `bench migrate` |

---

### Live Site Operations

| # | Option | Description |
|---|--------|-------------|
| 16 | Migrate site | Run pending database migrations (`bench migrate`) |
| 17 | Clear site cache | Clear Redis and website cache (`bench clear-cache`) |
| 18 | Set maintenance mode | Take a site offline or bring it back online |
| 19 | Enable / Disable scheduler | Pause or resume background jobs (email, reports, auto-backups) |
| 20 | Drop / Delete a site | `bench drop-site` — permanently removes site database and files |
| 21 | Restore site from backup | Restore from a `.sql.gz` backup inside the backend container |

---

### Images

| # | Option | Description |
|---|--------|-------------|
| 22 | View Docker images | List Frappe/ERPNext images, all images, or search by name; optionally remove |
| 23 | Create custom image | Build a new image from `apps.json` using `images/custom/` or `images/layered/` Containerfile; supports multi-platform `linux/amd64,linux/arm64` via `buildx` |
| 24 | Update image with latest git code | Rebuild an existing image with `--no-cache` so every app is freshly cloned |

---

### Management

| # | Option | Description |
|---|--------|-------------|
| 25 | Update bench (pull → restart → migrate) | 4-step update: pull image → patch YAML → restart services → migrate all sites |
| 26 | Stop a bench | `docker compose down` for a named bench project |
| 27 | View running containers | `docker ps` with name, status, and ports |
| 28 | View container logs | Tail logs for any project/service |
| 29 | Backup all sites | `bench --all-sites backup --with-files` |
| 30 | Push backup to S3 storage | Backup all sites then sync `private/backups/` to any S3-compatible bucket |
| 31 | Bench console (Python shell) | Interactive `bench console` inside a running container |
| 32 | Clean volumes, networks & build cache | Prune unused volumes (⚠ data loss), networks, build cache, and/or images |

---

## Directory Layout

```
~/gitops/              ← env files and resolved compose YAMLs (created automatically)
  traefik.env
  mariadb.env
  postgres.env
  <project>.env
  <project>.yaml

~/frappe_docker/       ← cloned frappe_docker repo (set via option 2)
  pwd.yml              ← used by local deploy options
  compose.yaml
  overrides/
  development/
    apps.json          ← generated by "Create custom image"
```

## Custom Image Build

Option 23 walks you through building a Frappe image with your own apps:

1. Enter image name/tag (e.g. `myorg/frappe:v15.0.0`)
2. Choose Frappe branch and git URL
3. Select build type: `custom` (full build) or `layered` (faster, needs frappe/build base)
4. Set Python and Node versions
5. Add apps interactively — each entry needs a git URL and branch
6. Optionally build for `linux/amd64,linux/arm64` with `docker buildx`

The `apps.json` is passed as both a Docker build secret and a `APPS_JSON_BASE64` build arg for compatibility with all Containerfile variants.

## S3 Backup

Option 30 supports AWS S3, MinIO, Backblaze B2, and any S3-compatible endpoint. It installs `awscli` inside the backend container and syncs `sites/*/private/backups/` to the chosen bucket prefix.

## Platform Notes

- **Linux** — Docker commands run with `sudo` where required.
- **macOS** — Docker Desktop runs rootless; `sudo` is omitted automatically.

## License

MIT
