#!/usr/bin/env bash
# Frappe Docker Automation — Shell Edition
# Interactive CLI to deploy and manage Frappe/ERPNext on Docker.
# interactive script — no strict mode

# ── Colors ────────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  BOLD="\033[1m"; RESET="\033[0m"
  GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; CYAN="\033[36m"; DIM="\033[2m"
else
  BOLD=""; RESET=""; GREEN=""; YELLOW=""; RED=""; CYAN=""; DIM=""
fi

bold()   { printf "${BOLD}%s${RESET}" "$1"; }
green()  { printf "${GREEN}%s${RESET}" "$1"; }
yellow() { printf "${YELLOW}%s${RESET}" "$1"; }
red()    { printf "${RED}%s${RESET}" "$1"; }
cyan()   { printf "${CYAN}%s${RESET}" "$1"; }
dim()    { printf "${DIM}%s${RESET}" "$1"; }

# ── Constants ─────────────────────────────────────────────────────────────────
GITOPS="$HOME/gitops"
OS_TYPE="$(uname -s)"
IS_MACOS=false; IS_LINUX=false
[[ "$OS_TYPE" == "Darwin" ]] && IS_MACOS=true
[[ "$OS_TYPE" == "Linux"  ]] && IS_LINUX=true

# ── Output helpers ────────────────────────────────────────────────────────────
banner() {
  local line; line="$(printf '%.0s─' {1..60})"
  printf "\n${CYAN}%s${RESET}\n  ${BOLD}%s${RESET}\n${CYAN}%s${RESET}\n" "$line" "$1" "$line"
}
success() { printf "  ${GREEN}✔  %s${RESET}\n" "$1"; }
warn()    { printf "  ${YELLOW}⚠  %s${RESET}\n" "$1"; }
error()   { printf "  ${RED}✖  %s${RESET}\n" "$1"; }
info()    { printf "  ${DIM}→  %s${RESET}\n" "$1"; }

# ── Input helpers ─────────────────────────────────────────────────────────────
ask() {
  local prompt="$1" default="${2:-}"
  local hint=""
  [[ -n "$default" ]] && hint=" [$default]"
  printf "  ${BOLD}?${RESET} %s%s: " "$prompt" "$hint" >&2
  local val; read -r val </dev/tty
  [[ -z "$val" ]] && val="$default"
  echo "$val"
}

ask_password() {
  local prompt="$1" default="${2:-}"
  local hint=""
  [[ -n "$default" ]] && hint=" [$default]"
  printf "  ${BOLD}?${RESET} %s%s: " "$prompt" "$hint" >&2
  local val
  if read -rs val </dev/tty 2>/dev/null; then
    printf "\n" >&2
  else
    read -r val </dev/tty
  fi
  [[ -z "$val" ]] && val="$default"
  echo "$val"
}

confirm() {
  local prompt="$1" default="${2:-false}"
  local choices="y/N"; [[ "$default" == "true" ]] && choices="Y/n"
  printf "  ${BOLD}?${RESET} %s (%s): " "$prompt" "$choices" >&2
  local val; read -r val </dev/tty; val="${val,,}"
  if [[ -z "$val" ]]; then
    [[ "$default" == "true" ]] && return 0 || return 1
  fi
  [[ "$val" == y* ]] && return 0 || return 1
}

validate_email() { echo "$1" | grep -qE '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'; }
validate_domain() { echo "$1" | grep -qE '^[a-zA-Z0-9._-]+\.[a-zA-Z]{2,}$'; }

# ── Shell helpers ─────────────────────────────────────────────────────────────
_sudo() { [[ "$IS_LINUX" == "true" ]] && echo "sudo " || echo ""; }

run_cmd() {
  local cmd="$1" silent="${2:-false}"
  [[ "$silent" == "false" ]] && info "${cmd:0:110}$([ ${#cmd} -gt 110 ] && echo '…')"
  if [[ "$silent" == "true" ]]; then
    eval "$cmd" >/dev/null 2>&1
  else
    eval "$cmd"
  fi
}

run_capture() {
  eval "$1" 2>/dev/null || true
}

# ── Guards ────────────────────────────────────────────────────────────────────
require_docker() {
  if ! command -v docker &>/dev/null; then
    error "Docker not found. Run option 1 to install it first."
    return 1
  fi
}

repo_is_ready() { [[ -f "$(pwd)/compose.yaml" ]]; }

require_repo() {
  if ! repo_is_ready; then
    error "compose.yaml not found in the current directory."
    info "Run option 2 to navigate to the frappe_docker repo first."
    return 1
  fi
}

ensure_gitops() { mkdir -p "$GITOPS"; }

