#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOL_HOME="${JOLT_TOOL_HOME:-$HOME/.jolt-tools}"
BIN_DIR="$TOOL_HOME/bin"
TMP_DIR="${TMPDIR:-/tmp}/jolt-install.$$"
SKIP_SYSTEM_PACKAGES="${SKIP_SYSTEM_PACKAGES:-0}"
SKIP_PROJECT_DEPS="${SKIP_PROJECT_DEPS:-0}"
SKIP_STATIC_TOOLS="${SKIP_STATIC_TOOLS:-0}"
VERIFY_ONLY="${VERIFY_ONLY:-0}"

GITLEAKS_VERSION="${GITLEAKS_VERSION:-8.30.1}"
PMD_VERSION="${PMD_VERSION:-7.25.0}"
CHECKSTYLE_VERSION="${CHECKSTYLE_VERSION:-13.5.0}"
SPOTBUGS_VERSION="${SPOTBUGS_VERSION:-4.9.8}"
DEPENDENCY_CHECK_VERSION="${DEPENDENCY_CHECK_VERSION:-12.2.2}"
OSV_SCANNER_VERSION="${OSV_SCANNER_VERSION:-2.3.8}"
TRIVY_VERSION="${TRIVY_VERSION:-0.71.0}"
KICS_VERSION="${KICS_VERSION:-2.1.20}"

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

warn() {
  printf '\n[WARN] %s\n' "$*" >&2
}

usage() {
  cat <<EOF
Usage: bash scripts/install-linux.sh [options]

Installs Jolt CodeReview runtime dependencies and static-analysis tools.

Options:
  --tool-home DIR             Install downloaded CLI tools into DIR (default: $TOOL_HOME)
  --skip-system-packages      Do not install curl/git/java/python with apt/dnf/yum/pacman/zypper
  --skip-project-deps         Do not run npm install or create/update .venv
  --skip-static-tools         Do not install Semgrep/PMD/Checkstyle/etc.
  --verify-only               Only verify command availability; do not install anything
  -h, --help                  Show this help

Environment overrides:
  JOLT_TOOL_HOME, GITLEAKS_VERSION, PMD_VERSION, CHECKSTYLE_VERSION,
  SPOTBUGS_VERSION, DEPENDENCY_CHECK_VERSION, OSV_SCANNER_VERSION,
  TRIVY_VERSION, KICS_VERSION
EOF
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --tool-home)
        TOOL_HOME="$2"
        BIN_DIR="$TOOL_HOME/bin"
        shift 2
        ;;
      --skip-system-packages)
        SKIP_SYSTEM_PACKAGES=1
        shift
        ;;
      --skip-project-deps)
        SKIP_PROJECT_DEPS=1
        shift
        ;;
      --skip-static-tools)
        SKIP_STATIC_TOOLS=1
        shift
        ;;
      --verify-only)
        VERIFY_ONLY=1
        shift
        ;;
      -h | --help)
        usage
        exit 0
        ;;
      *)
        warn "Unknown option: $1"
        usage
        exit 2
        ;;
    esac
  done
}

have() {
  command -v "$1" >/dev/null 2>&1
}

need_sudo() {
  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

download() {
  local url="$1"
  local output="$2"
  curl -fL --retry 3 --connect-timeout 20 "$url" -o "$output"
}

detect_arch() {
  case "$(uname -m)" in
    x86_64 | amd64) echo "amd64" ;;
    aarch64 | arm64) echo "arm64" ;;
    *) echo "unsupported" ;;
  esac
}

append_path_hint() {
  local shell_rc="$HOME/.bashrc"
  [ -n "${ZSH_VERSION:-}" ] && shell_rc="$HOME/.zshrc"
  local path_line="export PATH=\"$BIN_DIR:$HOME/.local/bin:$HOME/.npm-global/bin:\$PATH\""
  if [ -f "$shell_rc" ] && ! grep -F "$BIN_DIR" "$shell_rc" >/dev/null 2>&1; then
    printf '\n%s\n' "$path_line" >> "$shell_rc"
  fi
}

install_system_packages() {
  if [ "$SKIP_SYSTEM_PACKAGES" = "1" ]; then
    log "Skipping system package installation"
    return
  fi
  log "Installing system packages"
  if have apt-get; then
    need_sudo apt-get update
    need_sudo apt-get install -y curl unzip tar gzip git ca-certificates openjdk-17-jre python3 python3-venv python3-pip
  elif have dnf; then
    need_sudo dnf install -y curl unzip tar gzip git ca-certificates java-17-openjdk python3 python3-pip
  elif have yum; then
    need_sudo yum install -y curl unzip tar gzip git ca-certificates java-17-openjdk python3 python3-pip
  elif have pacman; then
    need_sudo pacman -Sy --noconfirm curl unzip tar gzip git ca-certificates jre-openjdk python python-pip
  elif have zypper; then
    need_sudo zypper --non-interactive install curl unzip tar gzip git ca-certificates java-17-openjdk python3 python3-pip
  else
    warn "No supported Linux package manager found. Please install curl, unzip, tar, git, Java 17+, Python 3.10+ manually."
  fi
}

