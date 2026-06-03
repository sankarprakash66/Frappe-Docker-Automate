#!/usr/bin/env python3
"""
Frappe Docker Deployment Tool
Interactive CLI to deploy and manage Frappe/ERPNext on Docker.
"""

import base64
import getpass
import json
import os
import platform as _platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ── Terminal colors ───────────────────────────────────────────────────────────

USE_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(text, code):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def bold(t):    return _c(t, "1")
def green(t):   return _c(t, "32")
def yellow(t):  return _c(t, "33")
def red(t):     return _c(t, "31")
def cyan(t):    return _c(t, "36")
def dim(t):     return _c(t, "2")

# ── Constants ─────────────────────────────────────────────────────────────────

GITOPS    = Path.home() / "gitops"
IS_MACOS  = _platform.system() == "Darwin"
IS_LINUX  = _platform.system() == "Linux"

# ── Output helpers ────────────────────────────────────────────────────────────


def banner(title: str):
    line = cyan("─" * 60)
    print(f"\n{line}\n  {bold(title)}\n{line}")


def success(msg):  print(green(f"  ✔  {msg}"))
def warn(msg):     print(yellow(f"  ⚠  {msg}"))
def error(msg):    print(red(f"  ✖  {msg}"))
def info(msg):     print(dim(f"  →  {msg}"))

# ── Input helpers ─────────────────────────────────────────────────────────────


def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    raw = input(f"  {bold('?')} {prompt}{hint}: ").strip()
    return raw if raw else default


def ask_password(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    try:
        raw = getpass.getpass(f"  {bold('?')} {prompt}{hint}: ").strip()
    except Exception:
        raw = input(f"  {bold('?')} {prompt}{hint}: ").strip()
    return raw if raw else default


def confirm(prompt: str, default: bool = False) -> bool:
    choices = "Y/n" if default else "y/N"
    raw = input(f"  {bold('?')} {prompt} ({choices}): ").strip().lower()
    return default if not raw else raw.startswith("y")


def validate_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def validate_domain(domain: str) -> bool:
    return bool(re.match(r"^[a-zA-Z0-9._-]+\.[a-zA-Z]{2,}$", domain))

# ── Shell helpers ─────────────────────────────────────────────────────────────


def _sudo() -> str:
    """Return 'sudo ' on Linux. macOS Docker Desktop runs rootless — no sudo needed."""
    return "sudo " if IS_LINUX else ""


def run(cmd: str, cwd: str = None, silent: bool = False) -> bool:
    """Run a shell command with live output. Return True on success."""
    if not silent:
        info(cmd[:110] + ("…" if len(cmd) > 110 else ""))
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd,
            stdout=subprocess.DEVNULL if silent else None,
            stderr=subprocess.DEVNULL if silent else None,
        )
        return result.returncode == 0
    except KeyboardInterrupt:
        warn("Interrupted.")
        return False