list_bench_projects() {
  [[ ! -d "$GITOPS" ]] && return
  for f in "$GITOPS"/*.env; do
    [[ -f "$f" ]] || continue
    local name; name="$(basename "$f" .env)"
    [[ "$name" == "traefik" || "$name" == "mariadb" || "$name" == "postgres" ]] && continue
    echo "$name"
  done
}

container_running() {
  command -v docker &>/dev/null || return 1
  local out
  out=$(docker ps --filter "label=com.docker.compose.project=$1" --format '{{.Names}}' 2>/dev/null)
  [[ -n "$out" ]]
}

# ── Latest Compose version ────────────────────────────────────────────────────
latest_compose_version() {
  local resp
  resp=$(curl -s https://api.github.com/repos/docker/compose/releases/latest 2>/dev/null || true)
  if [[ -n "$resp" ]]; then
    local tag; tag=$(echo "$resp" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tag_name',''))" 2>/dev/null || true)
    [[ -n "$tag" ]] && echo "$tag" && return
  fi
  echo "v2.27.0"
}

# ── 1. Install Docker ─────────────────────────────────────────────────────────
install_docker() {
  banner "Install Docker & Docker Compose"
  if command -v docker &>/dev/null; then
    warn "Docker is already installed: $(docker --version)"
    confirm "Re-install / update anyway?" false || return
  fi
  if [[ "$IS_MACOS" == "true" ]]; then
    _install_docker_macos
  else
    _install_docker_linux
  fi
}

_install_docker_macos() {
  printf "\n  ${BOLD}macOS detected — Docker Desktop is the recommended install.${RESET}\n\n"
  printf "  ${BOLD}1.${RESET} ${CYAN}Homebrew${RESET}       $(dim '(automated, recommended)')\n"
  printf "       brew install --cask docker\n"
  printf "  ${BOLD}2.${RESET} ${CYAN}Manual download${RESET} $(dim '(Docker Desktop .dmg)')\n\n"
  if command -v brew &>/dev/null; then
    local choice; choice=$(ask "Install via Homebrew? [y/n]" "y")
    if [[ "${choice,,}" == y* ]]; then
      if run_cmd "brew install --cask docker"; then
        success "Docker Desktop installed."
        info "Open Docker Desktop from Applications to finish setup, then re-run."
      else
        error "Homebrew install failed."
      fi
    fi
  else
    warn "Homebrew not found. Install from https://brew.sh or download Docker Desktop manually."
  fi
}

_install_docker_linux() {
  confirm "This runs the official Docker install script as root. Continue?" true || return
  if ! run_cmd "curl -fsSL https://get.docker.com | bash"; then
    error "Docker install failed."; return
  fi
  local cli_plugins="$HOME/.docker/cli-plugins"
  mkdir -p "$cli_plugins"
  local latest; latest=$(latest_compose_version)
  local arch; arch=$(uname -m)
  local url="https://github.com/docker/compose/releases/download/${latest}/docker-compose-linux-${arch}"
  info "Installing Docker Compose ${latest} …"
  if curl -SL "$url" -o "${cli_plugins}/docker-compose" && chmod +x "${cli_plugins}/docker-compose"; then
    success "Done."
    docker --version && docker compose version
  else
    error "Docker Compose install failed."
  fi
}

# ── 2. Clone / Navigate Repo ──────────────────────────────────────────────────
clone_or_navigate_repo() {
  banner "Clone / Navigate to frappe_docker Repo"
  local found=()
  for root in "$(pwd)" "$HOME" "/opt" "/srv"; do
    local candidate="$root/frappe_docker"
    [[ -d "$candidate" && -f "$candidate/compose.yaml" ]] && found+=("$candidate")
  done

  if [[ ${#found[@]} -gt 0 ]]; then
    printf "\n  ${BOLD}Existing frappe_docker folder(s) found:${RESET}\n"
    local i=1
    for p in "${found[@]}"; do
      local remote; remote=$(git -C "$p" remote get-url origin 2>/dev/null || echo "—")
      local branch; branch=$(git -C "$p" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "—")
      printf "  ${BOLD}%d.${RESET} ${CYAN}%s${RESET}\n       remote : %s\n       branch : %s\n" "$i" "$p" "$remote" "$branch"
      ((i++))
    done
    printf "  ${BOLD}%d.${RESET} Clone a fresh copy\n" "$i"; ((i++))
    printf "  ${BOLD}%d.${RESET} Enter a custom path manually\n\n" "$i"

    local total=${#found[@]}
    local choice; choice=$(ask "Choose [1-$((total+2))]" "1")

    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= total )); then
      cd "${found[$((choice-1))]}"
      ensure_gitops
      success "Using existing repo : $(pwd)"
      success "Gitops directory    : $GITOPS"
      return
    fi
    if [[ "$choice" == "$((total+2))" ]]; then
      local custom; custom=$(ask "Enter full path to frappe_docker repo")
      if [[ -z "$custom" || ! -d "$custom" ]]; then error "Directory not found."; return; fi
      cd "$custom"; ensure_gitops
      success "Repo directory   : $(pwd)"
      success "Gitops directory : $GITOPS"
      return
    fi
  fi

  local url; url=$(ask "Repository URL" "https://github.com/frappe/frappe_docker")
  local clone_dir; clone_dir=$(ask "Clone into folder name" "frappe_docker")

  if [[ -d "$clone_dir" ]]; then
    warn "Folder '$clone_dir' already exists."
    if confirm "Use the existing '$clone_dir' without re-cloning?" true; then
      cd "$clone_dir"; ensure_gitops
      success "Repo directory   : $(pwd)"
      success "Gitops directory : $GITOPS"
      return
    fi
    confirm "Delete and re-clone?" false || return
    rm -rf "$clone_dir"
  fi

  if git clone "$url" "$clone_dir"; then
    cd "$clone_dir"; ensure_gitops
    success "Repo directory   : $(pwd)"
    success "Gitops directory : $GITOPS"
  else
    error "Clone failed."
  fi
}

# ── 3. Local Deploy ───────────────────────────────────────────────────────────
local_deploy() {
  banner "Local Deploy (pwd.yml)"
  require_docker || return
  require_repo   || return

  local pwd_yml="$(pwd)/pwd.yml"
  if [[ -f "$pwd_yml" ]]; then
    local sudo_pfx; sudo_pfx=$(_sudo)
    local running; running=$(eval "${sudo_pfx}docker compose -f pwd.yml ps --services --filter status=running 2>/dev/null" || true)
    if [[ -n "$running" ]]; then
      printf "\n"
      warn "A local deploy is already running."
      info "Running services: $(echo "$running" | tr '\n' ' ')"
      printf "\n  $(dim 'Stop it first, then re-deploy:')\n"
      printf "  ${BOLD}  →${RESET} Use ${BOLD}Stop local deploy${RESET} to stop containers (data kept)\n"
      printf "  ${BOLD}  →${RESET} Use ${BOLD}Drop local deploy${RESET} to remove containers / volumes\n\n"
      return
    fi
  fi

  printf "\n  ${BOLD}What is pwd.yml?${RESET}\n"
  printf "  $(dim '  pwd.yml is a self-contained Docker Compose file for local / testing use.')\n"
  printf "  $(dim '  It starts the entire Frappe stack: backend, frontend (port 8080), workers,')\n"
  printf "  $(dim '  MariaDB 10.6, Redis cache + queue. All services share ONE image.')\n\n"

  if [[ ! -f "$pwd_yml" ]]; then error "pwd.yml not found in the current directory."; return; fi

  local text; text=$(cat "$pwd_yml")

  # Detect current Frappe image (skip mariadb/redis)
  local current_image=""
  while IFS= read -r line; do
    if echo "$line" | grep -qE '^\s+image:\s+\S+'; then
      local img; img=$(echo "$line" | sed 's/.*image:\s*//')
      if ! echo "$img" | grep -qiE 'mariadb|redis'; then
        current_image="$img"; break
      fi
    fi
  done <<< "$text"

  [[ -n "$current_image" ]] && printf "  ${BOLD}Current image in pwd.yml:${RESET} ${CYAN}%s${RESET}\n\n" "$current_image"

  # Local Frappe images
  local local_imgs=()
  while IFS= read -r line; do
    [[ -n "$line" ]] && local_imgs+=("$line")
  done < <(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -iE 'frappe|erpnext|hrms|sankarprakashm' || true)

  local new_image=""
  if [[ ${#local_imgs[@]} -gt 0 ]]; then
    printf "  ${BOLD}Local Frappe images found on this machine:${RESET}\n"
    local i=1
    for img in "${local_imgs[@]}"; do
      local tag=""; [[ "$img" == "$current_image" ]] && tag="  ${GREEN}← currently in pwd.yml${RESET}"
      printf "  ${BOLD}%d.${RESET} ${CYAN}%s${RESET}%b\n" "$i" "$img" "$tag"
      ((i++))
    done
    printf "  ${BOLD}%d.${RESET} Enter a different image manually\n\n" "$i"
    local choice; choice=$(ask "Choose [1-$i]" "1")
    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#local_imgs[@]} )); then
      new_image="${local_imgs[$((choice-1))]}"
    else
      new_image=$(ask "Image name:tag" "$current_image")
    fi
  else
    warn "No local Frappe images found."
    new_image=$(ask "Image name:tag (e.g. sankarprakashm/frappe:v15)" "$current_image")
  fi

  [[ -z "$new_image" ]] && error "Image name cannot be empty." && return

  printf "\n  ${BOLD}Site & database settings${RESET}\n"

  # Detect current site name
  local cur_site; cur_site=$(echo "$text" | sed -n 's/.*--set-default[[:space:]]\+\([^[:space:];]\+\).*/\1/p' | head -1 || true)
  [[ -z "$cur_site" ]] && cur_site="frontend"
  local cur_app; cur_app=$(echo "$text" | sed -n 's/.*--install-app[[:space:]]\+\([^[:space:]]\+\).*/\1/p' | head -1 || true)

  local site_name; site_name=$(ask "Site name" "$cur_site")
  local db_pass;   db_pass=$(ask_password "MariaDB root password" "admin")
  local admin_pass; admin_pass=$(ask_password "Frappe admin password" "admin")

  printf "\n  ${BOLD}App to install on site creation:${RESET}\n"
  local install_app; install_app=$(ask "App name (leave empty to skip)" "$cur_app")

  printf "\n  ${BOLD}Deploy mode:${RESET}\n"
  printf "  ${BOLD}1.${RESET} ${YELLOW}Fresh${RESET}   — stops stack, ${RED}wipes all volumes${RESET}, redeploys clean\n"
  printf "  ${BOLD}2.${RESET} ${GREEN}Update${RESET}  — keeps existing data, restarts with new image\n\n"
  local mode; mode=$(ask "Choose [1/2]" "2")
  local fresh=false; [[ "$mode" == "1" ]] && fresh=true

  if [[ "$fresh" == "true" ]]; then
    warn "FRESH DEPLOY: all existing MariaDB data and Frappe sites will be deleted."
    confirm "Are you absolutely sure?" false || { info "Cancelled."; return; }
  fi

  # Patch pwd.yml using python3 for reliable regex
  python3 - "$pwd_yml" "$new_image" "$site_name" "$db_pass" "$admin_pass" "$install_app" <<'PYEOF'
import re, sys
path, new_image, site_name, db_pass, admin_pass, install_app = sys.argv[1:]

text = open(path).read()

def swap_image(m):
    img = m.group(2)
    if any(x in img for x in ("mariadb","redis")):
        return m.group(0)
    return m.group(1) + new_image

text = re.sub(r'^(\s+image:\s+)(\S+)', swap_image, text, flags=re.MULTILINE)
text = re.sub(r'(--set-default\s+)\S+', lambda m: m.group(1) + site_name + ";", text)
text = re.sub(r'(FRAPPE_SITE_NAME_HEADER:\s*)\S+', lambda m: m.group(1) + site_name, text)
text = re.sub(r'(--admin-password=)\S+', lambda m: m.group(1) + admin_pass, text)
text = re.sub(r'(--db-root-password=)\S+', lambda m: m.group(1) + db_pass, text)
text = re.sub(r'(MYSQL_ROOT_PASSWORD:\s*)\S+', lambda m: m.group(1) + db_pass, text)
text = re.sub(r'(MARIADB_ROOT_PASSWORD:\s*)\S+', lambda m: m.group(1) + db_pass, text)
text = re.sub(r'(--password=)\S+', lambda m: m.group(1) + db_pass, text)
if install_app:
    text = re.sub(r'(--install-app\s+)\S+', lambda m: m.group(1) + install_app, text)
else:
    text = re.sub(r'\s*--install-app\s+\S+', '', text)
text = re.sub(r'(restart:\s*)none\b', r'\1"no"', text)
open(path, 'w').write(text)
PYEOF

  success "pwd.yml updated."

  printf "\n  $(dim '──────────────────────────────────────────────────────────')\n"
  printf "  ${BOLD}Image       :${RESET} ${CYAN}%s${RESET}\n" "$new_image"
  printf "  ${BOLD}Site name   :${RESET} %s\n" "$site_name"
  printf "  ${BOLD}App         :${RESET} %s\n" "${install_app:-$(dim 'none')}"
  if [[ "$fresh" == "true" ]]; then
    printf "  ${BOLD}Mode        :${RESET} ${RED}Fresh (volumes wiped)${RESET}\n"
  else
    printf "  ${BOLD}Mode        :${RESET} ${GREEN}Update (data preserved)${RESET}\n"
  fi
  printf "  ${BOLD}Access URL  :${RESET} ${CYAN}http://localhost:8080${RESET}\n"
  printf "  ${BOLD}Login       :${RESET} Administrator / %s\n" "$admin_pass"
  printf "  $(dim '──────────────────────────────────────────────────────────')\n\n"

  confirm "Deploy now?" true || { info "pwd.yml saved — run again to deploy."; return; }

  local sudo_prefix; sudo_prefix=$(_sudo)
  if [[ "$fresh" == "true" ]]; then
    info "Removing existing stack and volumes …"
    eval "${sudo_prefix}docker compose -f pwd.yml down --volumes"
  fi

  info "Starting stack …"
  if eval "${sudo_prefix}docker compose -f pwd.yml up -d"; then
    success "Stack is up!"
    local project_name; project_name=$(basename "$(pwd)")
    sleep 10
    info "Setting active site → ${site_name} …"
    eval "${sudo_prefix}docker compose --project-name ${project_name} exec backend bench use ${site_name}" >/dev/null 2>&1 || true
    printf "\n  $(dim '──────────────────────────────────────────────────────────')\n"
    printf "  ${BOLD}Running migrations${RESET}  $(dim '(this may take a few minutes …)')\n"
    printf "  $(dim '──────────────────────────────────────────────────────────')\n"
    sleep 10
    eval "${sudo_prefix}docker compose --project-name ${project_name} exec backend bench --site ${site_name} migrate" || true
    printf "  $(dim '──────────────────────────────────────────────────────────')\n"
    success "Migrations complete."
    printf "\n  ${BOLD}URL   :${RESET} ${CYAN}http://localhost:8080${RESET}\n"
    printf "  ${BOLD}Login :${RESET} Administrator / %s\n\n" "$admin_pass"
    info "On first run, site creation runs in background (~2-3 min)."
    info "Watch: ${sudo_prefix}docker compose -f pwd.yml logs -f create-site"
  else
    error "Deploy failed."
    info "Check logs: ${sudo_prefix}docker compose -f pwd.yml logs"
  fi
}

# ── 4. Local Status ───────────────────────────────────────────────────────────
local_status() {
  banner "Local Deploy Status (pwd.yml)"
  require_docker || return
  local sudo_prefix; sudo_prefix=$(_sudo)
  [[ ! -f "$(pwd)/pwd.yml" ]] && error "pwd.yml not found." && return

  printf "\n  ${BOLD}Container states:${RESET}\n"
  eval "${sudo_prefix}docker compose -f pwd.yml ps"

  printf "\n  ${BOLD}create-site logs${RESET} $(dim '(site creation result):')\n"
  local cs_logs; cs_logs=$(eval "${sudo_prefix}docker compose -f pwd.yml logs create-site 2>/dev/null" || true)
  if [[ -n "$cs_logs" ]]; then
    echo "$cs_logs" | tail -15 | while IFS= read -r line; do
      if echo "$line" | grep -qiE 'already exists|exit'; then
        printf "  ${YELLOW}⚠  %s${RESET}\n" "$line"
      elif echo "$line" | grep -qiE 'error|exception|traceback'; then
        printf "  ${RED}✖  %s${RESET}\n" "$line"
      elif echo "$line" | grep -qiE 'ready|successfully'; then
        printf "  ${GREEN}✔  %s${RESET}\n" "$line"
      else
        printf "  ${DIM}%s${RESET}\n" "$line"
      fi
    done
  else
    warn "No create-site logs found."
  fi

  printf "\n  ${BOLD}Backend logs${RESET} $(dim '(last 10 lines):')\n"
  local be_logs; be_logs=$(eval "${sudo_prefix}docker compose -f pwd.yml logs backend --tail=10 2>/dev/null" || true)
  if [[ -n "$be_logs" ]]; then
    echo "$be_logs" | while IFS= read -r line; do
      if echo "$line" | grep -qiE 'Error|Exception|DoesNotExist|not found'; then
        printf "  ${RED}%s${RESET}\n" "$line"
      else
        printf "  ${DIM}%s${RESET}\n" "$line"
      fi
    done
  else
    warn "No backend logs."
  fi

  printf "\n"
  if echo "$cs_logs" | grep -q "already exists"; then
    printf "  ${BOLD}${YELLOW}⚠  Diagnosis:${RESET} Site already exists in volumes from a previous deploy.\n"
    printf "\n  ${BOLD}Fix options:${RESET}\n"
    printf "  ${BOLD}1.${RESET} ${RED}Fresh deploy${RESET}  — wipe volumes and recreate site\n"
    printf "  ${BOLD}2.${RESET} ${YELLOW}Migrate only${RESET} — keep data, run bench migrate\n"
    printf "  ${BOLD}3.${RESET} Skip\n\n"
    local fix; fix=$(ask "Choose [1/2/3]" "1")
    if [[ "$fix" == "1" ]]; then
      confirm "This will DELETE all site data. Continue?" false || return
      eval "${sudo_prefix}docker compose -f pwd.yml down --volumes"
      eval "${sudo_prefix}docker compose -f pwd.yml up -d" && success "Fresh deploy started."
    elif [[ "$fix" == "2" ]]; then
      eval "${sudo_prefix}docker compose -f pwd.yml exec backend bench --site testing migrate" && \
        eval "${sudo_prefix}docker compose -f pwd.yml exec backend bench --site testing clear-cache" && \
        success "Migration complete. Refresh your browser." || error "Migration failed."
    fi
  else
    success "No obvious errors detected. Stack looks healthy."
    printf "  ${DIM}   Access: http://localhost:8080${RESET}\n"
  fi
}

# ── 5. Stop Local Deploy ──────────────────────────────────────────────────────
stop_local_deploy() {
  banner "Stop Local Deploy (pwd.yml)"
  require_docker || return
  [[ ! -f "$(pwd)/pwd.yml" ]] && error "pwd.yml not found." && return
  local sudo_prefix; sudo_prefix=$(_sudo)
  local running; running=$(eval "${sudo_prefix}docker compose -f pwd.yml ps --filter status=running --format '{{.Name}}' 2>/dev/null" || true)
  if [[ -z "$running" ]]; then warn "No pwd.yml containers are currently running."; return; fi
  printf "\n  ${BOLD}Containers that will be stopped:${RESET}\n"
  echo "$running" | while IFS= read -r name; do printf "  ${DIM}  • %s${RESET}\n" "$name"; done
  printf "\n"; info "Volumes and data will NOT be removed.\n"
  confirm "Stop all pwd.yml containers?" true || { info "Cancelled."; return; }
  if eval "${sudo_prefix}docker compose -f pwd.yml stop"; then
    success "Local deploy stopped. Data is intact."
    info "To restart: ${sudo_prefix}docker compose -f pwd.yml start"
  else
    error "Stop failed."
  fi
}

# ── 6. Drop Local Deploy ──────────────────────────────────────────────────────
drop_local_deploy() {
  banner "Drop Local Deploy (pwd.yml)"
  require_docker || return
  [[ ! -f "$(pwd)/pwd.yml" ]] && error "pwd.yml not found." && return
  local sudo_prefix; sudo_prefix=$(_sudo)
  local running; running=$(eval "${sudo_prefix}docker compose -f pwd.yml ps --format '{{.Name}}\t{{.Status}}' 2>/dev/null" || true)
  if [[ -z "$running" ]]; then warn "No pwd.yml containers are currently running."; return; fi
  printf "\n  ${BOLD}Running containers:${RESET}\n"
  echo "$running" | while IFS= read -r line; do printf "  ${DIM}  %s${RESET}\n" "$line"; done
  printf "\n  ${BOLD}Drop level:${RESET}\n"
  printf "  ${BOLD}1.${RESET} ${YELLOW}Stop only${RESET}       — stop containers, keep volumes\n"
  printf "  ${BOLD}2.${RESET} ${YELLOW}Stop + Remove${RESET}   — remove containers & network, keep volumes\n"
  printf "  ${BOLD}3.${RESET} ${RED}Full drop${RESET}        — remove everything including ${RED}all volumes (data lost)${RESET}\n\n"
  local choice; choice=$(ask "Choose [1/2/3]" "2")
  case "$choice" in
    1) confirm "Stop all containers?" true || { info "Cancelled."; return; }
       eval "${sudo_prefix}docker compose -f pwd.yml stop" && success "Containers stopped." || error "Stop failed." ;;
    2) confirm "Remove containers and network? (volumes kept)" true || { info "Cancelled."; return; }
       eval "${sudo_prefix}docker compose -f pwd.yml down" && success "Containers and network removed." || error "Down failed." ;;
    3) warn "This will permanently delete all site data, database, and logs."
       confirm "Are you absolutely sure?" false || { info "Cancelled."; return; }
       eval "${sudo_prefix}docker compose -f pwd.yml down --volumes"
       local orphans; orphans=$(docker volume ls --format '{{.Name}}' 2>/dev/null | grep -E '^frappe_docker_(sites|db-data|redis-queue-data|logs)$' || true)
       if [[ -n "$orphans" ]]; then
         echo "$orphans" | while IFS= read -r vol; do
           docker volume rm "$vol" 2>/dev/null && success "Removed volume: $vol" || warn "Could not remove: $vol"
         done
       fi
       success "Local deploy fully dropped." ;;
    *) warn "Invalid choice." ;;
  esac
}