node_major() {
  if have node; then
    node -p "Number(process.versions.node.split('.')[0])" 2>/dev/null || echo 0
  else
    echo 0
  fi
}

install_node_24() {
  if [ "$(node_major)" -ge 24 ] && have npm; then
    log "Node.js $(node -v) is already available"
    return
  fi

  log "Installing Node.js 24 with nvm"
  export NVM_DIR="$HOME/.nvm"
  if [ ! -s "$NVM_DIR/nvm.sh" ]; then
    download "https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh" "$TMP_DIR/nvm-install.sh"
    bash "$TMP_DIR/nvm-install.sh"
  fi
  # shellcheck disable=SC1091
  . "$NVM_DIR/nvm.sh"
  nvm install 24
  nvm use 24
  nvm alias default 24
}

install_project_dependencies() {
  if [ "$SKIP_PROJECT_DEPS" = "1" ]; then
    log "Skipping project npm/Python dependencies"
    return
  fi
  log "Installing project npm and Python dependencies"
  cd "$ROOT_DIR"
  npm install
  if [ ! -d ".venv" ]; then
    python3 -m venv .venv
  fi
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  if [ ! -f "config.json" ] && [ -f "config.example.json" ]; then
    cp config.example.json config.json
  fi
}

install_pipx() {
  if have pipx; then
    return
  fi
  log "Installing pipx"
  python3 -m pip install --user --break-system-packages pipx 2>/dev/null || python3 -m pip install --user pipx
  export PATH="$HOME/.local/bin:$PATH"
}

pipx_install_or_upgrade() {
  local package="$1"
  if pipx list 2>/dev/null | grep -E "package ${package} " >/dev/null 2>&1; then
    pipx upgrade "$package" || pipx install --force "$package"
  else
    pipx install "$package"
  fi
}

install_python_tools() {
  log "Installing Python based tools"
  install_pipx
  pipx ensurepath >/dev/null 2>&1 || true
  export PATH="$HOME/.local/bin:$PATH"
  pipx_install_or_upgrade semgrep
  pipx_install_or_upgrade ruff
  pipx_install_or_upgrade bandit
}

install_npm_tools() {
  log "Installing npm based tools"
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    npm config set prefix "$HOME/.npm-global" >/dev/null
    mkdir -p "$HOME/.npm-global/bin"
    export PATH="$HOME/.npm-global/bin:$PATH"
  fi
  npm install -g eslint openapi-diff
}

install_gitleaks() {
  have gitleaks && return
  log "Installing gitleaks"
  local arch asset
  arch="$(detect_arch)"
  [ "$arch" = "amd64" ] && asset="gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" || asset="gitleaks_${GITLEAKS_VERSION}_linux_arm64.tar.gz"
  download "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/${asset}" "$TMP_DIR/gitleaks.tar.gz"
  tar -xzf "$TMP_DIR/gitleaks.tar.gz" -C "$TMP_DIR"
  install -m 0755 "$TMP_DIR/gitleaks" "$BIN_DIR/gitleaks"
}

install_trivy() {
  have trivy && return
  log "Installing trivy"
  local arch asset
  arch="$(detect_arch)"
  [ "$arch" = "amd64" ] && asset="trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" || asset="trivy_${TRIVY_VERSION}_Linux-ARM64.tar.gz"
  download "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/${asset}" "$TMP_DIR/trivy.tar.gz"
  tar -xzf "$TMP_DIR/trivy.tar.gz" -C "$TMP_DIR"
  install -m 0755 "$TMP_DIR/trivy" "$BIN_DIR/trivy"
}

install_osv_scanner() {
  have osv-scanner && return
  log "Installing osv-scanner"
  local arch asset
  arch="$(detect_arch)"
  [ "$arch" = "amd64" ] && asset="osv-scanner_linux_amd64" || asset="osv-scanner_linux_arm64"
  download "https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/${asset}" "$BIN_DIR/osv-scanner"
  chmod +x "$BIN_DIR/osv-scanner"
}

install_kics() {
  have kics && return
  log "Installing kics"
  local arch asset
  arch="$(detect_arch)"
  [ "$arch" = "amd64" ] && asset="kics_${KICS_VERSION}_linux_x64.tar.gz" || asset="kics_${KICS_VERSION}_linux_arm64.tar.gz"
  download "https://github.com/Checkmarx/kics/releases/download/v${KICS_VERSION}/${asset}" "$TMP_DIR/kics.tar.gz"
  mkdir -p "$TOOL_HOME/kics"
  tar -xzf "$TMP_DIR/kics.tar.gz" -C "$TOOL_HOME/kics" --strip-components=0
  if [ -x "$TOOL_HOME/kics/kics" ]; then
    ln -sf "$TOOL_HOME/kics/kics" "$BIN_DIR/kics"
  else
    find "$TOOL_HOME/kics" -type f -name kics -perm -111 -exec ln -sf {} "$BIN_DIR/kics" \; -quit
  fi
}