def run_stream(cmd: str, cwd: str = None, silent: bool = False) -> bool:
    """Run a command and print each output line live with a log prefix. Return True on success."""
    if not silent:
        info(cmd[:110] + ("…" if len(cmd) > 110 else ""))
    try:
        proc = subprocess.Popen(
            cmd, shell=True, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in proc.stdout:
            if not silent:
                print(f"  {dim('│')} {line.rstrip()}")
        proc.wait()
        return proc.returncode == 0
    except KeyboardInterrupt:
        proc.terminate()
        warn("Interrupted.")
        return False


def run_capture(cmd: str) -> str:
    """Return stdout of a command, or empty string on failure."""
    try:
        return subprocess.check_output(
            cmd, shell=True, stderr=subprocess.DEVNULL, text=True
        ).strip()
    except subprocess.CalledProcessError:
        return ""

# ── Guards ────────────────────────────────────────────────────────────────────


def require_docker() -> bool:
    if not shutil.which("docker"):
        error("Docker not found. Run option 1 to install it first.")
        return False
    return True


def repo_is_ready() -> bool:
    """Return True when the CWD looks like a valid frappe_docker repo."""
    return (Path(os.getcwd()) / "compose.yaml").exists()


def require_repo() -> bool:
    if not repo_is_ready():
        error("compose.yaml not found in the current directory.")
        info("Run option 2 to navigate to the frappe_docker repo first.")
        return False
    return True


def ensure_gitops():
    GITOPS.mkdir(parents=True, exist_ok=True)


def list_bench_projects() -> list:
    if not GITOPS.exists():
        return []
    skip = {"traefik", "mariadb", "postgres"}
    return [f.stem for f in GITOPS.glob("*.env") if f.stem not in skip]


def _container_running(project: str) -> bool:
    """Return True if at least one container for the given compose project is running."""
    if not shutil.which("docker"):
        return False
    out = run_capture(
        f"docker ps --filter 'label=com.docker.compose.project={project}'"
        f" --format '{{{{.Names}}}}'"
    )
    return bool(out.strip())

# ── Action functions ──────────────────────────────────────────────────────────


def _latest_compose_version() -> str:
    """Fetch latest Docker Compose release tag via GitHub API (pure Python, no grep -P)."""
    resp = run_capture("curl -s https://api.github.com/repos/docker/compose/releases/latest")
    if resp:
        try:
            return json.loads(resp).get("tag_name", "") or "v2.27.0"
        except (json.JSONDecodeError, KeyError):
            pass
    return "v2.27.0"


def install_docker():
    banner("Install Docker & Docker Compose")
    if shutil.which("docker"):
        warn("Docker is already installed: " + run_capture("docker --version"))
        if not confirm("Re-install / update anyway?"):
            return

    if IS_MACOS:
        _install_docker_macos()
    else:
        _install_docker_linux()


def _install_docker_macos():
    print()
    print(f"  {bold('macOS detected — Docker Desktop is the recommended install.')}")
    print()
    print(f"  {bold('1.')} {cyan('Homebrew')}       {dim('(automated, recommended)')}")
    print(f"       brew install --cask docker")
    print(f"  {bold('2.')} {cyan('Manual download')} {dim('(Docker Desktop .dmg)')}")
    print(f"       https://www.docker.com/products/docker-desktop/")
    print()

    if shutil.which("brew"):
        choice = ask("Install via Homebrew? [y/n]", "y").lower()
        if choice.startswith("y"):
            if run("brew install --cask docker"):
                success("Docker Desktop installed.")
                info("Open Docker Desktop from Applications to finish setup, then re-run this script.")
            else:
                error("Homebrew install failed.")
                info("Try the manual download: https://www.docker.com/products/docker-desktop/")
        else:
            info("Download Docker Desktop from: https://www.docker.com/products/docker-desktop/")
    else:
        warn("Homebrew not found.")
        info("Install Homebrew first (https://brew.sh), then re-run, or download Docker Desktop manually.")
        info("Docker Desktop: https://www.docker.com/products/docker-desktop/")


def _install_docker_linux():
    if not confirm("This runs the official Docker install script as root. Continue?", default=True):
        return
    if not run("curl -fsSL https://get.docker.com | bash"):
        error("Docker install failed.")
        return

    cli_plugins = Path.home() / ".docker" / "cli-plugins"
    cli_plugins.mkdir(parents=True, exist_ok=True)
    compose_bin = cli_plugins / "docker-compose"

    latest = _latest_compose_version()
    arch   = run_capture("uname -m") or "x86_64"
    url    = f"https://github.com/docker/compose/releases/download/{latest}/docker-compose-linux-{arch}"
    info(f"Installing Docker Compose {latest} …")
    if run(f"curl -SL '{url}' -o '{compose_bin}' && chmod +x '{compose_bin}'"):
        success("Done.")
        run("docker --version && docker compose version")
    else:
        error("Docker Compose install failed.")


def clone_or_navigate_repo():
    banner("Clone / Navigate to frappe_docker Repo")

    # Search common locations for an existing frappe_docker folder
    search_roots = [Path.cwd(), Path.home(), Path("/opt"), Path("/srv")]
    found: list[Path] = []
    for root in search_roots:
        candidate = root / "frappe_docker"
        if candidate.is_dir() and (candidate / "compose.yaml").exists():
            if candidate not in found:
                found.append(candidate)

    if found:
        print()
        print(f"  {bold('Existing frappe_docker folder(s) found:')}")
        for i, p in enumerate(found, 1):
            remote = run_capture(f"git -C {p} remote get-url origin 2>/dev/null") or "—"
            branch = run_capture(f"git -C {p} rev-parse --abbrev-ref HEAD 2>/dev/null") or "—"
            print(f"  {bold(str(i))}. {cyan(str(p))}")
            print(f"       remote : {remote}")
            print(f"       branch : {branch}")
        print(f"  {bold(str(len(found) + 1))}. Clone a fresh copy")
        print(f"  {bold(str(len(found) + 2))}. Enter a custom path manually")
        print()

        choice = ask(f"Choose [1-{len(found) + 2}]", "1")

        if choice.isdigit() and 1 <= int(choice) <= len(found):
            repo_path = found[int(choice) - 1]
            os.chdir(repo_path)
            ensure_gitops()
            success(f"Using existing repo : {repo_path}")
            success(f"Gitops directory    : {GITOPS}")
            return

        if choice == str(len(found) + 2):
            # Fall through to custom-path prompt below
            custom = ask("Enter full path to frappe_docker repo")
            if not custom or not Path(custom).is_dir():
                error("Directory not found.")
                return
            os.chdir(custom)
            ensure_gitops()
            success(f"Repo directory   : {os.getcwd()}")
            success(f"Gitops directory : {GITOPS}")
            return

        # choice == len(found)+1  →  clone fresh copy (fall through)

    # ── Clone fresh ───────────────────────────────────────────────────────────
    url       = ask("Repository URL", "https://github.com/frappe/frappe_docker")
    clone_dir = ask("Clone into folder name", "frappe_docker")

    target = Path(clone_dir)
    if target.exists():
        warn(f"Folder '{clone_dir}' already exists.")
        if confirm(f"Use the existing '{clone_dir}' without re-cloning?", default=True):
            os.chdir(target)
            ensure_gitops()
            success(f"Repo directory   : {os.getcwd()}")
            success(f"Gitops directory : {GITOPS}")
            return
        if not confirm("Delete and re-clone?"):
            return
        shutil.rmtree(target)

    if not run(f"git clone {url} {clone_dir}"):
        error("Clone failed.")
        return

    os.chdir(clone_dir)
    ensure_gitops()
    success(f"Repo directory   : {os.getcwd()}")
    success(f"Gitops directory : {GITOPS}")


def create_traefik_env():
    banner("Setup Traefik Reverse Proxy")
    if not require_docker():
        return
    ensure_gitops()

    domain = ask("Traefik dashboard domain", "traefik.example.com")
    if not validate_domain(domain):
        warn("Domain looks unusual, proceeding anyway.")
    email = ask("Admin e-mail", "admin@example.com")
    password = ask_password("Dashboard password", "changeit")

    info("Hashing password …")
    hashed = run_capture(f"openssl passwd -apr1 '{password}' | sed -e 's/\\$/\\$\\$/g'")
    if not hashed:
        error("openssl not found or hashing failed.")
        return

    env_path = GITOPS / "traefik.env"
    env_path.write_text(f"TRAEFIK_DOMAIN={domain}\nEMAIL={email}\nHASHED_PASSWORD={hashed}\n")
    info(f"Wrote {env_path}")

    ssl = confirm("Enable HTTPS with Let's Encrypt?", default=True)
    files = "-f overrides/compose.traefik.yaml"
    if ssl:
        files += " -f overrides/compose.traefik-ssl.yaml"

    if run(f"docker compose --project-name traefik --env-file {env_path} {files} up -d"):
        success("Traefik is running.")
        info(f"Dashboard → http{'s' if ssl else ''}://{domain}")
    else:
        error("Traefik failed to start.")


def create_mariadb_env():
    banner("Setup Shared MariaDB Database")
    if not require_docker():
        return
    ensure_gitops()

    db_pass = ask_password("MariaDB root password", "changeit")
    env_path = GITOPS / "mariadb.env"
    env_path.write_text(f"DB_PASSWORD={db_pass}\n")
    info(f"Wrote {env_path}")

    if run(f"docker compose --project-name mariadb --env-file {env_path} -f overrides/compose.mariadb-shared.yaml up -d"):
        success("MariaDB is running on network: mariadb-network")
    else:
        error("MariaDB failed to start.")


def create_postgres_env():
    banner("Setup Shared PostgreSQL Database")
    if not require_docker():
        return
    ensure_gitops()

    db_pass = ask_password("PostgreSQL password", "changeit")
    env_path = GITOPS / "postgres.env"
    env_path.write_text(f"DB_PASSWORD={db_pass}\n")
    info(f"Wrote {env_path}")

    if run(f"docker compose --project-name postgres --env-file {env_path} -f overrides/compose.postgres-shared.yaml up -d"):
        success("PostgreSQL is running on network: postgres-network")
    else:
        error("PostgreSQL failed to start.")


def create_bench_env():
    banner("Deploy Frappe / ERPNext Bench")
    if not require_docker():
        return
    ensure_gitops()

    example_env = Path(os.getcwd()) / "example.env"
    if not example_env.exists():
        error(f"example.env not found in {os.getcwd()}")
        return

    project = ask("Project / bench name", "erpnext-one")

    db_type = ask("Database type [mariadb/postgres]", "mariadb").lower()
    if db_type not in ("mariadb", "postgres"):
        warn("Unknown type, defaulting to mariadb.")
        db_type = "mariadb"

    db_pass = ask_password("DB password", "changeit")
    if db_type == "mariadb":
        db_host = ask("DB_HOST", "mariadb-database")
        db_port = ask("DB_PORT", "3306")
    else:
        db_host = ask("DB_HOST", "postgres-database")
        db_port = ask("DB_PORT", "5432")

    le_email = ask("Let's Encrypt email", "admin@example.com")
    if not validate_email(le_email):
        warn("Email looks invalid, proceeding anyway.")

    sites_raw = ask("Site domain(s), comma-separated", "one.example.com")
    sites = ",".join(f"`{s.strip().strip('`')}`" for s in sites_raw.split(","))

    ssl = confirm("Enable HTTPS with Let's Encrypt?", default=True)

    use_custom = confirm("Use a custom Docker image?", default=False)
    custom_image = ask("Custom image (e.g. tridotstech/frappe:v15)", "") if use_custom else ""

    # Build env file from example.env using regex substitution
    text = example_env.read_text()
    for pattern, value in [
        (r"^DB_PASSWORD=.*",       f"DB_PASSWORD={db_pass}"),
        (r"^DB_HOST=.*",           f"DB_HOST={db_host}"),
        (r"^DB_PORT=.*",           f"DB_PORT={db_port}"),
        (r"^LETSENCRYPT_EMAIL=.*", f"LETSENCRYPT_EMAIL={le_email}"),
        (r"^SITES=.*",             f"SITES={sites}"),
    ]:
        text = re.sub(pattern, value, text, flags=re.MULTILINE)
    text += f"\nROUTER={project}\nBENCH_NETWORK={project}\n"

    env_path = GITOPS / f"{project}.env"
    env_path.write_text(text)
    info(f"Wrote {env_path}")

    # Compose file list
    files = "-f compose.yaml -f overrides/compose.redis.yaml -f overrides/compose.multi-bench.yaml"
    if ssl:
        files += " -f overrides/compose.multi-bench-ssl.yaml"
    if db_type == "postgres":
        files += " -f overrides/compose.postgres.yaml"

    yaml_path = GITOPS / f"{project}.yaml"
    info("Generating resolved compose config …")
    if not run(f"docker compose --project-name {project} --env-file {env_path} {files} config > {yaml_path}"):
        error("Failed to generate compose config.")
        return

    if custom_image:
        info(f"Patching image → {custom_image}")
        patched = re.sub(
            r"^(\s+)image:.*",
            lambda m: f"{m.group(1)}image: {custom_image}",
            yaml_path.read_text(),
            flags=re.MULTILINE,
        )
        yaml_path.write_text(patched)

    if run(f"docker compose --project-name {project} -f {yaml_path} up -d"):
        success(f"Bench '{project}' is running.")
        info("Next: create a site with option 7.")
    else:
        error("Bench failed to start. Check: docker compose logs")


def _get_traefik_domains_from_yaml(yaml_path: Path) -> list:
    """Return domains currently listed in the first Traefik Host() rule found in the YAML."""
    if not yaml_path.exists():
        return []
    m = re.search(
        r'traefik\.http\.routers\.[^.]+\.rule:\s*["\']?Host\(([^)]+)\)',
        yaml_path.read_text(),
    )
    return re.findall(r'`([^`]+)`', m.group(1)) if m else []


def _update_traefik_host_rule(yaml_path: Path, new_domain: str) -> bool:
    """Add *new_domain* to every Traefik Host() rule in yaml_path (http + https routers).
    Returns True if the file was changed, False if domain already present or file missing."""
    if not yaml_path.exists():
        return False
    text = yaml_path.read_text()
    changed = False

    def _add_if_missing(m):
        nonlocal changed
        existing = re.findall(r'`([^`]+)`', m.group(2))
        if new_domain in existing:
            return m.group(0)
        existing.append(new_domain)
        changed = True
        return m.group(1) + ",".join(f"`{d}`" for d in existing) + m.group(3)

    updated = re.sub(
        r'(traefik\.http\.routers\.[^.]+\.rule:\s*["\']?Host\()([^)]+)(\)["\']?)',
        _add_if_missing,
        text,
    )
    if changed:
        yaml_path.write_text(updated)
    return changed


def create_bench_site():
    banner("Create a New Frappe Site")
    if not require_docker():
        return

    projects = list_bench_projects()
    if projects:
        info("Known projects: " + ", ".join(projects))

    project   = ask("Project name", "erpnext-one")
    yaml_path = GITOPS / f"{project}.yaml"

    # Show domains already registered in this project's Traefik routing
    existing_domains = _get_traefik_domains_from_yaml(yaml_path)
    if existing_domains:
        print()
        print(f"  {bold('Existing site domain(s) in this project:')}")
        for d in existing_domains:
            print(f"  {dim('  •')} {cyan(d)}")
        print()

    site = ask("Site domain (must match your SITES setting)")
    if not site:
        error("Site name cannot be empty.")
        return
    if not validate_domain(site):
        warn("Site name looks unusual, proceeding anyway.")

    db_root_pass  = ask_password("DB root password", "changeit")
    admin_pass    = ask_password("Site admin password", "changeit")

    info("Creating site … (this may take a minute)")
    ok = run(
        f"docker compose --project-name {project} exec backend bench new-site"
        f" --mariadb-user-host-login-scope=%"
        f" --db-root-password {db_root_pass}"
        f" --admin-password {admin_pass}"
        f" {site}"
    )
    if not ok:
        error("Site creation failed.")
        return

    run(f"docker compose --project-name {project} exec backend bench use {site}")
    run(f"docker compose --project-name {project} exec backend bench migrate")
    run(f"docker compose --project-name {project} exec backend bench clear-cache")

    # Update Traefik Host rule in the project YAML to include the new domain
    if yaml_path.exists():
        if _update_traefik_host_rule(yaml_path, site):
            success(f"Traefik routing updated — '{site}' added to Host rule in {yaml_path.name}")
            info("Re-apply the compose file for routing to take effect:")
            info(f"  docker compose --project-name {project} -f {yaml_path} up -d")
        else:
            info(f"Traefik Host rule already includes '{site}' — no update needed.")
    else:
        warn(f"No YAML found at {yaml_path} — Traefik routing not updated.")

    success("Site is ready!")
    print(f"\n  {bold('URL:')}   https://{site}/app")
    print(f"  {bold('Login:')} Administrator / {admin_pass}\n")


def install_app():
    banner("Install an App on a Site")
    if not require_docker():
        return

    projects = list_bench_projects()
    if projects:
        info("Known projects: " + ", ".join(projects))

    project  = ask("Project name", "erpnext-one")
    site     = ask("Site name")
    app_name = ask("App name (e.g. erpnext, hrms, payments)")
    if not app_name:
        error("App name cannot be empty.")
        return

    if run(f"docker compose --project-name {project} exec backend bench --site {site} install-app {app_name}"):
        run(f"docker compose --project-name {project} exec backend bench --site {site} migrate")
        success(f"App '{app_name}' installed on {site}.")
    else:
        error("App installation failed.")


def stop_bench():
    banner("Stop a Bench")
    if not require_docker():
        return

    projects = list_bench_projects()
    if projects:
        info("Known projects: " + ", ".join(projects))

    project   = ask("Project name", "erpnext-one")
    yaml_path = GITOPS / f"{project}.yaml"

    cmd = f"docker compose --project-name {project}"
    cmd += f" -f {yaml_path}" if yaml_path.exists() else ""
    cmd += " down"

    if run(cmd):
        success(f"Bench '{project}' stopped.")
    else:
        error("Stop command failed.")


def restart_servers():
    banner("Restart Traefik & Database Servers")
    if not require_docker():
        return

    traefik_env  = GITOPS / "traefik.env"
    mariadb_env  = GITOPS / "mariadb.env"
    postgres_env = GITOPS / "postgres.env"

    if traefik_env.exists():
        info("Restarting Traefik …")
        run(f"docker compose --project-name traefik --env-file {traefik_env}"
            " -f overrides/compose.traefik.yaml -f overrides/compose.traefik-ssl.yaml restart")
        success("Traefik restarted.")
    else:
        warn(f"{traefik_env} not found — skipping Traefik.")

    if mariadb_env.exists():
        info("Restarting MariaDB …")
        run(f"docker compose --project-name mariadb --env-file {mariadb_env}"
            " -f overrides/compose.mariadb-shared.yaml restart")
        success("MariaDB restarted.")
    else:
        warn(f"{mariadb_env} not found — skipping MariaDB.")

    if postgres_env.exists():
        info("Restarting PostgreSQL …")
        run(f"docker compose --project-name postgres --env-file {postgres_env}"
            " -f overrides/compose.postgres-shared.yaml restart")
        success("PostgreSQL restarted.")


def local_status():
    banner("Local Deploy Status (pwd.yml)")
    if not require_docker():
        return

    pwd_yml = Path(os.getcwd()) / "pwd.yml"
    if not pwd_yml.exists():
        error("pwd.yml not found.")
        return

    # ── Container states ──────────────────────────────────────────────────────
    print()
    print(f"  {bold('Container states:')}")
    run(f"{_sudo()}docker compose -f pwd.yml ps")

    # ── create-site result ────────────────────────────────────────────────────
    print()
    print(f"  {bold('create-site logs')} {dim('(site creation result):')}")
    cs_logs = run_capture(f"{_sudo()}docker compose -f pwd.yml logs create-site 2>/dev/null")
    if cs_logs:
        for line in cs_logs.splitlines()[-15:]:
            # highlight key lines
            if "already exists" in line or "exit" in line.lower():
                print(f"  {yellow('⚠  ' + line.strip())}")
            elif "error" in line.lower() or "exception" in line.lower() or "traceback" in line.lower():
                print(f"  {red('✖  ' + line.strip())}")
            elif "Site" in line and "ready" in line.lower() or "successfully" in line.lower():
                print(f"  {green('✔  ' + line.strip())}")
            else:
                print(f"  {dim(line.strip())}")
    else:
        warn("No create-site logs found (container may not have run yet).")

    # ── backend errors ────────────────────────────────────────────────────────
    print()
    print(f"  {bold('Backend logs')} {dim('(last 10 lines):')}")
    be_logs = run_capture(f"{_sudo()}docker compose -f pwd.yml logs backend --tail=10 2>/dev/null")
    if be_logs:
        for line in be_logs.splitlines():
            if any(x in line for x in ("Error", "error", "Exception", "DoesNotExist", "not found")):
                print(f"  {red(line.strip())}")
            else:
                print(f"  {dim(line.strip())}")
    else:
        warn("No backend logs.")

    # ── Diagnose and suggest fix ──────────────────────────────────────────────
    print()
    if cs_logs and "already exists" in cs_logs:
        print(f"  {bold(yellow('⚠  Diagnosis:'))} Site already exists in volumes from a previous deploy.")
        print(f"  {dim('   The new image may not match the old site data → Internal Server Error.')}")
        print()
        print(f"  {bold('Fix options:')}")
        print(f"  {bold('1.')} {red('Fresh deploy')}  — wipe volumes and recreate site from scratch")
        print(f"  {bold('2.')} {yellow('Migrate only')} — keep data, run bench migrate to sync new image")
        print(f"  {bold('3.')} Skip — return to menu")
        print()
        fix = ask("Choose [1/2/3]", "1")
        if fix == "1":
            if confirm("This will DELETE all site data and the database. Continue?", default=False):
                info("Stopping stack and wiping volumes …")
                run(f"{_sudo()}docker compose -f pwd.yml down --volumes")
                info("Starting fresh …")
                if run(f"{_sudo()}docker compose -f pwd.yml up -d"):
                    success("Fresh deploy started.")
                    info(f"Watch site creation: {_sudo()}docker compose -f pwd.yml logs -f create-site")
                else:
                    error("Deploy failed.")
        elif fix == "2":
            info("Running bench migrate …")
            if run(f"{_sudo()}docker compose -f pwd.yml exec backend bench --site testing migrate"):
                run(f"{_sudo()}docker compose -f pwd.yml exec backend bench --site testing clear-cache")
                success("Migration complete. Refresh your browser.")
            else:
                error("Migration failed. Check backend logs.")
    elif be_logs and "not found" in be_logs.lower():
        print(f"  {bold(yellow('⚠  Diagnosis:'))} Backend module/app not found — image may be missing an app.")
        print(f"  {dim('   Ensure your image has all required apps installed.')}")
    else:
        success("No obvious errors detected. Stack looks healthy.")
        print(f"  {dim('   Access: http://localhost:8080')}")


def stop_local_deploy():
    banner("Stop Local Deploy (pwd.yml)")
    if not require_docker():
        return

    pwd_yml = Path(os.getcwd()) / "pwd.yml"
    if not pwd_yml.exists():
        error("pwd.yml not found.")
        return

    running = run_capture(f"{_sudo()}docker compose -f pwd.yml ps --filter status=running --format '{{.Name}}' 2>/dev/null")
    if not running:
        warn("No pwd.yml containers are currently running.")
        return

    print()
    print(f"  {bold('Containers that will be stopped:')}")
    for name in running.splitlines():
        print(f"  {dim('  • ' + name)}")
    print()
    info("Volumes and data will NOT be removed — you can restart anytime.")
    print()

    if not confirm("Stop all pwd.yml containers?", default=True):
        info("Cancelled.")
        return

    if run(f"{_sudo()}docker compose -f pwd.yml stop"):
        success("Local deploy stopped. Data is intact.")
        info(f"To restart: {_sudo()}docker compose -f pwd.yml start")
    else:
        error(f"Stop failed. Check: {_sudo()}docker compose -f pwd.yml ps")


def drop_local_deploy():
    banner("Drop Local Deploy (pwd.yml)")
    if not require_docker():
        return

    pwd_yml = Path(os.getcwd()) / "pwd.yml"
    if not pwd_yml.exists():
        error("pwd.yml not found.")
        return

    # ── Show what is running ──────────────────────────────────────────────────
    running = run_capture(f"{_sudo()}docker compose -f pwd.yml ps --format '{{.Name}}\t{{.Status}}' 2>/dev/null")
    if not running:
        warn("No pwd.yml containers are currently running.")
        return

    print()
    print(f"  {bold('Running containers that will be stopped:')}")
    for line in running.splitlines():
        print(f"  {dim('  ' + line)}")
    print()

    # ── Choose drop level ─────────────────────────────────────────────────────
    print(f"  {bold('Drop level:')}")
    print(f"  {bold('1.')} {yellow('Stop only')}       — stop containers, keep volumes & data intact")
    print(f"  {bold('2.')} {yellow('Stop + Remove')}   — remove containers & network, keep volumes (data safe)")
    print(f"  {bold('3.')} {red('Full drop')}        — remove everything: containers, network, {red('AND all volumes (data lost)')}")
    print()
    choice = ask("Choose [1/2/3]", "2")

    if choice == "1":
        if not confirm("Stop all pwd.yml containers?", default=True):
            info("Cancelled.")
            return
        if run(f"{_sudo()}docker compose -f pwd.yml stop"):
            success("Containers stopped. Data volumes are intact.")
        else:
            error("Stop failed.")

    elif choice == "2":
        if not confirm("Remove pwd.yml containers and network? (volumes kept)", default=True):
            info("Cancelled.")
            return
        if run(f"{_sudo()}docker compose -f pwd.yml down"):
            success("Containers and network removed. Volumes are intact.")
            info(f"Redeploy anytime with: {_sudo()}docker compose -f pwd.yml up -d")
        else:
            error("Down failed.")

    elif choice == "3":
        warn("This will permanently delete all site data, database, and logs.")
        if not confirm("Are you absolutely sure?", default=False):
            info("Cancelled.")
            return
        info("Stopping stack and removing volumes …")
        run(f"{_sudo()}docker compose -f pwd.yml down --volumes")
        # Also remove any orphan volumes left from older projects
        orphans = run_capture(
            "docker volume ls --format '{{.Name}}'"
            " | grep -E '^frappe_docker_(sites|db-data|redis-queue-data|logs)$'"
        )
        if orphans:
            info("Removing leftover orphan volumes …")
            for vol in orphans.splitlines():
                if run(f"docker volume rm {vol}"):
                    success(f"Removed volume: {vol}")
                else:
                    warn(f"Could not remove: {vol} (may still be in use)")
        success("Local deploy fully dropped. All data removed.")
    else:
        warn("Invalid choice.")


def local_deploy():
    banner("Local Deploy (pwd.yml)")
    if not require_docker() or not require_repo():
        return

    # ── Guard: block if a local deploy is already running ────────────────────
    pwd_yml = Path(os.getcwd()) / "pwd.yml"
    if pwd_yml.exists():
        running = run_capture(
            f"{_sudo()}docker compose -f pwd.yml ps --services --filter status=running 2>/dev/null"
        )
        if running:
            print()
            warn("A local deploy is already running.")
            info("Running services: " + ", ".join(running.splitlines()))
            print()
            print(f"  {dim('Stop it first, then re-deploy:')}")
            print(f"  {bold('  →')} Use {bold('Stop local deploy')}  to stop containers (data kept)")
            print(f"  {bold('  →')} Use {bold('Drop local deploy')}  to remove containers / volumes")
            print()
            return

    # ── What this does ────────────────────────────────────────────────────────
    print()
    print(f"  {bold('What is pwd.yml?')}")
    print(f"  {dim('  pwd.yml is a self-contained Docker Compose file for local / testing use.')}")
    print(f"  {dim('  It starts the entire Frappe stack in one command:')}")
    print(f"  {dim('    • backend, frontend (port 8080), workers, scheduler, websocket')}")
    print(f"  {dim('    • MariaDB 10.6  (internal, no external port)')}")
    print(f"  {dim('    • Redis cache + queue')}")
    print(f"  {dim('  All Frappe services share ONE image — you choose it here.')}")
    print(f"  {dim('  On first run a site is auto-created; on update your data is kept.')}")
    print()

    pwd_yml = Path(os.getcwd()) / "pwd.yml"
    if not pwd_yml.exists():
        error("pwd.yml not found in the current directory.")
        return

    text = pwd_yml.read_text()

    # ── Detect current Frappe image ───────────────────────────────────────────
    frappe_imgs = [
        img for img in re.findall(r"^\s+image:\s+(\S+)", text, re.MULTILINE)
        if not any(x in img for x in ("mariadb", "redis"))
    ]
    current_image = frappe_imgs[0] if frappe_imgs else ""
    if current_image:
        print(f"  {bold('Current image in pwd.yml:')} {cyan(current_image)}")
    print()

    # ── Let user pick / enter image ───────────────────────────────────────────
    local_imgs = [
        ln.strip()
        for ln in run_capture(
            "docker images --format '{{.Repository}}:{{.Tag}}'"
            " | grep -iE 'frappe|erpnext|hrms|tridots'"
        ).splitlines()
        if ln.strip()
    ]

    new_image = ""
    if local_imgs:
        print(f"  {bold('Local Frappe images found on this machine:')}")
        for i, img in enumerate(local_imgs, 1):
            tag = f"  {green('← currently in pwd.yml')}" if img == current_image else ""
            print(f"  {bold(str(i))}. {cyan(img)}{tag}")
        print(f"  {bold(str(len(local_imgs) + 1))}. Enter a different image manually")
        print()
        choice = ask(f"Choose [1-{len(local_imgs) + 1}]", "1")
        if choice.isdigit() and 1 <= int(choice) <= len(local_imgs):
            new_image = local_imgs[int(choice) - 1]
        else:
            new_image = ask("Image name:tag", current_image)
    else:
        warn("No local Frappe images found. You can still enter one (it will be pulled).")
        new_image = ask("Image name:tag (e.g. tridotstech/frappe:v15)", current_image)

    if not new_image:
        error("Image name cannot be empty.")
        return

    # ── Site / DB settings ────────────────────────────────────────────────────
    print()
    print(f"  {bold('Site & database settings')}")
    print(f"  {dim('  These configure the auto-created Frappe site.')}")
    print(f"  {dim('  On a fresh deploy they are used to create the site from scratch.')}")
    print(f"  {dim('  On an update deploy the site already exists — passwords are not changed.')}")
    print()

    # detect current site name from --set-default
    m = re.search(r"--set-default\s+(\S+)", text)
    cur_site = m.group(1).rstrip(";") if m else "frontend"

    # detect current apps from --install-app
    m2 = re.search(r"--install-app\s+(\S+)", text)
    cur_app = m2.group(1) if m2 else ""

    site_name  = ask("Site name", cur_site)
    db_pass    = ask_password("MariaDB root password", "admin")
    admin_pass = ask_password("Frappe admin password", "admin")

    print()
    print(f"  {bold('App to install on site creation:')}")
    print(f"  {dim('  This is the Frappe app installed when the site is created for the first time.')}")
    print(f"  {dim('  Leave empty to skip app installation (Frappe only).')}")
    install_app = ask("App name", cur_app)

    # ── Deploy mode ───────────────────────────────────────────────────────────
    print()
    print(f"  {bold('Deploy mode:')}")
    print(f"  {bold('1.')} {yellow('Fresh')}   — stops stack, {red('wipes all volumes')} (DB + sites), redeploys clean")
    print(f"  {bold('2.')} {green('Update')}  — keeps existing data, restarts services with the new image")
    print()
    mode  = ask("Choose [1/2]", "2")
    fresh = mode == "1"

    if fresh:
        warn("FRESH DEPLOY: all existing MariaDB data and Frappe sites will be deleted.")
        if not confirm("Are you absolutely sure?", default=False):
            info("Cancelled.")
            return

    # ── Patch pwd.yml ─────────────────────────────────────────────────────────
    # 1. Replace Frappe service images (leave mariadb / redis untouched)
    def _swap_image(m):
        img = m.group(2)
        if any(x in img for x in ("mariadb", "redis")):
            return m.group(0)
        return m.group(1) + new_image
    updated = re.sub(r"^(\s+image:\s+)(\S+)", _swap_image, text, flags=re.MULTILINE)

    # 2. Site name in create-site command
    updated = re.sub(r"(--set-default\s+)\S+", lambda m: m.group(1) + site_name + ";", updated)
    updated = re.sub(r"(FRAPPE_SITE_NAME_HEADER:\s*)\S+", lambda m: m.group(1) + site_name, updated)

    # 3. Passwords
    updated = re.sub(r"(--admin-password=)\S+", lambda m: m.group(1) + admin_pass, updated)
    updated = re.sub(r"(--db-root-password=)\S+", lambda m: m.group(1) + db_pass, updated)
    updated = re.sub(r"(MYSQL_ROOT_PASSWORD:\s*)\S+", lambda m: m.group(1) + db_pass, updated)
    updated = re.sub(r"(MARIADB_ROOT_PASSWORD:\s*)\S+", lambda m: m.group(1) + db_pass, updated)
    updated = re.sub(r"(--password=)\S+", lambda m: m.group(1) + db_pass, updated)

    # 4. App to install
    if install_app:
        updated = re.sub(r"(--install-app\s+)\S+", lambda m: m.group(1) + install_app, updated)
    else:
        # Remove --install-app flag entirely if user left it blank
        updated = re.sub(r"\s*--install-app\s+\S+", "", updated)

    # 5. Fix invalid restart policy — Docker rejects 'none', requires 'no'
    updated = re.sub(r"(restart:\s*)none\b", r'\1"no"', updated)

    pwd_yml.write_text(updated)
    success(f"pwd.yml updated.")

    # ── Summary panel ─────────────────────────────────────────────────────────
    print()
    print(f"  {dim('─' * 58)}")
    print(f"  {bold('Image       :')} {cyan(new_image)}")
    print(f"  {bold('Site name   :')} {site_name}")
    print(f"  {bold('App         :')} {install_app if install_app else dim('none')}")
    print(f"  {bold('DB password :')} {'*' * len(db_pass)}")
    print(f"  {bold('Mode        :')} {red('Fresh (volumes wiped)') if fresh else green('Update (data preserved)')}")
    print(f"  {bold('Access URL  :')} {cyan('http://localhost:8080')}")
    print(f"  {bold('Login       :')} Administrator / {admin_pass}")
    print(f"  {dim('─' * 58)}")
    print()

    if not confirm("Deploy now?", default=True):
        info("pwd.yml saved — run this option again to deploy when ready.")
        return

    # ── Deploy ────────────────────────────────────────────────────────────────
    if fresh:
        info("Removing existing stack and volumes …")
        run(f"{_sudo()}docker compose -f pwd.yml down --volumes")

    info("Starting stack …")
    if run(f"{_sudo()}docker compose -f pwd.yml up -d"):
        success("Stack is up!")

        # ── Post-deploy: set active site and run migrations ───────────────────
        project_name = Path(os.getcwd()).name  # e.g. "frappe_docker"

        time.sleep(10)
        info(f"Setting active site → {site_name} …")
        run(f"{_sudo()}docker compose --project-name {project_name} exec backend bench use {site_name}", silent=True)

        print()
        print(f"  {dim('─' * 58)}")
        print(f"  {bold('Running migrations')}  {dim('(this may take a few minutes …)')}")
        print(f"  {dim('─' * 58)}")
        time.sleep(10)
        ok = run_stream(f"{_sudo()}docker compose --project-name {project_name} exec backend bench --site {site_name} migrate", silent=True)
        print(f"  {dim('─' * 58)}")
        if ok:
            success("Migrations complete.")
        else:
            warn("Migration finished with errors — check the logs above.")

        print()
        print(f"  {bold('URL   :')} {cyan('http://localhost:8080')}")
        print(f"  {bold('Login :')} Administrator / {admin_pass}")
        print()
        info("On first run, site creation runs in the background (~2-3 min).")
        info(f"Watch progress: {_sudo()}docker compose -f pwd.yml logs -f create-site")
    else:
        error("Deploy failed.")
        info(f"Check logs: {_sudo()}docker compose -f pwd.yml logs")


def drop_infrastructure():
    banner("Drop Infrastructure Services")
    if not require_docker():
        return

    traefik_env  = GITOPS / "traefik.env"
    mariadb_env  = GITOPS / "mariadb.env"
    postgres_env = GITOPS / "postgres.env"

    services = []
    if traefik_env.exists():
        services.append(("Traefik",    "traefik",  traefik_env,
                         "-f overrides/compose.traefik.yaml -f overrides/compose.traefik-ssl.yaml"))
    if mariadb_env.exists():
        services.append(("MariaDB",    "mariadb",  mariadb_env,
                         "-f overrides/compose.mariadb-shared.yaml"))
    if postgres_env.exists():
        services.append(("PostgreSQL", "postgres", postgres_env,
                         "-f overrides/compose.postgres-shared.yaml"))

    if not services:
        warn("No infrastructure .env files found in gitops — nothing to drop.")
        return

    print()
    print(f"  {bold('Select services to drop:')}")
    for i, (name, _, _, _) in enumerate(services, 1):
        print(f"  {bold(str(i))}. {name}")
    print(f"  {bold(str(len(services) + 1))}. All of the above")
    print()

    choice = ask(f"Choose [1-{len(services) + 1}]", str(len(services) + 1))

    if choice.isdigit() and 1 <= int(choice) <= len(services):
        targets = [services[int(choice) - 1]]
    else:
        targets = services

    remove_volumes = confirm("Also remove volumes? (WARNING: deletes all data)", default=False)
    vol_flag = " --volumes" if remove_volumes else ""

    print()
    warn(f"This will stop and remove {', '.join(n for n, *_ in targets)}.")
    if not confirm("Proceed?", default=False):
        info("Cancelled.")
        return

    for name, project, env_file, files in targets:
        info(f"Dropping {name} …")
        if run(f"docker compose --project-name {project} --env-file {env_file} {files} down{vol_flag}"):
            success(f"{name} dropped.")
        else:
            error(f"Failed to drop {name}.")


def show_status():
    banner("Running Docker Containers")
    if not require_docker():
        return
    run("docker ps --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}'")


def show_logs():
    banner("View Container Logs")
    if not require_docker():
        return

    projects = list_bench_projects()
    if projects:
        info("Known projects: " + ", ".join(projects))

    project = ask("Project name (or 'traefik' / 'mariadb')")
    service = ask("Service (leave empty for all)", "")
    lines   = ask("Lines to show", "50")

    yaml_path = GITOPS / f"{project}.yaml"
    cmd = f"docker compose --project-name {project}"
    if yaml_path.exists():
        cmd += f" -f {yaml_path}"
    cmd += f" logs --tail={lines} {service}"
    run(cmd)


def backup_sites():
    banner("Backup All Sites")
    if not require_docker():
        return

    projects = list_bench_projects()
    if projects:
        info("Known projects: " + ", ".join(projects))

    project = ask("Project name", "erpnext-one")
    if run(f"docker compose --project-name {project} exec backend bench --all-sites backup --with-files"):
        success("Backup complete. Files are inside the sites volume.")
    else:
        error("Backup failed.")

def clean_docker():
    banner("Clean Docker — Volumes, Networks & Cache")
    if not require_docker():
        return

    print()
    print(f"  {bold('What this removes:')}")
    print(f"  {dim('  Volumes  — all unused named volumes (db-data, sites, logs, etc.)')}")
    print(f"  {dim('             ⚠  This permanently deletes all Frappe sites & database data.')}")
    print(f"  {dim('  Networks — all unused custom networks (frappe_network, etc.)')}")
    print(f"  {dim('  Cache    — Docker build cache (layer cache from docker build / buildx)')}")
    print(f"  {dim('  Stopped containers are removed automatically as part of each prune.')}")
    print()

    # ── Show current disk usage ───────────────────────────────────────────────
    usage = run_capture("docker system df 2>/dev/null")
    if usage:
        print(f"  {bold('Current Docker disk usage:')}")
        for line in usage.splitlines():
            print(f"  {dim(line)}")
        print()

    # ── Choose what to clean ─────────────────────────────────────────────────
    print(f"  {bold('Select what to clean:')}")
    print(f"  {bold('1.')} Volumes only")
    print(f"  {bold('2.')} Networks only")
    print(f"  {bold('3.')} Build cache only")
    print(f"  {bold('4.')} Volumes + Networks + Build cache  {dim('(full clean)')}")
    print(f"  {bold('5.')} Everything above + unused images  {dim('(deepest clean)')}")
    print()
    choice = ask("Choose [1-5]", "4")

    do_volumes  = choice in ("1", "4", "5")
    do_networks = choice in ("2", "4", "5")
    do_cache    = choice in ("3", "4", "5")
    do_images   = choice == "5"

    # ── Stop pwd.yml stack first if volumes are being wiped ───────────────────
    pwd_yml = Path(os.getcwd()) / "pwd.yml"
    if do_volumes and pwd_yml.exists():
        running = run_capture(
            f"{_sudo()}docker compose -f pwd.yml ps --services --filter status=running 2>/dev/null"
        )
        if running:
            warn("pwd.yml stack is running — it must be stopped before volumes can be removed.")
            if confirm("Stop the pwd.yml stack now?", default=True):
                run(f"{_sudo()}docker compose -f pwd.yml down")
            else:
                warn("Skipping volume cleanup (stack still running).")
                do_volumes = False

    # ── Final confirmation ────────────────────────────────────────────────────
    targets = []
    if do_volumes:  targets.append(red("all unused volumes (DATA LOSS)"))
    if do_networks: targets.append(yellow("unused networks"))
    if do_cache:    targets.append(yellow("build cache"))
    if do_images:   targets.append(yellow("unused images"))

    print()
    warn("About to remove: " + ", ".join(targets))
    if not confirm("Proceed?", default=False):
        info("Cancelled.")
        return

    # ── Execute ───────────────────────────────────────────────────────────────
    print()
    if do_volumes:
        info("Removing unused volumes …")
        if run("docker volume prune -f"):
            success("Volumes removed.")
        else:
            error("Volume prune failed.")

    if do_networks:
        info("Removing unused networks …")
        if run("docker network prune -f"):
            success("Networks removed.")
        else:
            error("Network prune failed.")

    if do_cache:
        info("Clearing build cache …")
        if run("docker builder prune -f"):
            success("Build cache cleared.")
        else:
            error("Cache prune failed.")

    if do_images:
        info("Removing unused images …")
        if run("docker image prune -f"):
            success("Unused images removed.")
        else:
            error("Image prune failed.")

    # ── Show reclaimed space ──────────────────────────────────────────────────
    print()
    after = run_capture("docker system df 2>/dev/null")
    if after:
        print(f"  {bold('Docker disk usage after clean:')}")
        for line in after.splitlines():
            print(f"  {dim(line)}")
    print()
    success("Cleanup complete.")


# ── Site Operations ───────────────────────────────────────────────────────────

def _pick_project_and_site(default_project="erpnext-one"):
    """Helper: ask for project + site and return (project, site)."""
    projects = list_bench_projects()
    if projects:
        info("Known projects: " + ", ".join(projects))
    project = ask("Project name", default_project)
    site    = ask("Site name")
    return project, site


def migrate_site():
    banner("Migrate Site")
    if not require_docker():
        return
    print()
    info("Runs pending database migrations — always do this after updating the image or installing an app.")
    print()
    project, site = _pick_project_and_site()
    if not site:
        error("Site name cannot be empty.")
        return
    if run(f"docker compose --project-name {project} exec backend bench --site {site} migrate"):
        success(f"Migration complete for {site}.")
    else:
        error("Migration failed. Check logs with option: View container logs.")


def clear_site_cache():
    banner("Clear Site Cache")
    if not require_docker():
        return
    print()
    info("Clears Redis cache for a site — fixes stale UI, missing assets, or config issues.")
    print()
    project, site = _pick_project_and_site()
    if not site:
        error("Site name cannot be empty.")
        return
    if run(f"docker compose --project-name {project} exec backend bench --site {site} clear-cache"):
        run(f"docker compose --project-name {project} exec backend bench --site {site} clear-website-cache")
        success(f"Cache cleared for {site}.")
    else:
        error("Clear cache failed.")


def maintenance_mode():
    banner("Set Maintenance Mode")
    if not require_docker():
        return
    print()
    print(f"  {bold('What maintenance mode does:')}")
    print(f"  {dim('  Puts a site offline and shows a maintenance page to all visitors.')}")
    print(f"  {dim('  Use before major updates, migrations, or restores.')}")
    print()
    project, site = _pick_project_and_site()
    if not site:
        error("Site name cannot be empty.")
        return
    print()
    print(f"  {bold('1.')} {yellow('Enable')}  — take site offline (maintenance page shown)")
    print(f"  {bold('2.')} {green('Disable')} — bring site back online")
    print()
    choice = ask("Choose [1/2]", "1")
    if choice == "1":
        if run(f"docker compose --project-name {project} exec backend bench --site {site} set-maintenance-mode on"):
            success(f"Maintenance mode ON for {site}. Site is offline.")
        else:
            error("Failed to enable maintenance mode.")
    else:
        if run(f"docker compose --project-name {project} exec backend bench --site {site} set-maintenance-mode off"):
            success(f"Maintenance mode OFF for {site}. Site is back online.")
        else:
            error("Failed to disable maintenance mode.")


def drop_site():
    banner("Drop / Delete a Site")
    if not require_docker():
        return
    print()
    warn("This permanently deletes the site, its database, and all files. This cannot be undone.")
    print()
    project, site = _pick_project_and_site()
    if not site:
        error("Site name cannot be empty.")
        return
    db_root_pass = ask_password("DB root password (needed to drop the database)", "changeit")
    print()
    warn(f"About to permanently delete site: {site}")
    if not confirm("Are you absolutely sure?", default=False):
        info("Cancelled.")
        return
    if run(f"docker compose --project-name {project} exec backend bench drop-site --db-root-password {db_root_pass} {site}"):
        success(f"Site '{site}' dropped.")
    else:
        error("Drop failed. The site may still exist.")


def restore_backup():
    banner("Restore Site from Backup")
    if not require_docker():
        return
    print()
    print(f"  {bold('What this does:')}")
    print(f"  {dim('  Restores a Frappe site from a .sql.gz database backup file.')}")
    print(f"  {dim('  The backup file must be accessible inside the backend container.')}")
    print(f"  {dim('  Backups are stored in: sites/<site>/private/backups/')}")
    print()
    projects = list_bench_projects()
    if projects:
        info("Known projects: " + ", ".join(projects))
    project      = ask("Project name", "erpnext-one")
    site         = ask("Site name to restore INTO")
    if not site:
        error("Site name cannot be empty.")
        return
    backup_file  = ask("Backup file path (inside container, e.g. sites/mysite/private/backups/20240101_db.sql.gz)")
    if not backup_file:
        error("Backup file path cannot be empty.")
        return
    db_root_pass = ask_password("DB root password", "changeit")
    admin_pass   = ask_password("New admin password for restored site", "changeit")
    print()
    if not confirm(f"Restore {backup_file} into site '{site}'?", default=True):
        info("Cancelled.")
        return
    if run(
        f"docker compose --project-name {project} exec backend bench --site {site} restore"
        f" --db-root-password {db_root_pass} --admin-password {admin_pass} {backup_file}"
    ):
        success(f"Restore complete for {site}.")
        info("Run 'Migrate site' next to apply any pending migrations.")
    else:
        error("Restore failed. Check the backup file path and DB password.")


def toggle_scheduler():
    banner("Enable / Disable Scheduler")
    if not require_docker():
        return
    print()
    print(f"  {bold('What the scheduler does:')}")
    print(f"  {dim('  Runs background jobs: email sending, report generation, auto-backups, etc.')}")
    print(f"  {dim('  Disable it temporarily during maintenance; always re-enable after.')}")
    print()
    project, site = _pick_project_and_site()
    if not site:
        error("Site name cannot be empty.")
        return
    print()
    print(f"  {bold('1.')} {green('Enable')}  — start scheduler (normal operation)")
    print(f"  {bold('2.')} {yellow('Disable')} — pause scheduler (maintenance)")
    print()
    choice = ask("Choose [1/2]", "1")
    if choice == "1":
        if run(f"docker compose --project-name {project} exec backend bench --site {site} enable-scheduler"):
            success(f"Scheduler enabled for {site}.")
        else:
            error("Failed to enable scheduler.")
    else:
        if run(f"docker compose --project-name {project} exec backend bench --site {site} disable-scheduler"):
            success(f"Scheduler disabled for {site}.")
        else:
            error("Failed to disable scheduler.")


def uninstall_app():
    banner("Uninstall an App from a Site")
    if not require_docker():
        return
    print()
    info("Removes an app and all its data from a site. This cannot be undone.")
    print()
    projects = list_bench_projects()
    if projects:
        info("Known projects: " + ", ".join(projects))
    project  = ask("Project name", "erpnext-one")
    site     = ask("Site name")
    app_name = ask("App name to uninstall (e.g. erpnext, hrms)")
    if not app_name or not site:
        error("Site and app name cannot be empty.")
        return
    warn(f"This will remove '{app_name}' and all its doctypes/data from {site}.")
    if not confirm("Continue?", default=False):
        info("Cancelled.")
        return
    if run(f"docker compose --project-name {project} exec backend bench --site {site} uninstall-app {app_name}"):
        run(f"docker compose --project-name {project} exec backend bench --site {site} migrate")
        success(f"App '{app_name}' uninstalled from {site}.")
    else:
        error("Uninstall failed.")


def update_bench():
    banner("Update Bench (Pull → Restart → Migrate)")
    if not require_docker() or not require_repo():
        return
    print()
    print(f"  {bold('What this does:')}")
    print(f"  {dim('  Full update workflow in 4 steps:')}")
    print(f"  {dim('    1. Pull latest image from registry')}")
    print(f"  {dim('    2. Regenerate resolved compose YAML')}")
    print(f"  {dim('    3. Restart bench containers with new image')}")
    print(f"  {dim('    4. Run bench migrate on all sites')}")
    print()
    projects = list_bench_projects()
    if projects:
        info("Known projects: " + ", ".join(projects))
    project = ask("Project name", "erpnext-one")
    yaml_path = GITOPS / f"{project}.yaml"
    if not yaml_path.exists():
        error(f"No compose YAML found at {yaml_path}. Deploy the bench first (option: Deploy bench).")
        return
    # Detect image from YAML
    current_img = run_capture(f"grep 'image:' {yaml_path} | head -1 | awk '{{print $2}}'")
    if current_img:
        info(f"Current image: {current_img}")
    new_img = ask("Image to pull (leave blank to keep current)", current_img)
    if not new_img:
        error("Image cannot be empty.")
        return
    print()
    # Step 1 — pull
    info("Step 1/4 — Pulling latest image …")
    if not run(f"docker pull {new_img}"):
        error("Image pull failed. Check image name and registry login.")
        return
    success("Image pulled.")
    # Step 2 — patch image in yaml and re-up
    info("Step 2/4 — Patching image in compose YAML …")
    patched = re.sub(
        r"^(\s+image:\s+)\S+",
        lambda m: m.group(1) + new_img,
        yaml_path.read_text(),
        flags=re.MULTILINE,
    )
    yaml_path.write_text(patched)
    success("YAML updated.")
    # Step 3 — restart
    info("Step 3/4 — Restarting bench …")
    if not run(f"docker compose --project-name {project} -f {yaml_path} up -d --no-deps backend queue-long queue-short scheduler websocket"):
        error("Restart failed.")
        return
    success("Bench restarted.")
    # Step 4 — migrate all sites
    info("Step 4/4 — Running migrations on all sites …")
    if run(f"docker compose --project-name {project} exec backend bench --all-sites migrate"):
        run(f"docker compose --project-name {project} exec backend bench --all-sites clear-cache")
        success("All sites migrated and cache cleared.")
    else:
        error("Migration failed. Run 'Migrate site' manually for each site.")
    success(f"Bench '{project}' updated to {new_img}.")


def push_backup_s3():
    banner("Push Backup to S3 / Compatible Storage")
    if not require_docker():
        return
    print()
    print(f"  {bold('What this does:')}")
    print(f"  {dim('  Runs a one-shot backup of all sites and pushes the files to an S3 bucket.')}")
    print(f"  {dim('  Works with AWS S3, MinIO, Backblaze B2, and any S3-compatible storage.')}")
    print()
    projects = list_bench_projects()
    if projects:
        info("Known projects: " + ", ".join(projects))
    project        = ask("Project name", "erpnext-one")
    bucket         = ask("S3 bucket name")
    region         = ask("AWS region", "us-east-1")
    access_key     = ask("AWS access key ID")
    secret_key     = ask_password("AWS secret access key")
    endpoint       = ask("Endpoint URL (leave blank for AWS)", "")
    backup_path    = ask("S3 folder/prefix", f"frappe-backups/{project}")
    if not bucket or not access_key or not secret_key:
        error("Bucket, access key and secret key are required.")
        return
    print()
    info("Running backup …")
    if not run(f"docker compose --project-name {project} exec backend bench --all-sites backup --with-files"):
        error("Backup failed.")
        return
    success("Local backup created.")
    endpoint_arg = f"--endpoint-url {endpoint}" if endpoint else ""
    info("Pushing to S3 …")
    push_cmd = (
        f"docker compose --project-name {project} exec"
        f" -e AWS_ACCESS_KEY_ID={access_key}"
        f" -e AWS_SECRET_ACCESS_KEY={secret_key}"
        f" -e AWS_DEFAULT_REGION={region}"
        f" backend bash -c \""
        f"pip install awscli -q && "
        f"aws s3 sync /home/frappe/frappe-bench/sites s3://{bucket}/{backup_path} "
        f"--exclude '*' --include '*/private/backups/*' {endpoint_arg}\""
    )
    if run(push_cmd):
        success(f"Backups pushed to s3://{bucket}/{backup_path}")
    else:
        error("S3 push failed. Check credentials and bucket name.")


def bench_console():
    banner("Bench Console (Python Shell)")
    if not require_docker():
        return
    print()
    print(f"  {bold('What this does:')}")
    print(f"  {dim('  Opens an interactive Python shell inside the Frappe bench.')}")
    print(f"  {dim('  You can query the database, call APIs, debug doctypes, etc.')}")
    example = 'frappe.get_doc("User", "Administrator")'
    print(f"  {dim('  Example: ' + example)}")
    print()
    projects = list_bench_projects()
    if projects:
        info("Known projects: " + ", ".join(projects))
    project = ask("Project name", "erpnext-one")
    site    = ask("Site name")
    if not site:
        error("Site name cannot be empty.")
        return
    info(f"Opening bench console for {site} … (type 'exit' or Ctrl+D to quit)")
    print()
    os.system(f"docker compose --project-name {project} exec backend bench --site {site} console")


def view_images():
    banner("View Docker Images")
    if not require_docker():
        return

    print()
    print(f"  {bold('1.')} Frappe / ERPNext images only  {dim('(default)')}")
    print(f"  {bold('2.')} All local images")
    print(f"  {bold('3.')} Search by name")
    print()
    choice = ask("Choose [1/2/3]", "1")

    fmt = "table {{.Repository}}\\t{{.Tag}}\\t{{.ID}}\\t{{.Size}}\\t{{.CreatedSince}}"

    if choice == "2":
        run(f"docker images --format '{fmt}'")

    elif choice == "3":
        term = ask("Image name or keyword")
        # docker images accepts a name filter as a positional arg
        run(f"docker images '{term}' --format '{fmt}'")

    else:
        # Frappe / ERPNext filter: show header then grep
        header = run_capture(f"docker images --format '{fmt}' | head -1")
        rows   = run_capture(
            "docker images --format"
            " '{{.Repository}}\\t{{.Tag}}\\t{{.ID}}\\t{{.Size}}\\t{{.CreatedSince}}'"
            " | grep -iE 'frappe|erpnext|hrms|tridots'"
        )
        if header:
            print(f"\n  {bold(header)}")
        if rows:
            for r in rows.splitlines():
                print(f"  {r}")
        else:
            warn("No frappe/erpnext images found locally.")
            if confirm("Show all images instead?"):
                run(f"docker images --format '{fmt}'")

    print()
    if confirm("Remove an image?", default=False):
        image_id = ask("Image name:tag or ID to remove")
        if image_id:
            if run(f"docker rmi {image_id}"):
                success(f"Removed: {image_id}")
            else:
                error("Remove failed. Is the image in use by a container?")


# ── apps.json helpers ─────────────────────────────────────────────────────────

def _show_apps(apps: list):
    if not apps:
        warn("No apps added yet.")
        return
    print()
    for i, a in enumerate(apps, 1):
        print(f"  {bold(str(i))}. {cyan(a['url'])}  branch: {bold(a['branch'])}")
    print()


def _build_apps_json(default_branch: str, apps_json_path: Path = None) -> list:
    """Interactively build the apps list. Returns list of app dicts."""
    if apps_json_path is None:
        apps_json_path = Path(os.getcwd()) / "apps.json"

    # Offer to reuse existing file
    if apps_json_path.exists():
        try:
            existing = json.loads(apps_json_path.read_text())
            if isinstance(existing, list) and existing:
                info(f"Found existing apps.json ({len(existing)} app(s)):")
                _show_apps(existing)
                choice = ask("Use this / Edit / Discard [u/e/d]", "u").lower()
                if choice.startswith("u"):
                    return existing
                if choice.startswith("e"):
                    apps = list(existing)
                    return _edit_apps_list(apps, default_branch)
        except (json.JSONDecodeError, KeyError):
            warn("Existing apps.json is invalid — starting fresh.")

    return _edit_apps_list([], default_branch)


def _edit_apps_list(apps: list, default_branch: str) -> list:
    """Add / remove apps interactively. Returns the final list."""
    print()
    info("Build your apps list (these apps will be installed inside the image).")
    info("Enter each app's git URL and branch. Leave URL empty when done.")
    print()

    while True:
        _show_apps(apps)
        print(f"  {bold('a.')} Add app")
        if apps:
            print(f"  {bold('r.')} Remove an app")
        print(f"  {bold('d.')} Done")
        print()
        act = ask("Action [a/r/d]", "a" if not apps else "d").lower()

        if act.startswith("d"):
            break

        if act.startswith("r") and apps:
            idx = ask(f"Remove which? [1-{len(apps)}]")
            if idx.isdigit() and 1 <= int(idx) <= len(apps):
                removed = apps.pop(int(idx) - 1)
                success(f"Removed: {removed['url']}")
            else:
                warn("Invalid number.")

        if act.startswith("a"):
            url = ask("App git URL")
            if not url:
                continue
            branch = ask("Branch", default_branch)
            apps.append({"url": url, "branch": branch})
            success(f"Added: {url}  [{branch}]")

    return apps


def create_image():
    banner("Create Custom Frappe / ERPNext Docker Image")
    if not require_docker() or not require_repo():
        return

    # ── 1. Image name & tag ───────────────────────────────────────────────────
    print()
    image_name = ask("Image name", "tridotstech/frappe")
    image_tag  = ask("Image tag",  "v15.0.0")
    full_image = f"{image_name}:{image_tag}"

    # ── 2. Frappe branch & path ───────────────────────────────────────────────
    print()
    frappe_branch = ask("Frappe branch", "version-15")
    frappe_path   = ask("Frappe git URL", "https://github.com/frappe/frappe")

    # ── 3. Build type ─────────────────────────────────────────────────────────
    print()
    print(f"  {bold('Build type:')}")
    print(f"  {bold('1.')} {cyan('custom')}   — full build from scratch using images/custom/Containerfile")
    print(f"          Slower but fully self-contained. No pre-built base needed.")
    print(f"  {bold('2.')} {cyan('layered')}  — builds on top of frappe/build base image")
    print(f"          Faster. Requires the frappe/build base to exist locally or on Docker Hub.")
    print()
    build_choice  = ask("Choose [1/2]", "1")
    use_layered   = build_choice == "2"
    containerfile = "images/layered/Containerfile" if use_layered else "images/custom/Containerfile"

    # ── 4. Python / Node versions ─────────────────────────────────────────────
    print()
    python_version = ask("Python version", "3.12.4")
    node_version   = ask("Node version",   "18.17.1")

    # ── 5. apps.json in development/ ─────────────────────────────────────────
    print()
    info("Step: configure apps.json — apps bundled into the image")
    dev_dir = Path(os.getcwd()) / "development"
    dev_dir.mkdir(parents=True, exist_ok=True)
    apps_json_path = dev_dir / "apps.json"

    apps = _build_apps_json(frappe_branch, apps_json_path)

    if not apps:
        warn("No apps specified. The image will contain Frappe framework only.")
        if not confirm("Continue without extra apps?", default=True):
            return

    apps_json_path.write_text(json.dumps(apps, indent=2))
    success(f"Saved apps.json → {apps_json_path}")
    print()
    print(json.dumps(apps, indent=4))
    print()

    # ── 6. Multi-platform? ────────────────────────────────────────────────────
    multiplatform = confirm("Build for multiple platforms (linux/amd64 + linux/arm64)?", default=False)
    platforms     = ""
    if multiplatform:
        platforms = ask("Platforms", "linux/amd64,linux/arm64")
        if not run_capture("docker buildx version 2>/dev/null"):
            warn("docker buildx not found. Falling back to single-platform build.")
            multiplatform = False

    # ── 7. Assemble build command ─────────────────────────────────────────────
    # Pass apps.json as both:
    #   --secret      → newer Containerfile reads /run/secrets/apps_json to create
    #                   /opt/frappe/apps.json
    #   APPS_JSON_BASE64 → older Containerfile decodes it to /opt/frappe/apps.json;
    #                      both old and new Containerfiles check this var to set
    #                      APP_INSTALL_ARGS="--apps_path=/opt/frappe/apps.json"
    apps_b64 = base64.b64encode(apps_json_path.read_bytes()).decode()
    build_args = [
        "--no-cache",
        "--secret id=apps_json,src=development/apps.json",
        f"--build-arg=FRAPPE_PATH={frappe_path}",
        f"--build-arg=FRAPPE_BRANCH={frappe_branch}",
        f"--build-arg=PYTHON_VERSION={python_version}",
        f"--build-arg=NODE_VERSION={node_version}",
        f"--build-arg=APPS_JSON_BASE64={apps_b64}",
        f"-t {full_image}",
        f"-f {containerfile}",
    ]
    args_str = " ".join(build_args)

    if multiplatform:
        push_now = confirm(f"Push {full_image} to registry during build? (multi-platform requires --push)", default=True)
        if not push_now:
            warn("--load is not supported for multi-platform builds. Falling back to single-platform.")
            multiplatform = False
        else:
            cmd = f"{_sudo()}DOCKER_BUILDKIT=1 docker buildx build --platform {platforms} --push {args_str} ."
    if not multiplatform:
        cmd = f"{_sudo()}DOCKER_BUILDKIT=1 docker build {args_str} ."

    # ── 8. Summary before build ───────────────────────────────────────────────
    print()
    print(f"  {bold('Image        :')} {cyan(full_image)}")
    print(f"  {bold('Containerfile:')} {containerfile}")
    print(f"  {bold('Frappe       :')} {frappe_branch}  ({frappe_path})")
    print(f"  {bold('Python       :')} {python_version}   Node: {node_version}")
    print(f"  {bold('Apps         :')} {len(apps)} app(s) → development/apps.json  {dim('(secret + APPS_JSON_BASE64)')}")
    if multiplatform:
        print(f"  {bold('Platforms    :')} {platforms}")
    print()

    if not confirm("Start build now?", default=True):
        info("Build cancelled. apps.json is saved — run this option again to build.")
        return

    # ── 9. Build ──────────────────────────────────────────────────────────────
    info("Building … this can take 10-30 minutes for a full build.")
    if not run(cmd):
        error("Image build failed. Check the output above for details.")
        return

    success(f"Image ready: {full_image}")

    # ── 10. Push (single-platform) ────────────────────────────────────────────
    if not multiplatform and confirm(f"Push {full_image} to registry?", default=False):
        if run(f"docker push {full_image}"):
            success(f"Pushed: {full_image}")
        else:
            error("Push failed. Make sure you are logged in: docker login")


def update_image():
    banner("Update Image with Latest Git Code")
    if not require_docker() or not require_repo():
        return

    # ── Explain what this does ────────────────────────────────────────────────
    print()
    print(f"  {bold('How this works:')}")
    print(f"  {dim('Docker images bake your git repos in at build time.')}")
    print(f"  {dim('Pushing new code to git does NOT update the image.')}")
    print(f"  {dim('This option rebuilds the image using --no-cache so every')}")
    print(f"  {dim('app is freshly cloned from its git branch.')}")
    print()

    # ── 1. Load apps.json ─────────────────────────────────────────────────────
    apps_json_path = Path(os.getcwd()) / "apps.json"
    apps = []

    if apps_json_path.exists():
        try:
            apps = json.loads(apps_json_path.read_text())
            info(f"Found apps.json with {len(apps)} app(s):")
            _show_apps(apps)
        except (json.JSONDecodeError, KeyError):
            warn("apps.json is invalid.")
            apps = []

    if not apps:
        warn("No apps.json found in the repo root.")
        info("Tip: run 'Create custom image' first to generate apps.json.")
        if not confirm("Continue with no extra apps (Frappe only)?", default=False):
            return

    # Allow editing before rebuild (e.g. branch changed)
    if apps and confirm("Edit apps.json before rebuilding? (e.g. update a branch)", default=False):
        frappe_branch_hint = apps[0].get("branch", "version-15") if apps else "version-15"
        apps = _edit_apps_list(list(apps), frappe_branch_hint)
        apps_json_path.write_text(json.dumps(apps, indent=2))
        success(f"Updated apps.json → {apps_json_path}")

    # ── 2. Image to (re)build ─────────────────────────────────────────────────
    print()
    # Show existing local frappe images to help the user pick
    existing = run_capture(
        "docker images --format '{{.Repository}}:{{.Tag}}'"
        " | grep -iE 'frappe|erpnext|hrms|tridots'"
    )
    if existing:
        info("Existing local Frappe images:")
        for line in existing.splitlines():
            print(f"      {cyan(line)}")
        print()

    old_image = ask("Image name:tag to rebuild (must already exist locally or in registry)")
    if not old_image:
        error("Image name cannot be empty.")
        return

    # New tag — default = same tag (overwrite) or bump
    print()
    print(f"  {bold('New tag options:')}")
    print(f"  {bold('1.')} Keep same tag  {dim(f'({old_image})')}  — overwrites the existing image")
    print(f"  {bold('2.')} Enter a new tag  — keeps the old image intact")
    print()
    tag_choice = ask("Choose [1/2]", "1")

    if tag_choice == "2":
        new_tag = ask("New tag (e.g. v15.1.0)")
        if not new_tag:
            error("Tag cannot be empty.")
            return
        name_part = old_image.rsplit(":", 1)[0]
        full_image = f"{name_part}:{new_tag}"
    else:
        full_image = old_image

    # ── 3. Build settings ─────────────────────────────────────────────────────
    print()
    frappe_branch = ask("Frappe branch", "version-15")
    frappe_path   = ask("Frappe git URL", "https://github.com/frappe/frappe")

    print()
    print(f"  {bold('Build type:')}")
    print(f"  {bold('1.')} custom   — images/custom/Containerfile  {dim('(full build)')}")
    print(f"  {bold('2.')} layered  — images/layered/Containerfile {dim('(needs frappe/build base)')}")
    print()
    use_layered   = ask("Choose [1/2]", "1") == "2"
    containerfile = "images/layered/Containerfile" if use_layered else "images/custom/Containerfile"

    python_version = ""
    node_version   = ""
    if not use_layered:
        print()
        python_version = ask("Python version", "3.11.6")
        node_version   = ask("Node version",   "18.18.2")

    # ── 4. Base64-encode apps.json ────────────────────────────────────────────
    apps_b64 = base64.b64encode(apps_json_path.read_bytes()).decode() if apps_json_path.exists() else ""

    # ── 5. Assemble build command  (--no-cache is the key difference) ─────────
    build_args = [
        f"--build-arg FRAPPE_PATH={frappe_path}",
        f"--build-arg FRAPPE_BRANCH={frappe_branch}",
        f"--tag {full_image}",
        f"--file {containerfile}",
        "--no-cache",
    ]
    if apps_b64:
        build_args.append(f"--build-arg APPS_JSON_BASE64={apps_b64}")
    if python_version:
        build_args.append(f"--build-arg PYTHON_VERSION={python_version}")
    if node_version:
        build_args.append(f"--build-arg NODE_VERSION={node_version}")

    cmd = "docker build " + " ".join(build_args) + " ."

    # ── 6. Summary ────────────────────────────────────────────────────────────
    print()
    print(f"  {bold('Rebuilding    :')} {cyan(full_image)}")
    print(f"  {bold('Containerfile :')} {containerfile}")
    print(f"  {bold('Frappe branch :')} {frappe_branch}")
    print(f"  {bold('Apps          :')} {len(apps)} app(s)  {dim('(fresh clone — latest code)')}")
    print(f"  {bold('Cache         :')} {red('disabled (--no-cache)')}")
    print()

    if not confirm("Start rebuild now?", default=True):
        return

    info("Rebuilding … all apps will be freshly cloned from git.")
    if not run(cmd):
        error("Rebuild failed. Check the output above.")
        return

    success(f"Image updated: {full_image}")

    if confirm(f"Push {full_image} to registry?", default=False):
        if run(f"docker push {full_image}"):
            success(f"Pushed: {full_image}")
        else:
            error("Push failed. Make sure you are logged in: docker login")


# ── Menu ──────────────────────────────────────────────────────────────────────


MENU = [
    # label                                           function          needs_repo  maintenance
    ("Install Docker & Docker Compose",               install_docker,         False, False),
    ("Set active frappe_docker repo",                 clone_or_navigate_repo, False, False),
    ("─── Local Deploy ───────────────────────────", None,                   False, False),
    ("Local deploy via pwd.yml",                      local_deploy,           True,  False),
    ("Local deploy status & diagnostics",             local_status,           True,  False),
    ("Stop local deploy",                             stop_local_deploy,      True,  False),
    ("Drop local deploy",                             drop_local_deploy,      True,  False),
    ("─── Live Infrastructure ────────────────────────",  None,                   False, False),
    ("Setup Traefik reverse proxy",                   create_traefik_env,     True,  False),
    ("Setup shared MariaDB database",                 create_mariadb_env,     True,  False),
    ("Setup shared PostgreSQL database",              create_postgres_env,    True,  False),
    ("Restart infrastructure servers",                restart_servers,        False, False),
    ("Drop infrastructure services",                  drop_infrastructure,    False, False),
    ("─── Live Bench & Sites ──────────────────────────", None,                   False, False),
    ("Deploy Frappe / ERPNext bench",                 create_bench_env,       True,  False),
    ("Create a new site",                             create_bench_site,      True,  False),
    ("Install an app on a site",                      install_app,            True,  False),
    ("Uninstall an app from a site",                  uninstall_app,          True,  False),
    ("─── Live Site Operations ────────────────────────", None,                   False, False),
    ("Migrate site",                                  migrate_site,           True,  False),
    ("Clear site cache",                              clear_site_cache,       True,  False),
    ("Set maintenance mode",                          maintenance_mode,       True,  False),
    ("Enable / Disable scheduler",                    toggle_scheduler,       True,  False),
    ("Drop / Delete a site",                          drop_site,              True,  False),
    ("Restore site from backup",                      restore_backup,         True,  False),
    ("─── Images ─────────────────────────────────", None,                   False, False),
    ("View Docker images",                            view_images,            False, False),
    ("Create custom image (apps.json + build)",       create_image,           True,  False),
    ("Update image with latest git code",             update_image,           True,  False),
    ("─── Management ─────────────────────────────", None,                   False, False),
    ("Update bench (pull → restart → migrate)",       update_bench,           True,  False),
    ("Stop a bench",                                  stop_bench,             True,  False),
    ("View running containers",                       show_status,            False, False),
    ("View container logs",                           show_logs,              False, False),
    ("Backup all sites",                              backup_sites,           True,  False),
    ("Push backup to S3 storage",                     push_backup_s3,         True,  False),
    ("Bench console (Python shell)",                  bench_console,          True,  False),
    ("Clean volumes, networks & build cache",         clean_docker,           False, False),
    ("──────────────────────────────────────────────", None,                  False, False),
    ("Exit",                                          None,                   False, False),
]


def _os_label() -> str:
    """Return a human-readable OS name, e.g. 'Ubuntu 22.04.3 LTS' or 'macOS 14.5'."""
    if IS_MACOS:
        ver = _platform.mac_ver()[0]
        return f"macOS {ver}" if ver else "macOS"
    os_release = Path("/etc/os-release")
    if os_release.exists():
        for line in os_release.read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    return f"{_platform.system()} {_platform.release()}"


def _print_status():
    """Print a status panel above the menu showing all infrastructure states."""
    docker_ok = bool(shutil.which("docker"))
    repo_ok   = repo_is_ready()

    W = 14  # label column width

    print(f"  {dim('─' * 58)}")

    # OS Type
    print(f"  {bold('OS Type'):<{W}} {cyan(_os_label())}")

    # Docker
    d = green("✔  installed") if docker_ok else red("✖  not installed  →  run option 1")
    print(f"  {bold('Docker'):<{W}} {d}")

    # Repo
    if repo_ok:
        print(f"  {bold('Repo'):<{W}} {green('✔  selected')}  {dim(os.getcwd())}")
    else:
        print(f"  {bold('Repo'):<{W}} {yellow('✖  not selected')}  {dim('→ required for all options below (run option 2)')}")

    # Gitops
    if GITOPS.exists():
        print(f"  {bold('Gitops'):<{W}} {green('✔  selected')}  {dim(str(GITOPS))}")
    else:
        print(f"  {bold('Gitops'):<{W}} {yellow('✖  not selected')}")

    # Traefik
    traefik_env = GITOPS / "traefik.env"
    if traefik_env.exists():
        state = green("✔  running") if _container_running("traefik") else red("✖  stopped")
        print(f"  {bold('Traefik'):<{W}} {state}   {dim(str(traefik_env))}")
    else:
        print(f"  {bold('Traefik'):<{W}} {dim('─  not configured  (run option 3)')}")

    # MariaDB
    mariadb_env = GITOPS / "mariadb.env"
    if mariadb_env.exists():
        state = green("✔  running") if _container_running("mariadb") else red("✖  stopped")
        print(f"  {bold('MariaDB'):<{W}} {state}   {dim(str(mariadb_env))}")
    else:
        print(f"  {bold('MariaDB'):<{W}} {dim('─  not configured  (run option 4)')}")

    # PostgreSQL
    postgres_env = GITOPS / "postgres.env"
    if postgres_env.exists():
        state = green("✔  running") if _container_running("postgres") else red("✖  stopped")
        print(f"  {bold('PostgreSQL'):<{W}} {state}   {dim(str(postgres_env))}")
    else:
        print(f"  {bold('PostgreSQL'):<{W}} {dim('─  not configured  (run option 5)')}")

    print(f"  {dim('─' * 58)}")


def print_menu():
    print()
    _print_status()
    print()
    option_num = 0
    for label, fn, needs_repo, maintenance in MENU:
        if label.startswith("─"):
            print(f"  {dim(label)}")
        elif label == "Exit":
            print(f"  {bold('  q.')} {label}")
        else:
            option_num += 1
            if maintenance:
                print(f"  {dim(f'{option_num:>2}.')} {dim(label)}  {yellow('(maintenance mode)')}")
            else:
                suffix = ""
                if fn is clone_or_navigate_repo:
                    suffix = yellow("  ← set this first")
                elif needs_repo and not repo_is_ready():
                    suffix = dim("  (needs repo)")
                print(f"  {bold(f'{option_num:>2}.')} {label}{suffix}")
    print()


def main():
    print(bold(cyan("\n╔══════════════════════════════════════════════════════╗")))
    print(bold(cyan(  "║      Frappe / ERPNext Docker Deployment Wizard       ║")))
    print(bold(cyan(  "╚══════════════════════════════════════════════════════╝")))

    # Selectable options only (skip separators and Exit)
    options = [
        (label, fn, needs_repo, maintenance)
        for label, fn, needs_repo, maintenance in MENU
        if not label.startswith("─") and label != "Exit"
    ]

    while True:
        print_menu()
        raw = input(f"  {bold('?')} Select [{bold('1')}-{bold(str(len(options)))} or {bold('q')}]: ").strip().lower()

        if raw in ("q", "quit", "exit"):
            print(green("\n  Goodbye!\n"))
            break

        if not raw.isdigit() or not (1 <= int(raw) <= len(options)):
            warn(f"Invalid choice '{raw}'. Enter a number between 1 and {len(options)}, or 'q' to quit.")
            continue

        label, fn, needs_repo, maintenance = options[int(raw) - 1]

        # ── Maintenance gate ───────────────────────────────────────────────────
        if maintenance:
            print()
            warn(f"'{label}' is currently in maintenance mode and cannot be used.")
            info("Please try again later or contact your administrator.")
            print()
            continue

        # ── Repo gate ─────────────────────────────────────────────────────────
        if needs_repo and not repo_is_ready():
            print()
            warn(f"'{label}' requires an active frappe_docker repo.")
            warn("Option 2 sets the repo — all other options work inside it.")
            print()
            if confirm("Open the repo setup now? (option 2)", default=True):
                try:
                    clone_or_navigate_repo()
                except KeyboardInterrupt:
                    print()
                    warn("Interrupted.")
                if not repo_is_ready():
                    error("Repo still not set. Please complete option 2 before continuing.")
                    continue
                # Repo is now active — proceed to the originally chosen option
            else:
                info("Returning to menu.")
                continue
        # ─────────────────────────────────────────────────────────────────────

        try:
            fn()
        except KeyboardInterrupt:
            print()
            warn("Interrupted — returning to menu.")
        except Exception as exc:
            error(f"Unexpected error: {exc}")


if __name__ == "__main__":
    main()