# ── 7. Setup Traefik ──────────────────────────────────────────────────────────
create_traefik_env() {
  banner "Setup Traefik Reverse Proxy"
  require_docker || return
  ensure_gitops
  local domain; domain=$(ask "Traefik dashboard domain" "traefik.example.com")
  validate_domain "$domain" || warn "Domain looks unusual, proceeding anyway."
  local email;  email=$(ask "Admin e-mail" "admin@example.com")
  local password; password=$(ask_password "Dashboard password" "changeit")

  info "Hashing password …"
  local hashed; hashed=$(openssl passwd -apr1 "$password" 2>/dev/null | sed 's/\$/\$\$/g')
  if [[ -z "$hashed" ]]; then error "openssl not found or hashing failed."; return; fi

  local env_path="$GITOPS/traefik.env"
  printf "TRAEFIK_DOMAIN=%s\nEMAIL=%s\nHASHED_PASSWORD=%s\n" "$domain" "$email" "$hashed" > "$env_path"
  info "Wrote $env_path"

  local ssl=false
  confirm "Enable HTTPS with Let's Encrypt?" true && ssl=true || true
  local files="-f overrides/compose.traefik.yaml"
  [[ "$ssl" == "true" ]] && files+=" -f overrides/compose.traefik-ssl.yaml"

  if docker compose --project-name traefik --env-file "$env_path" $files up -d; then
    success "Traefik is running."
    [[ "$ssl" == "true" ]] && info "Dashboard → https://${domain}" || info "Dashboard → http://${domain}"
  else
    error "Traefik failed to start."
  fi
}

# ── 8. Setup MariaDB ──────────────────────────────────────────────────────────
create_mariadb_env() {
  banner "Setup Shared MariaDB Database"
  require_docker || return
  ensure_gitops
  local db_pass; db_pass=$(ask_password "MariaDB root password" "changeit")
  local env_path="$GITOPS/mariadb.env"
  printf "DB_PASSWORD=%s\n" "$db_pass" > "$env_path"
  info "Wrote $env_path"
  if docker compose --project-name mariadb --env-file "$env_path" -f overrides/compose.mariadb-shared.yaml up -d; then
    success "MariaDB is running on network: mariadb-network"
  else
    error "MariaDB failed to start."
  fi
}