install_pmd() {
  have pmd && return
  log "Installing PMD"
  local url
  url="https://github.com/pmd/pmd/releases/download/pmd_releases%2F${PMD_VERSION}/pmd-dist-${PMD_VERSION}-bin.zip"
  download "$url" "$TMP_DIR/pmd.zip"
  unzip -q "$TMP_DIR/pmd.zip" -d "$TOOL_HOME"
  ln -sf "$TOOL_HOME/pmd-bin-${PMD_VERSION}/bin/pmd" "$BIN_DIR/pmd"
}

install_checkstyle() {
  have checkstyle && return
  log "Installing Checkstyle"
  mkdir -p "$TOOL_HOME/checkstyle"
  download "https://github.com/checkstyle/checkstyle/releases/download/checkstyle-${CHECKSTYLE_VERSION}/checkstyle-${CHECKSTYLE_VERSION}-all.jar" "$TOOL_HOME/checkstyle/checkstyle.jar"
  cat > "$BIN_DIR/checkstyle" <<EOF
#!/usr/bin/env bash
exec java -jar "$TOOL_HOME/checkstyle/checkstyle.jar" "\$@"
EOF
  chmod +x "$BIN_DIR/checkstyle"
}

install_spotbugs() {
  have spotbugs && return
  log "Installing SpotBugs"
  download "https://github.com/spotbugs/spotbugs/releases/download/${SPOTBUGS_VERSION}/spotbugs-${SPOTBUGS_VERSION}.zip" "$TMP_DIR/spotbugs.zip"
  unzip -q "$TMP_DIR/spotbugs.zip" -d "$TOOL_HOME"
  ln -sf "$TOOL_HOME/spotbugs-${SPOTBUGS_VERSION}/bin/spotbugs" "$BIN_DIR/spotbugs"
}

install_dependency_check() {
  have dependency-check && return
  log "Installing OWASP Dependency-Check"
  download "https://github.com/dependency-check/DependencyCheck/releases/download/v${DEPENDENCY_CHECK_VERSION}/dependency-check-${DEPENDENCY_CHECK_VERSION}-release.zip" "$TMP_DIR/dependency-check.zip"
  unzip -q "$TMP_DIR/dependency-check.zip" -d "$TOOL_HOME"
  ln -sf "$TOOL_HOME/dependency-check/bin/dependency-check.sh" "$BIN_DIR/dependency-check"
}

install_static_tools() {
  if [ "$SKIP_STATIC_TOOLS" = "1" ]; then
    log "Skipping static toolchain installation"
    return
  fi
  log "Installing static toolchain into $TOOL_HOME"
  mkdir -p "$BIN_DIR" "$TMP_DIR"
  export PATH="$BIN_DIR:$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"
  install_python_tools
  install_npm_tools
  install_gitleaks || warn "gitleaks install failed"
  install_trivy || warn "trivy install failed"
  install_osv_scanner || warn "osv-scanner install failed"
  install_kics || warn "kics install failed"
  install_pmd || warn "PMD install failed"
  install_checkstyle || warn "Checkstyle install failed"
  install_spotbugs || warn "SpotBugs install failed"
  install_dependency_check || warn "Dependency-Check install failed"
  append_path_hint
}

verify_command() {
  local name="$1"
  shift
  if have "$name"; then
    printf '[OK] %-18s ' "$name"
    "$name" "$@" 2>&1 | head -n 1 || true
  else
    printf '[MISS] %s\n' "$name"
    return 1
  fi
}

verify_all() {
  log "Verifying tool availability"
  export PATH="$BIN_DIR:$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"
  local missing=0
  verify_command node --version || missing=1
  verify_command npm --version || missing=1
  verify_command python3 --version || missing=1
  verify_command java -version || missing=1
  verify_command semgrep --version || missing=1
  verify_command gitleaks version || missing=1
  verify_command ruff --version || missing=1
  verify_command bandit --version || missing=1
  verify_command eslint --version || missing=1
  verify_command pmd --version || missing=1
  verify_command checkstyle --version || missing=1
  verify_command spotbugs -version || missing=1
  verify_command dependency-check --version || missing=1
  verify_command osv-scanner --version || missing=1
  verify_command trivy --version || missing=1
  verify_command kics version || missing=1
  verify_command openapi-diff --version || missing=1
  if [ "$missing" -ne 0 ]; then
    warn "Some tools are still missing. Reopen your shell or add $BIN_DIR, $HOME/.local/bin and $HOME/.npm-global/bin to PATH."
    return 1
  fi
}

main() {
  parse_args "$@"
  mkdir -p "$TMP_DIR"
  trap 'rm -rf "$TMP_DIR"' EXIT
  if [ "$VERIFY_ONLY" = "1" ]; then
    verify_all
    return
  fi
  install_system_packages
  install_node_24
  export PATH="$BIN_DIR:$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"
  install_project_dependencies
  install_static_tools
  verify_all
  log "Install complete. Run: npm run build"
}

main "$@"