# ── 9. Setup PostgreSQL ───────────────────────────────────────────────────────
create_postgres_env() {
  banner "Setup Shared PostgreSQL Database"
  require_docker || return
  ensure_gitops
  local db_pass; db_pass=$(ask_password "PostgreSQL password" "changeit")
  local env_path="$GITOPS/postgres.env"
  printf "DB_PASSWORD=%s\n" "$db_pass" > "$env_path"
  info "Wrote $env_path"
  if docker compose --project-name postgres --env-file "$env_path" -f overrides/compose.postgres-shared.yaml up -d; then
    success "PostgreSQL is running on network: postgres-network"
  else
    error "PostgreSQL failed to start."
  fi
}

# ── 10. Restart Servers ───────────────────────────────────────────────────────
restart_servers() {
  banner "Restart Traefik & Database Servers"
  require_docker || return
  local t="$GITOPS/traefik.env" m="$GITOPS/mariadb.env" p="$GITOPS/postgres.env"
  if [[ -f "$t" ]]; then
    info "Restarting Traefik …"
    docker compose --project-name traefik --env-file "$t" \
      -f overrides/compose.traefik.yaml -f overrides/compose.traefik-ssl.yaml restart
    success "Traefik restarted."
  else warn "$t not found — skipping Traefik."; fi
  if [[ -f "$m" ]]; then
    info "Restarting MariaDB …"
    docker compose --project-name mariadb --env-file "$m" -f overrides/compose.mariadb-shared.yaml restart
    success "MariaDB restarted."
  else warn "$m not found — skipping MariaDB."; fi
  if [[ -f "$p" ]]; then
    info "Restarting PostgreSQL …"
    docker compose --project-name postgres --env-file "$p" -f overrides/compose.postgres-shared.yaml restart
    success "PostgreSQL restarted."
  fi
}

# ── 11. Drop Infrastructure ───────────────────────────────────────────────────
drop_infrastructure() {
  banner "Drop Infrastructure Services"
  require_docker || return
  local services=()
  [[ -f "$GITOPS/traefik.env"  ]] && services+=("Traefik|traefik|$GITOPS/traefik.env|-f overrides/compose.traefik.yaml -f overrides/compose.traefik-ssl.yaml")
  [[ -f "$GITOPS/mariadb.env"  ]] && services+=("MariaDB|mariadb|$GITOPS/mariadb.env|-f overrides/compose.mariadb-shared.yaml")
  [[ -f "$GITOPS/postgres.env" ]] && services+=("PostgreSQL|postgres|$GITOPS/postgres.env|-f overrides/compose.postgres-shared.yaml")

  if [[ ${#services[@]} -eq 0 ]]; then warn "No infrastructure .env files found — nothing to drop."; return; fi

  printf "\n  ${BOLD}Select services to drop:${RESET}\n"
  local i=1
  for s in "${services[@]}"; do
    printf "  ${BOLD}%d.${RESET} %s\n" "$i" "$(echo "$s" | cut -d'|' -f1)"
    ((i++))
  done
  printf "  ${BOLD}%d.${RESET} All of the above\n\n" "$i"
  local choice; choice=$(ask "Choose [1-$i]" "$i")

  local targets=()
  if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#services[@]} )); then
    targets=("${services[$((choice-1))]}")
  else
    targets=("${services[@]}")
  fi

  local vol_flag=""
  confirm "Also remove volumes? (WARNING: deletes all data)" false && vol_flag=" --volumes"

  warn "This will stop and remove the selected services."
  confirm "Proceed?" false || { info "Cancelled."; return; }

  for s in "${targets[@]}"; do
    local name proj env_file files
    IFS='|' read -r name proj env_file files <<< "$s"
    info "Dropping $name …"
    if docker compose --project-name "$proj" --env-file "$env_file" $files down$vol_flag; then
      success "$name dropped."
    else
      error "Failed to drop $name."
    fi
  done
}

# ── 12. Deploy Bench ──────────────────────────────────────────────────────────
create_bench_env() {
  banner "Deploy Frappe / ERPNext Bench"
  require_docker || return
  ensure_gitops
  [[ ! -f "$(pwd)/example.env" ]] && error "example.env not found in $(pwd)" && return

  local project; project=$(ask "Project / bench name" "erpnext-one")
  local db_type; db_type=$(ask "Database type [mariadb/postgres]" "mariadb")
  [[ "$db_type" != "mariadb" && "$db_type" != "postgres" ]] && warn "Unknown type, defaulting to mariadb." && db_type="mariadb"
  local db_pass; db_pass=$(ask_password "DB password" "changeit")
  local db_host db_port
  if [[ "$db_type" == "mariadb" ]]; then
    db_host=$(ask "DB_HOST" "mariadb-database"); db_port=$(ask "DB_PORT" "3306")
  else
    db_host=$(ask "DB_HOST" "postgres-database"); db_port=$(ask "DB_PORT" "5432")
  fi
  local le_email; le_email=$(ask "Let's Encrypt email" "admin@example.com")
  validate_email "$le_email" || warn "Email looks invalid, proceeding anyway."
  local sites_raw; sites_raw=$(ask "Site domain(s), comma-separated" "one.example.com")
  local sites; sites=$(echo "$sites_raw" | python3 -c "import sys; parts=sys.stdin.read().strip().split(','); print(','.join('\`'+p.strip().strip('\`')+'\`' for p in parts))")
  local ssl=false
  confirm "Enable HTTPS with Let's Encrypt?" true && ssl=true || true
  local custom_image=""
  if confirm "Use a custom Docker image?" false; then
    custom_image=$(ask "Custom image (e.g. sankarprakashm/frappe:v15)" "")
  fi

  local env_path="$GITOPS/${project}.env"
  python3 - "$(pwd)/example.env" "$env_path" "$db_pass" "$db_host" "$db_port" "$le_email" "$sites" "$project" <<'PYEOF'
import re, sys
src, dst, db_pass, db_host, db_port, le_email, sites, project = sys.argv[1:]
text = open(src).read()
for pat, val in [
    (r'^DB_PASSWORD=.*', f'DB_PASSWORD={db_pass}'),
    (r'^DB_HOST=.*',     f'DB_HOST={db_host}'),
    (r'^DB_PORT=.*',     f'DB_PORT={db_port}'),
    (r'^LETSENCRYPT_EMAIL=.*', f'LETSENCRYPT_EMAIL={le_email}'),
    (r'^SITES=.*',       f'SITES={sites}'),
]:
    text = re.sub(pat, val, text, flags=re.MULTILINE)
text += f'\nROUTER={project}\nBENCH_NETWORK={project}\n'
open(dst, 'w').write(text)
PYEOF
  info "Wrote $env_path"

  local files="-f compose.yaml -f overrides/compose.redis.yaml -f overrides/compose.multi-bench.yaml"
  [[ "$ssl" == "true" ]] && files+=" -f overrides/compose.multi-bench-ssl.yaml"
  [[ "$db_type" == "postgres" ]] && files+=" -f overrides/compose.postgres.yaml"

  local yaml_path="$GITOPS/${project}.yaml"
  info "Generating resolved compose config …"
  if ! eval "docker compose --project-name ${project} --env-file ${env_path} ${files} config > ${yaml_path}"; then
    error "Failed to generate compose config."; return
  fi

  if [[ -n "$custom_image" ]]; then
    info "Patching image → $custom_image"
    python3 -c "
import re, sys
p=sys.argv[1]; img=sys.argv[2]
text=open(p).read()
text=re.sub(r'^(\s+)image:.*', lambda m: m.group(1)+'image: '+img, text, flags=re.MULTILINE)
open(p,'w').write(text)
" "$yaml_path" "$custom_image"
  fi

  if docker compose --project-name "$project" -f "$yaml_path" up -d; then
    success "Bench '$project' is running."
    info "Next: create a site with option 13."
  else
    error "Bench failed to start. Check: docker compose logs"
  fi
}

# ── 13. Create Site ───────────────────────────────────────────────────────────
create_bench_site() {
  banner "Create a New Frappe Site"
  require_docker || return
  local projects; projects=$(list_bench_projects | tr '\n' ' ')
  [[ -n "$projects" ]] && info "Known projects: $projects"
  local project; project=$(ask "Project name" "erpnext-one")
  local site;    site=$(ask "Site domain (must match your SITES setting)")
  [[ -z "$site" ]] && error "Site name cannot be empty." && return
  validate_domain "$site" || warn "Site name looks unusual, proceeding anyway."
  local db_root_pass; db_root_pass=$(ask_password "DB root password" "changeit")
  local admin_pass;   admin_pass=$(ask_password "Site admin password" "changeit")
  info "Creating site … (this may take a minute)"
  if docker compose --project-name "$project" exec backend bench new-site \
      --mariadb-user-host-login-scope=% \
      --db-root-password "$db_root_pass" \
      --admin-password "$admin_pass" "$site"; then
    docker compose --project-name "$project" exec backend bench use "$site"
    docker compose --project-name "$project" exec backend bench migrate
    docker compose --project-name "$project" exec backend bench clear-cache
    success "Site is ready!"
    printf "\n  ${BOLD}URL:${RESET}   https://%s/app\n" "$site"
    printf "  ${BOLD}Login:${RESET} Administrator / %s\n\n" "$admin_pass"
  else
    error "Site creation failed."
  fi
}

# ── 14. Install App ───────────────────────────────────────────────────────────
install_app() {
  banner "Install an App on a Site"
  require_docker || return
  local projects; projects=$(list_bench_projects | tr '\n' ' ')
  [[ -n "$projects" ]] && info "Known projects: $projects"
  local project; project=$(ask "Project name" "erpnext-one")
  local site;     site=$(ask "Site name")
  local app_name; app_name=$(ask "App name (e.g. erpnext, hrms, payments)")
  [[ -z "$app_name" ]] && error "App name cannot be empty." && return
  if docker compose --project-name "$project" exec backend bench --site "$site" install-app "$app_name"; then
    docker compose --project-name "$project" exec backend bench --site "$site" migrate
    success "App '$app_name' installed on $site."
  else
    error "App installation failed."
  fi
}

# ── 15. Uninstall App ─────────────────────────────────────────────────────────
uninstall_app() {
  banner "Uninstall an App from a Site"
  require_docker || return
  local projects; projects=$(list_bench_projects | tr '\n' ' ')
  [[ -n "$projects" ]] && info "Known projects: $projects"
  local project; project=$(ask "Project name" "erpnext-one")
  local site;     site=$(ask "Site name")
  local app_name; app_name=$(ask "App name to uninstall (e.g. erpnext, hrms)")
  [[ -z "$app_name" || -z "$site" ]] && error "Site and app name cannot be empty." && return
  warn "This will remove '$app_name' and all its data from $site."
  confirm "Continue?" false || { info "Cancelled."; return; }
  if docker compose --project-name "$project" exec backend bench --site "$site" uninstall-app "$app_name"; then
    docker compose --project-name "$project" exec backend bench --site "$site" migrate
    success "App '$app_name' uninstalled from $site."
  else
    error "Uninstall failed."
  fi
}

# ── 16. Migrate Site ──────────────────────────────────────────────────────────
migrate_site() {
  banner "Migrate Site"
  require_docker || return
  printf "\n"; info "Runs pending database migrations."; printf "\n"
  local projects; projects=$(list_bench_projects | tr '\n' ' ')
  [[ -n "$projects" ]] && info "Known projects: $projects"
  local project; project=$(ask "Project name" "erpnext-one")
  local site;    site=$(ask "Site name")
  [[ -z "$site" ]] && error "Site name cannot be empty." && return
  if docker compose --project-name "$project" exec backend bench --site "$site" migrate; then
    success "Migration complete for $site."
  else
    error "Migration failed."
  fi
}

# ── 17. Clear Cache ───────────────────────────────────────────────────────────
clear_site_cache() {
  banner "Clear Site Cache"
  require_docker || return
  printf "\n"; info "Clears Redis cache for a site."; printf "\n"
  local projects; projects=$(list_bench_projects | tr '\n' ' ')
  [[ -n "$projects" ]] && info "Known projects: $projects"
  local project; project=$(ask "Project name" "erpnext-one")
  local site;    site=$(ask "Site name")
  [[ -z "$site" ]] && error "Site name cannot be empty." && return
  if docker compose --project-name "$project" exec backend bench --site "$site" clear-cache; then
    docker compose --project-name "$project" exec backend bench --site "$site" clear-website-cache
    success "Cache cleared for $site."
  else
    error "Clear cache failed."
  fi
}

# ── 18. Maintenance Mode ──────────────────────────────────────────────────────
maintenance_mode() {
  banner "Set Maintenance Mode"
  require_docker || return
  local projects; projects=$(list_bench_projects | tr '\n' ' ')
  [[ -n "$projects" ]] && info "Known projects: $projects"
  local project; project=$(ask "Project name" "erpnext-one")
  local site;    site=$(ask "Site name")
  [[ -z "$site" ]] && error "Site name cannot be empty." && return
  printf "\n  ${BOLD}1.${RESET} ${YELLOW}Enable${RESET}  — take site offline\n"
  printf "  ${BOLD}2.${RESET} ${GREEN}Disable${RESET} — bring site back online\n\n"
  local choice; choice=$(ask "Choose [1/2]" "1")
  if [[ "$choice" == "1" ]]; then
    docker compose --project-name "$project" exec backend bench --site "$site" set-maintenance-mode on && \
      success "Maintenance mode ON for $site." || error "Failed to enable maintenance mode."
  else
    docker compose --project-name "$project" exec backend bench --site "$site" set-maintenance-mode off && \
      success "Maintenance mode OFF for $site." || error "Failed to disable maintenance mode."
  fi
}

# ── 19. Toggle Scheduler ──────────────────────────────────────────────────────
toggle_scheduler() {
  banner "Enable / Disable Scheduler"
  require_docker || return
  local projects; projects=$(list_bench_projects | tr '\n' ' ')
  [[ -n "$projects" ]] && info "Known projects: $projects"
  local project; project=$(ask "Project name" "erpnext-one")
  local site;    site=$(ask "Site name")
  [[ -z "$site" ]] && error "Site name cannot be empty." && return
  printf "\n  ${BOLD}1.${RESET} ${GREEN}Enable${RESET}  — start scheduler\n"
  printf "  ${BOLD}2.${RESET} ${YELLOW}Disable${RESET} — pause scheduler\n\n"
  local choice; choice=$(ask "Choose [1/2]" "1")
  if [[ "$choice" == "1" ]]; then
    docker compose --project-name "$project" exec backend bench --site "$site" enable-scheduler && \
      success "Scheduler enabled for $site." || error "Failed to enable scheduler."
  else
    docker compose --project-name "$project" exec backend bench --site "$site" disable-scheduler && \
      success "Scheduler disabled for $site." || error "Failed to disable scheduler."
  fi
}

# ── 20. Drop Site ─────────────────────────────────────────────────────────────
drop_site() {
  banner "Drop / Delete a Site"
  require_docker || return
  warn "This permanently deletes the site, its database, and all files."
  local projects; projects=$(list_bench_projects | tr '\n' ' ')
  [[ -n "$projects" ]] && info "Known projects: $projects"
  local project; project=$(ask "Project name" "erpnext-one")
  local site;    site=$(ask "Site name")
  [[ -z "$site" ]] && error "Site name cannot be empty." && return
  local db_root_pass; db_root_pass=$(ask_password "DB root password" "changeit")
  warn "About to permanently delete site: $site"
  confirm "Are you absolutely sure?" false || { info "Cancelled."; return; }
  if docker compose --project-name "$project" exec backend bench drop-site \
      --db-root-password "$db_root_pass" --archived-sites "$site"; then
    success "Site '$site' dropped."
  else
    error "Drop failed. The site may still exist."
  fi
}

# ── 21. Restore Backup ────────────────────────────────────────────────────────
restore_backup() {
  banner "Restore Site from Backup"
  require_docker || return
  local projects; projects=$(list_bench_projects | tr '\n' ' ')
  [[ -n "$projects" ]] && info "Known projects: $projects"
  local project; project=$(ask "Project name" "erpnext-one")
  local site;    site=$(ask "Site name to restore INTO")
  [[ -z "$site" ]] && error "Site name cannot be empty." && return
  local backup_file; backup_file=$(ask "Backup file path (inside container, e.g. sites/mysite/private/backups/db.sql.gz)")
  [[ -z "$backup_file" ]] && error "Backup file path cannot be empty." && return
  local db_root_pass; db_root_pass=$(ask_password "DB root password" "changeit")
  local admin_pass;   admin_pass=$(ask_password "New admin password for restored site" "changeit")
  confirm "Restore $backup_file into site '$site'?" true || { info "Cancelled."; return; }
  if docker compose --project-name "$project" exec backend bench --site "$site" restore \
      --db-root-password "$db_root_pass" --admin-password "$admin_pass" "$backup_file"; then
    success "Restore complete for $site."
    info "Run 'Migrate site' next to apply any pending migrations."
  else
    error "Restore failed. Check the backup file path and DB password."
  fi
}

# ── 22. View Images ───────────────────────────────────────────────────────────
view_images() {
  banner "View Docker Images"
  require_docker || return
  printf "\n  ${BOLD}1.${RESET} Frappe / ERPNext images only ${DIM}(default)${RESET}\n"
  printf "  ${BOLD}2.${RESET} All local images\n"
  printf "  ${BOLD}3.${RESET} Search by name\n\n"
  local choice; choice=$(ask "Choose [1/2/3]" "1")
  local fmt='table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedSince}}'
  case "$choice" in
    2) docker images --format "$fmt" ;;
    3) local term; term=$(ask "Image name or keyword")
       docker images "$term" --format "$fmt" ;;
    *) printf "\n  ${BOLD}REPOSITORY\tTAG\tID\tSIZE\tCREATED${RESET}\n"
       docker images --format '{{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedSince}}' \
         | grep -iE 'frappe|erpnext|hrms|sankarprakashm' || warn "No frappe/erpnext images found locally." ;;
  esac
  printf "\n"
  if confirm "Remove an image?" false; then
    local image_id; image_id=$(ask "Image name:tag or ID to remove")
    if [[ -n "$image_id" ]]; then
      docker rmi "$image_id" && success "Removed: $image_id" || error "Remove failed. Is the image in use?"
    fi
  fi
}

# ── apps.json helpers ─────────────────────────────────────────────────────────
_show_apps() {
  local apps_json="$1"
  python3 -c "
import json, sys
apps = json.loads(open(sys.argv[1]).read()) if __import__('os').path.exists(sys.argv[1]) else []
for i, a in enumerate(apps, 1):
    print(f'  \033[1m{i}.\033[0m \033[36m{a[\"url\"]}\033[0m  branch: \033[1m{a[\"branch\"]}\033[0m')
" "$apps_json" 2>/dev/null || true
}

_edit_apps_list() {
  local apps_json="$1" default_branch="$2"
  printf "\n"; info "Build your apps list (installed inside the image)."
  info "Leave URL empty when done."; printf "\n"

  while true; do
    _show_apps "$apps_json"
    printf "  ${BOLD}a.${RESET} Add app\n"
    local count; count=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" "$apps_json" 2>/dev/null || echo 0)
    [[ "$count" -gt 0 ]] && printf "  ${BOLD}r.${RESET} Remove an app\n"
    printf "  ${BOLD}d.${RESET} Done\n\n"
    local default_act="a"; [[ "$count" -gt 0 ]] && default_act="d"
    local act; act=$(ask "Action [a/r/d]" "$default_act")
    act="${act,,}"

    case "$act" in
      d*) break ;;
      r*) if [[ "$count" -gt 0 ]]; then
            local idx; idx=$(ask "Remove which? [1-$count]")
            python3 -c "
import json, sys
apps=json.load(open(sys.argv[1]))
idx=int(sys.argv[2])-1
if 0<=idx<len(apps):
    removed=apps.pop(idx)
    json.dump(apps, open(sys.argv[1],'w'), indent=2)
    print(f'  Removed: {removed[\"url\"]}')
" "$apps_json" "$idx" 2>/dev/null || true
          fi ;;
      a*) local url; url=$(ask "App git URL")
          [[ -z "$url" ]] && continue
          local branch; branch=$(ask "Branch" "$default_branch")
          python3 -c "
import json, sys, os
p=sys.argv[1]
apps=json.load(open(p)) if os.path.exists(p) else []
apps.append({'url':sys.argv[2],'branch':sys.argv[3]})
json.dump(apps,open(p,'w'),indent=2)
print(f'  Added: {sys.argv[2]}  [{sys.argv[3]}]')
" "$apps_json" "$url" "$branch" ;;
    esac
  done
}

# ── 23. Create Custom Image ───────────────────────────────────────────────────
create_image() {
  banner "Create Custom Frappe / ERPNext Docker Image"
  require_docker || return
  require_repo   || return

  local image_name; image_name=$(ask "Image name" "sankarprakashm/frappe")
  local image_tag;  image_tag=$(ask "Image tag" "v15.0.0")
  local full_image="${image_name}:${image_tag}"

  local frappe_branch; frappe_branch=$(ask "Frappe branch" "version-15")
  local frappe_path;   frappe_path=$(ask "Frappe git URL" "https://github.com/frappe/frappe")

  printf "\n  ${BOLD}Build type:${RESET}\n"
  printf "  ${BOLD}1.${RESET} ${CYAN}custom${RESET}   — full build (images/custom/Containerfile)\n"
  printf "  ${BOLD}2.${RESET} ${CYAN}layered${RESET}  — builds on frappe/build base (faster)\n\n"
  local build_choice; build_choice=$(ask "Choose [1/2]" "1")
  local containerfile="images/custom/Containerfile"
  [[ "$build_choice" == "2" ]] && containerfile="images/layered/Containerfile"

  local python_version; python_version=$(ask "Python version" "3.12.4")
  local node_version;   node_version=$(ask "Node version" "18.17.1")

  local dev_dir="$(pwd)/development"
  mkdir -p "$dev_dir"
  local apps_json_path="$dev_dir/apps.json"
  [[ ! -f "$apps_json_path" ]] && echo "[]" > "$apps_json_path"

  _edit_apps_list "$apps_json_path" "$frappe_branch"

  local app_count; app_count=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" "$apps_json_path" 2>/dev/null || echo 0)
  if [[ "$app_count" -eq 0 ]]; then
    warn "No apps specified. Image will contain Frappe framework only."
    confirm "Continue without extra apps?" true || return
  fi

  success "Saved apps.json → $apps_json_path"
  python3 -c "import json,sys; print(json.dumps(json.load(open(sys.argv[1])),indent=4))" "$apps_json_path"

  local multiplatform=false platforms=""
  if confirm "Build for multiple platforms (linux/amd64 + linux/arm64)?" false; then
    if docker buildx version &>/dev/null 2>&1; then
      multiplatform=true
      platforms=$(ask "Platforms" "linux/amd64,linux/arm64")
    else
      warn "docker buildx not found. Falling back to single-platform build."
    fi
  fi

  local apps_b64; apps_b64=$(base64 -w 0 "$apps_json_path" 2>/dev/null || base64 "$apps_json_path")
  local build_args=(
    "--no-cache"
    "--secret id=apps_json,src=development/apps.json"
    "--build-arg=FRAPPE_PATH=${frappe_path}"
    "--build-arg=FRAPPE_BRANCH=${frappe_branch}"
    "--build-arg=PYTHON_VERSION=${python_version}"
    "--build-arg=NODE_VERSION=${node_version}"
    "--build-arg=APPS_JSON_BASE64=${apps_b64}"
    "-t ${full_image}"
    "-f ${containerfile}"
  )

  printf "\n  ${BOLD}Image        :${RESET} ${CYAN}%s${RESET}\n" "$full_image"
  printf "  ${BOLD}Containerfile:${RESET} %s\n" "$containerfile"
  printf "  ${BOLD}Frappe       :${RESET} %s  (%s)\n" "$frappe_branch" "$frappe_path"
  printf "  ${BOLD}Python       :${RESET} %s   Node: %s\n" "$python_version" "$node_version"
  printf "  ${BOLD}Apps         :${RESET} %s app(s) → development/apps.json\n" "$app_count"
  [[ "$multiplatform" == "true" ]] && printf "  ${BOLD}Platforms    :${RESET} %s\n" "$platforms"
  printf "\n"

  confirm "Start build now?" true || { info "Build cancelled. apps.json saved."; return; }

  local cmd
  if [[ "$multiplatform" == "true" ]]; then
    local push_now=false
    confirm "Push $full_image to registry during build? (multi-platform requires --push)" true && push_now=true || true
    if [[ "$push_now" == "true" ]]; then
      cmd="DOCKER_BUILDKIT=1 docker buildx build --platform $platforms --push ${build_args[*]} ."
    else
      cmd="DOCKER_BUILDKIT=1 docker build ${build_args[*]} ."
    fi
  else
    cmd="DOCKER_BUILDKIT=1 docker build ${build_args[*]} ."
  fi

  info "Building … this can take 10-30 minutes."
  if eval "$cmd"; then
    success "Image ready: $full_image"
    if [[ "$multiplatform" != "true" ]] && confirm "Push $full_image to registry?" false; then
      docker push "$full_image" && success "Pushed: $full_image" || error "Push failed. Run: docker login"
    fi
  else
    error "Image build failed. Check the output above."
  fi
}

# ── 24. Update Image ──────────────────────────────────────────────────────────
update_image() {
  banner "Update Image with Latest Git Code"
  require_docker || return
  require_repo   || return

  local apps_json_path="$(pwd)/apps.json"
  [[ ! -f "$apps_json_path" ]] && echo "[]" > "$apps_json_path"

  local app_count; app_count=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" "$apps_json_path" 2>/dev/null || echo 0)
  if [[ "$app_count" -gt 0 ]]; then
    info "Found apps.json with $app_count app(s):"
    _show_apps "$apps_json_path"
  else
    warn "No apps in apps.json."
    confirm "Continue with no extra apps (Frappe only)?" false || return
  fi

  if [[ "$app_count" -gt 0 ]] && confirm "Edit apps.json before rebuilding?" false; then
    local hint; hint=$(python3 -c "import json,sys; apps=json.load(open(sys.argv[1])); print(apps[0].get('branch','version-15') if apps else 'version-15')" "$apps_json_path")
    _edit_apps_list "$apps_json_path" "$hint"
    success "Updated apps.json → $apps_json_path"
  fi

  local existing; existing=$(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -iE 'frappe|erpnext|hrms|sankarprakashm' || true)
  [[ -n "$existing" ]] && info "Existing local Frappe images:" && echo "$existing" | while IFS= read -r l; do printf "      ${CYAN}%s${RESET}\n" "$l"; done

  local old_image; old_image=$(ask "Image name:tag to rebuild")
  [[ -z "$old_image" ]] && error "Image name cannot be empty." && return

  printf "\n  ${BOLD}1.${RESET} Keep same tag ${DIM}(${old_image})${RESET} — overwrites existing\n"
  printf "  ${BOLD}2.${RESET} Enter a new tag — keeps old image intact\n\n"
  local tag_choice; tag_choice=$(ask "Choose [1/2]" "1")
  local full_image="$old_image"
  if [[ "$tag_choice" == "2" ]]; then
    local new_tag; new_tag=$(ask "New tag (e.g. v15.1.0)")
    [[ -z "$new_tag" ]] && error "Tag cannot be empty." && return
    full_image="${old_image%:*}:${new_tag}"
  fi

  local frappe_branch; frappe_branch=$(ask "Frappe branch" "version-15")
  local frappe_path;   frappe_path=$(ask "Frappe git URL" "https://github.com/frappe/frappe")
  printf "\n  ${BOLD}1.${RESET} custom   — images/custom/Containerfile\n"
  printf "  ${BOLD}2.${RESET} layered  — images/layered/Containerfile\n\n"
  local use_layered_choice; use_layered_choice=$(ask "Choose [1/2]" "1")
  local containerfile="images/custom/Containerfile"
  [[ "$use_layered_choice" == "2" ]] && containerfile="images/layered/Containerfile"

  local python_version="" node_version=""
  if [[ "$use_layered_choice" != "2" ]]; then
    python_version=$(ask "Python version" "3.11.6")
    node_version=$(ask "Node version" "18.18.2")
  fi

  local apps_b64=""; [[ -f "$apps_json_path" ]] && apps_b64=$(base64 -w 0 "$apps_json_path" 2>/dev/null || base64 "$apps_json_path")

  local build_args=("--build-arg FRAPPE_PATH=$frappe_path" "--build-arg FRAPPE_BRANCH=$frappe_branch" "--tag $full_image" "--file $containerfile" "--no-cache")
  [[ -n "$apps_b64" ]] && build_args+=("--build-arg APPS_JSON_BASE64=$apps_b64")
  [[ -n "$python_version" ]] && build_args+=("--build-arg PYTHON_VERSION=$python_version")
  [[ -n "$node_version" ]] && build_args+=("--build-arg NODE_VERSION=$node_version")

  printf "\n  ${BOLD}Rebuilding    :${RESET} ${CYAN}%s${RESET}\n" "$full_image"
  printf "  ${BOLD}Containerfile :${RESET} %s\n" "$containerfile"
  printf "  ${BOLD}Frappe branch :${RESET} %s\n" "$frappe_branch"
  printf "  ${BOLD}Cache         :${RESET} ${RED}disabled (--no-cache)${RESET}\n\n"

  confirm "Start rebuild now?" true || return
  info "Rebuilding … all apps will be freshly cloned from git."
  if eval "docker build ${build_args[*]} ."; then
    success "Image updated: $full_image"
    confirm "Push $full_image to registry?" false && \
      (docker push "$full_image" && success "Pushed: $full_image" || error "Push failed. Run: docker login")
  else
    error "Rebuild failed."
  fi
}

# ── 25. Update Bench ──────────────────────────────────────────────────────────
update_bench() {
  banner "Update Bench (Pull → Restart → Migrate)"
  require_docker || return
  require_repo   || return
  local projects; projects=$(list_bench_projects | tr '\n' ' ')
  [[ -n "$projects" ]] && info "Known projects: $projects"
  local project; project=$(ask "Project name" "erpnext-one")
  local yaml_path="$GITOPS/${project}.yaml"
  [[ ! -f "$yaml_path" ]] && error "No compose YAML at $yaml_path. Deploy bench first." && return
  local current_img; current_img=$(grep 'image:' "$yaml_path" 2>/dev/null | head -1 | awk '{print $2}' || true)
  [[ -n "$current_img" ]] && info "Current image: $current_img"
  local new_img; new_img=$(ask "Image to pull (leave blank to keep current)" "$current_img")
  [[ -z "$new_img" ]] && error "Image cannot be empty." && return

  info "Step 1/4 — Pulling latest image …"
  docker pull "$new_img" || { error "Image pull failed."; return; }
  success "Image pulled."

  info "Step 2/4 — Patching image in compose YAML …"
  python3 -c "
import re, sys
p, img = sys.argv[1], sys.argv[2]
text = re.sub(r'^(\s+image:\s+)\S+', lambda m: m.group(1)+img, open(p).read(), flags=re.MULTILINE)
open(p,'w').write(text)
" "$yaml_path" "$new_img"
  success "YAML updated."

  info "Step 3/4 — Restarting bench …"
  docker compose --project-name "$project" -f "$yaml_path" up -d --no-deps \
    backend queue-long queue-short scheduler websocket || { error "Restart failed."; return; }
  success "Bench restarted."

  info "Step 4/4 — Running migrations on all sites …"
  if docker compose --project-name "$project" exec backend bench --all-sites migrate; then
    docker compose --project-name "$project" exec backend bench --all-sites clear-cache
    success "All sites migrated and cache cleared."
  else
    error "Migration failed. Run 'Migrate site' manually for each site."
  fi
  success "Bench '$project' updated to $new_img."
}

# ── 26. Stop Bench ────────────────────────────────────────────────────────────
stop_bench() {
  banner "Stop a Bench"
  require_docker || return
  local projects; projects=$(list_bench_projects | tr '\n' ' ')
  [[ -n "$projects" ]] && info "Known projects: $projects"
  local project; project=$(ask "Project name" "erpnext-one")
  local yaml_path="$GITOPS/${project}.yaml"
  local cmd="docker compose --project-name $project"
  [[ -f "$yaml_path" ]] && cmd+=" -f $yaml_path"
  cmd+=" down"
  eval "$cmd" && success "Bench '$project' stopped." || error "Stop command failed."
}

# ── 27. Show Status ───────────────────────────────────────────────────────────
show_status() {
  banner "Running Docker Containers"
  require_docker || return
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
}

# ── 28. Show Logs ─────────────────────────────────────────────────────────────
show_logs() {
  banner "View Container Logs"
  require_docker || return
  local projects; projects=$(list_bench_projects | tr '\n' ' ')
  [[ -n "$projects" ]] && info "Known projects: $projects"
  local project; project=$(ask "Project name (or 'traefik' / 'mariadb')")
  local service;  service=$(ask "Service (leave empty for all)" "")
  local lines;    lines=$(ask "Lines to show" "50")
  local yaml_path="$GITOPS/${project}.yaml"
  local cmd="docker compose --project-name $project"
  [[ -f "$yaml_path" ]] && cmd+=" -f $yaml_path"
  cmd+=" logs --tail=$lines $service"
  eval "$cmd"
}

# ── 29. Backup Sites ──────────────────────────────────────────────────────────
backup_sites() {
  banner "Backup All Sites"
  require_docker || return
  local projects; projects=$(list_bench_projects | tr '\n' ' ')
  [[ -n "$projects" ]] && info "Known projects: $projects"
  local project; project=$(ask "Project name" "erpnext-one")
  if docker compose --project-name "$project" exec backend bench --all-sites backup --with-files; then
    success "Backup complete. Files are inside the sites volume."
  else
    error "Backup failed."
  fi
}

# ── 30. Push Backup to S3 ─────────────────────────────────────────────────────
push_backup_s3() {
  banner "Push Backup to S3 / Compatible Storage"
  require_docker || return
  local projects; projects=$(list_bench_projects | tr '\n' ' ')
  [[ -n "$projects" ]] && info "Known projects: $projects"
  local project;     project=$(ask "Project name" "erpnext-one")
  local bucket;      bucket=$(ask "S3 bucket name")
  local region;      region=$(ask "AWS region" "us-east-1")
  local access_key;  access_key=$(ask "AWS access key ID")
  local secret_key;  secret_key=$(ask_password "AWS secret access key")
  local endpoint;    endpoint=$(ask "Endpoint URL (leave blank for AWS)" "")
  local backup_path; backup_path=$(ask "S3 folder/prefix" "frappe-backups/$project")
  [[ -z "$bucket" || -z "$access_key" || -z "$secret_key" ]] && error "Bucket, access key and secret key are required." && return

  info "Running backup …"
  docker compose --project-name "$project" exec backend bench --all-sites backup --with-files || \
    { error "Backup failed."; return; }
  success "Local backup created."

  local endpoint_arg=""; [[ -n "$endpoint" ]] && endpoint_arg="--endpoint-url $endpoint"
  info "Pushing to S3 …"
  local push_cmd="docker compose --project-name $project exec \
    -e AWS_ACCESS_KEY_ID=$access_key \
    -e AWS_SECRET_ACCESS_KEY=$secret_key \
    -e AWS_DEFAULT_REGION=$region \
    backend bash -c \"pip install awscli -q && \
    aws s3 sync /home/frappe/frappe-bench/sites s3://${bucket}/${backup_path} \
    --exclude '*' --include '*/private/backups/*' $endpoint_arg\""
  eval "$push_cmd" && success "Backups pushed to s3://${bucket}/${backup_path}" || error "S3 push failed. Check credentials and bucket name."
}

# ── 31. Bench Console ─────────────────────────────────────────────────────────
bench_console() {
  banner "Bench Console (Python Shell)"
  require_docker || return
  local projects; projects=$(list_bench_projects | tr '\n' ' ')
  [[ -n "$projects" ]] && info "Known projects: $projects"
  local project; project=$(ask "Project name" "erpnext-one")
  local site;    site=$(ask "Site name")
  [[ -z "$site" ]] && error "Site name cannot be empty." && return
  info "Opening bench console for $site … (type 'exit' or Ctrl+D to quit)"
  docker compose --project-name "$project" exec backend bench --site "$site" console
}

# ── 32. Clean Docker ──────────────────────────────────────────────────────────
clean_docker() {
  banner "Clean Docker — Volumes, Networks & Cache"
  require_docker || return
  printf "\n  ${BOLD}What this removes:${RESET}\n"
  printf "  ${DIM}  Volumes  — all unused named volumes (⚠ permanently deletes Frappe data)${RESET}\n"
  printf "  ${DIM}  Networks — all unused custom networks${RESET}\n"
  printf "  ${DIM}  Cache    — Docker build cache${RESET}\n\n"

  local usage; usage=$(docker system df 2>/dev/null || true)
  if [[ -n "$usage" ]]; then
    printf "  ${BOLD}Current Docker disk usage:${RESET}\n"
    echo "$usage" | while IFS= read -r line; do printf "  ${DIM}%s${RESET}\n" "$line"; done
    printf "\n"
  fi

  printf "  ${BOLD}Select what to clean:${RESET}\n"
  printf "  ${BOLD}1.${RESET} Volumes only\n"
  printf "  ${BOLD}2.${RESET} Networks only\n"
  printf "  ${BOLD}3.${RESET} Build cache only\n"
  printf "  ${BOLD}4.${RESET} Volumes + Networks + Build cache ${DIM}(full clean)${RESET}\n"
  printf "  ${BOLD}5.${RESET} Everything above + unused images ${DIM}(deepest clean)${RESET}\n\n"
  local choice; choice=$(ask "Choose [1-5]" "4")

  local do_volumes=false do_networks=false do_cache=false do_images=false
  [[ "$choice" =~ ^[145]$ ]] && do_volumes=true
  [[ "$choice" =~ ^[245]$ ]] && do_networks=true
  [[ "$choice" =~ ^[345]$ ]] && do_cache=true
  [[ "$choice" == "5" ]]     && do_images=true

  local sudo_prefix; sudo_prefix=$(_sudo)
  if [[ "$do_volumes" == "true" ]]; then
    local pwd_yml="$(pwd)/pwd.yml"
    if [[ -f "$pwd_yml" ]]; then
      local running; running=$(eval "${sudo_prefix}docker compose -f pwd.yml ps --services --filter status=running 2>/dev/null" || true)
      if [[ -n "$running" ]]; then
        warn "pwd.yml stack is running — must be stopped before volume cleanup."
        if confirm "Stop the pwd.yml stack now?" true; then
          eval "${sudo_prefix}docker compose -f pwd.yml down"
        else
          warn "Skipping volume cleanup."; do_volumes=false
        fi
      fi
    fi
  fi

  warn "About to remove selected items. This may be irreversible."
  confirm "Proceed?" false || { info "Cancelled."; return; }

  [[ "$do_volumes"  == "true" ]] && { info "Removing unused volumes …";  docker volume prune -f  && success "Volumes removed."       || error "Volume prune failed."; }
  [[ "$do_networks" == "true" ]] && { info "Removing unused networks …"; docker network prune -f && success "Networks removed."      || error "Network prune failed."; }
  [[ "$do_cache"    == "true" ]] && { info "Clearing build cache …";     docker builder prune -f && success "Build cache cleared."   || error "Cache prune failed."; }
  [[ "$do_images"   == "true" ]] && { info "Removing unused images …";   docker image prune -f   && success "Unused images removed." || error "Image prune failed."; }

  printf "\n"
  local after; after=$(docker system df 2>/dev/null || true)
  if [[ -n "$after" ]]; then
    printf "  ${BOLD}Docker disk usage after clean:${RESET}\n"
    echo "$after" | while IFS= read -r line; do printf "  ${DIM}%s${RESET}\n" "$line"; done
  fi
  printf "\n"; success "Cleanup complete."
}

# ── Status Panel ──────────────────────────────────────────────────────────────
_os_label() {
  if [[ "$IS_MACOS" == "true" ]]; then
    local ver; ver=$(sw_vers -productVersion 2>/dev/null || true)
    echo "macOS ${ver}"
  elif [[ -f /etc/os-release ]]; then
    grep '^PRETTY_NAME=' /etc/os-release | cut -d= -f2 | tr -d '"' || echo "Linux"
  else
    uname -sr
  fi
}

print_status() {
  local W=14
  printf "  ${DIM}%s${RESET}\n" "──────────────────────────────────────────────────────────"
  printf "  ${BOLD}%-${W}s${RESET} ${CYAN}%s${RESET}\n" "OS Type" "$(_os_label)"

  if command -v docker &>/dev/null; then
    printf "  ${BOLD}%-${W}s${RESET} ${GREEN}✔  installed${RESET}\n" "Docker"
  else
    printf "  ${BOLD}%-${W}s${RESET} ${RED}✖  not installed  →  run option 1${RESET}\n" "Docker"
  fi

  if repo_is_ready; then
    printf "  ${BOLD}%-${W}s${RESET} ${GREEN}✔  selected${RESET}  ${DIM}%s${RESET}\n" "Repo" "$(pwd)"
  else
    printf "  ${BOLD}%-${W}s${RESET} ${YELLOW}✖  not selected${RESET}  ${DIM}→ run option 2${RESET}\n" "Repo"
  fi

  if [[ -d "$GITOPS" ]]; then
    printf "  ${BOLD}%-${W}s${RESET} ${GREEN}✔  selected${RESET}  ${DIM}%s${RESET}\n" "Gitops" "$GITOPS"
  else
    printf "  ${BOLD}%-${W}s${RESET} ${YELLOW}✖  not selected${RESET}\n" "Gitops"
  fi

  for svc in "Traefik traefik" "MariaDB mariadb" "PostgreSQL postgres"; do
    local name proj; name=$(echo "$svc" | cut -d' ' -f1); proj=$(echo "$svc" | cut -d' ' -f2)
    local env_f="$GITOPS/${proj}.env"
    if [[ -f "$env_f" ]]; then
      if container_running "$proj"; then
        printf "  ${BOLD}%-${W}s${RESET} ${GREEN}✔  running${RESET}   ${DIM}%s${RESET}\n" "$name" "$env_f"
      else
        printf "  ${BOLD}%-${W}s${RESET} ${RED}✖  stopped${RESET}   ${DIM}%s${RESET}\n" "$name" "$env_f"
      fi
    else
      printf "  ${BOLD}%-${W}s${RESET} ${DIM}─  not configured${RESET}\n" "$name"
    fi
  done
  printf "  ${DIM}%s${RESET}\n" "──────────────────────────────────────────────────────────"
}

# ── Menu ──────────────────────────────────────────────────────────────────────
declare -a MENU_LABELS MENU_FUNCS
MENU_LABELS=(
  "Install Docker & Docker Compose"
  "Set active frappe_docker repo"
  "─── Local Deploy ───────────────────────────"
  "Local deploy via pwd.yml"
  "Local deploy status & diagnostics"
  "Stop local deploy"
  "Drop local deploy"
  "─── Live Infrastructure ────────────────────"
  "Setup Traefik reverse proxy"
  "Setup shared MariaDB database"
  "Setup shared PostgreSQL database"
  "Restart infrastructure servers"
  "Drop infrastructure services"
  "─── Live Bench & Sites ─────────────────────"
  "Deploy Frappe / ERPNext bench"
  "Create a new site"
  "Install an app on a site"
  "Uninstall an app from a site"
  "─── Live Site Operations ───────────────────"
  "Migrate site"
  "Clear site cache"
  "Set maintenance mode"
  "Enable / Disable scheduler"
  "Drop / Delete a site"
  "Restore site from backup"
  "─── Images ─────────────────────────────────"
  "View Docker images"
  "Create custom image (apps.json + build)"
  "Update image with latest git code"
  "─── Management ─────────────────────────────"
  "Update bench (pull → restart → migrate)"
  "Stop a bench"
  "View running containers"
  "View container logs"
  "Backup all sites"
  "Push backup to S3 storage"
  "Bench console (Python shell)"
  "Clean volumes, networks & build cache"
  "────────────────────────────────────────────"
  "Exit"
)
MENU_FUNCS=(
  "install_docker"
  "clone_or_navigate_repo"
  ""
  "local_deploy"
  "local_status"
  "stop_local_deploy"
  "drop_local_deploy"
  ""
  "create_traefik_env"
  "create_mariadb_env"
  "create_postgres_env"
  "restart_servers"
  "drop_infrastructure"
  ""
  "create_bench_env"
  "create_bench_site"
  "install_app"
  "uninstall_app"
  ""
  "migrate_site"
  "clear_site_cache"
  "maintenance_mode"
  "toggle_scheduler"
  "drop_site"
  "restore_backup"
  ""
  "view_images"
  "create_image"
  "update_image"
  ""
  "update_bench"
  "stop_bench"
  "show_status"
  "show_logs"
  "backup_sites"
  "push_backup_s3"
  "bench_console"
  "clean_docker"
  ""
  "exit"
)

print_menu() {
  printf "\n"
  print_status
  printf "\n"
  local num=0
  for i in "${!MENU_LABELS[@]}"; do
    local label="${MENU_LABELS[$i]}"
    if [[ "$label" == ─* ]]; then
      printf "  ${DIM}%s${RESET}\n" "$label"
    elif [[ "$label" == "Exit" ]]; then
      printf "  ${BOLD}  q.${RESET} %s\n" "$label"
    else
      num=$((num + 1))
      local suffix=""
      if [[ "${MENU_FUNCS[$i]}" == "clone_or_navigate_repo" ]]; then
        suffix="  ${YELLOW}← set this first${RESET}"
      elif ! repo_is_ready && [[ "${MENU_FUNCS[$i]}" != "" ]]; then
        : # no suffix for now
      fi
      printf "  ${BOLD}%2d.${RESET} %s%b\n" "$num" "$label" "$suffix"
    fi
  done
  printf "\n"
}

# Build selectable options array (skip separators and Exit)
declare -a OPT_LABELS OPT_FUNCS
for i in "${!MENU_LABELS[@]}"; do
  local_label="${MENU_LABELS[$i]}"
  if [[ "$local_label" != ─* && "$local_label" != "Exit" && -n "${MENU_FUNCS[$i]}" ]]; then
    OPT_LABELS+=("$local_label")
    OPT_FUNCS+=("${MENU_FUNCS[$i]}")
  fi
done

main() {
  printf "${BOLD}${CYAN}\n╔══════════════════════════════════════════════════════╗${RESET}\n"
  printf "${BOLD}${CYAN}║      Frappe / ERPNext Docker Deployment Wizard       ║${RESET}\n"
  printf "${BOLD}${CYAN}╚══════════════════════════════════════════════════════╝${RESET}\n"

  # Ctrl+C inside any option → print message and return to menu (never exit)
  trap 'printf "\n"; warn "Interrupted — returning to menu."' INT

  local total=${#OPT_FUNCS[@]}
  while true; do
    print_menu
    printf "  ${BOLD}?${RESET} Select [${BOLD}1${RESET}-${BOLD}%d${RESET} or ${BOLD}q${RESET}]: " "$total"
    local raw=""
    read -r raw </dev/tty || true
    raw="${raw,,}"

    # Empty input means Ctrl+C interrupted the read — go back to top of loop
    [[ -z "$raw" ]] && continue

    [[ "$raw" == "q" || "$raw" == "quit" || "$raw" == "exit" ]] && printf "${GREEN}\n  Goodbye!\n${RESET}\n" && exit 0

    if ! [[ "$raw" =~ ^[0-9]+$ ]] || (( raw < 1 || raw > total )); then
      warn "Invalid choice '$raw'. Enter a number between 1 and $total, or 'q' to quit."
      continue
    fi

    local fn="${OPT_FUNCS[$((raw-1))]}"
    local label="${OPT_LABELS[$((raw-1))]}"

    if [[ "$fn" != "install_docker" && "$fn" != "clone_or_navigate_repo" ]]; then
      if ! repo_is_ready && [[ "$fn" =~ local_deploy|local_status|stop_local_deploy|drop_local_deploy|create_traefik_env|create_mariadb_env|create_postgres_env|create_bench_env|create_bench_site|install_app|uninstall_app|migrate_site|clear_site_cache|maintenance_mode|toggle_scheduler|drop_site|restore_backup|view_images|create_image|update_image|update_bench|stop_bench|show_logs|backup_sites|push_backup_s3|bench_console ]]; then
        printf "\n"
        warn "'$label' requires an active frappe_docker repo."
        warn "Option 2 sets the repo — all other options work inside it."
        printf "\n"
        if confirm "Open the repo setup now? (option 2)" true; then
          clone_or_navigate_repo || true
          if ! repo_is_ready; then
            error "Repo still not set. Please complete option 2 before continuing."
            continue
          fi
        else
          info "Returning to menu."; continue
        fi
      fi
    fi

    "$fn" || true
  done
}

main "$@"
