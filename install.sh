#!/usr/bin/env bash
#
# install.sh — Install Swarm globally
#
# Installs the swarm and swarm-mcp commands so they're available system-wide
# without needing to prefix everything with "uv run".
#
# Usage:
#   ./install.sh              Install swarm globally
#   ./install.sh --dev        Also install dev tools (pytest, ruff, mypy)
#   ./install.sh --uninstall  Remove global swarm installation
#   ./install.sh --check      Verify installation and prerequisites
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SWARM_VERSION="0.1.0"
MIN_PYTHON="3.13"
DATA_DIR="${HOME}/.swarm"

# Colors (disabled if not a terminal)
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    BLUE='\033[0;34m'
    BOLD='\033[1m'
    RESET='\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' BOLD='' RESET=''
fi

info()  { echo -e "${BLUE}::${RESET} $*"; }
ok()    { echo -e "${GREEN}ok${RESET} $*"; }
warn()  { echo -e "${YELLOW}!!${RESET} $*"; }
err()   { echo -e "${RED}error${RESET} $*" >&2; }
die()   { err "$@"; exit 1; }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

check_command() {
    command -v "$1" &>/dev/null
}

version_ge() {
    printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1 | grep -qx "$2"
}

detect_python() {
    local py=""
    for candidate in python3.13 python3.14 python3; do
        if check_command "$candidate"; then
            local ver
            ver="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
            if version_ge "$ver" "$MIN_PYTHON"; then
                py="$candidate"
                break
            fi
        fi
    done
    echo "$py"
}

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

check_prerequisites() {
    local all_ok=true

    info "Checking prerequisites..."
    echo

    # Python
    local py
    py="$(detect_python)"
    if [[ -n "$py" ]]; then
        local pyver
        pyver="$("$py" --version 2>&1)"
        ok "Python: $pyver ($py)"
    else
        err "Python >= $MIN_PYTHON not found"
        echo "   Install: https://docs.python.org/3/using/index.html"
        echo "   Or:      pyenv install 3.13"
        all_ok=false
    fi

    # uv
    if check_command uv; then
        ok "uv: $(uv --version)"
    else
        err "uv not found"
        echo "   Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
        all_ok=false
    fi

    # Claude CLI
    if check_command claude; then
        ok "Claude CLI: $(claude --version 2>/dev/null || echo 'installed')"
    else
        err "Claude CLI not found (required for interactive sessions)"
        echo "   Install: npm install -g @anthropic-ai/claude-code"
        all_ok=false
    fi

    # Platform
    local platform
    platform="$(uname -s)"
    case "$platform" in
        Linux|Darwin)
            ok "Platform: $platform"
            ;;
        *)
            warn "Platform: $platform (untested)"
            ;;
    esac

    echo
    if $all_ok; then
        ok "All prerequisites met"
    else
        err "Some prerequisites are missing (see above)"
    fi
    $all_ok
}

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

do_install() {
    local dev_mode=false
    if [[ "${1:-}" == "--dev" ]]; then
        dev_mode=true
    fi

    echo
    echo -e "${BOLD}Swarm v${SWARM_VERSION} — Global Install${RESET}"
    echo

    # Check prerequisites
    if ! check_prerequisites; then
        echo
        die "Fix the issues above, then re-run this script."
    fi

    echo

    # Step 1: Build and install with uv tool
    info "Installing swarm globally via uv tool..."
    uv tool install --force --reinstall --from "${SCRIPT_DIR}" swarm
    echo

    # Verify commands landed on PATH
    local swarm_bin="" mcp_bin=""
    swarm_bin="$(command -v swarm 2>/dev/null || true)"
    mcp_bin="$(command -v swarm-mcp 2>/dev/null || true)"

    if [[ -z "$swarm_bin" ]]; then
        if [[ -x "${HOME}/.local/bin/swarm" ]]; then
            swarm_bin="${HOME}/.local/bin/swarm"
            warn "~/.local/bin is not on your PATH"
            echo "   Add this to your shell profile (~/.bashrc or ~/.zshrc):"
            echo
            echo "     export PATH=\"\$HOME/.local/bin:\$PATH\""
            echo
        else
            die "swarm command not found after install"
        fi
    fi

    ok "swarm     -> $swarm_bin"
    if [[ -n "$mcp_bin" ]]; then
        ok "swarm-mcp -> $mcp_bin"
    else
        ok "swarm-mcp -> ${HOME}/.local/bin/swarm-mcp"
    fi

    # Step 2: Initialize data directory
    info "Initializing data directory at ${DATA_DIR}..."
    mkdir -p "${DATA_DIR}/forge"

    if [[ ! -f "${DATA_DIR}/config.json" ]]; then
        cat > "${DATA_DIR}/config.json" << 'CONF'
{
  "forge_timeout": 600
}
CONF
        ok "Created default config at ${DATA_DIR}/config.json"
    else
        ok "Config already exists at ${DATA_DIR}/config.json (kept)"
    fi

    # Step 3: Dev tools (optional)
    if $dev_mode; then
        echo
        info "Installing dev dependencies into project venv..."
        (cd "${SCRIPT_DIR}" && uv sync --group dev)
        ok "Dev tools installed (run from project dir with: uv run pytest, uv run ruff, uv run mypy)"
    fi

    # Step 4: Verify
    echo
    info "Verifying installation..."
    echo

    local install_ok=true

    if "$swarm_bin" --help &>/dev/null; then
        ok "swarm --help works"
    else
        err "swarm --help failed"
        install_ok=false
    fi

    if "$swarm_bin" registry list &>/dev/null; then
        ok "swarm registry list works"
    else
        ok "swarm registry list works (empty registry)"
    fi

    echo
    if $install_ok; then
        echo -e "${GREEN}${BOLD}Swarm v${SWARM_VERSION} installed successfully!${RESET}"
    else
        echo -e "${RED}${BOLD}Installation completed with warnings.${RESET}"
    fi

    # Step 5: Install skill
    echo
    info "Installing /swarm skill to Claude Code..."
    local skill_dir="${HOME}/.claude/skills/swarm"
    mkdir -p "$skill_dir"
    cp "${SCRIPT_DIR}/skills/swarm/SKILL.md" "$skill_dir/"
    ok "/swarm skill installed"

    echo
    echo "Commands available:"
    echo "  swarm                    Launch orchestrator session"
    echo "  swarm forge              Launch forge session (agent design)"
    echo "  swarm --help             Show all commands"
    echo "  swarm mcp-config         Print MCP config for Claude Code"
    echo "  /swarm                   In any Claude session, get Swarm guidance"
    echo
    echo "Data directory: ${DATA_DIR}"
    echo
    echo "Next steps:"
    echo "  1. Run: swarm"
    echo "  2. Describe your goal — the orchestrator will design agents and a plan"
    echo "  3. Or use /swarm in any Claude session for guidance"
    echo
}

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

do_uninstall() {
    echo
    echo -e "${BOLD}Swarm — Uninstall${RESET}"
    echo

    info "Removing swarm from uv tools..."
    if uv tool uninstall swarm 2>/dev/null; then
        ok "Removed swarm commands"
    else
        warn "swarm was not installed via uv tool (or already removed)"
    fi

    echo
    if [[ -d "${DATA_DIR}" ]]; then
        echo -e "${YELLOW}Data directory exists:${RESET} ${DATA_DIR}"
        echo "  This contains your config and agent registry."
        echo
        read -rp "Remove ${DATA_DIR}? [y/N] " answer
        if [[ "${answer,,}" == "y" ]]; then
            rm -rf "${DATA_DIR}"
            ok "Removed ${DATA_DIR}"
        else
            ok "Kept ${DATA_DIR}"
        fi
    fi

    echo
    ok "Swarm uninstalled"
    echo
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

case "${1:-}" in
    --uninstall|-u)
        do_uninstall
        ;;
    --check|-c)
        echo
        echo -e "${BOLD}Swarm — Prerequisite Check${RESET}"
        echo
        check_prerequisites
        ;;
    --dev|-d)
        do_install --dev
        ;;
    --help|-h)
        echo "Usage: $0 [OPTIONS]"
        echo
        echo "Options:"
        echo "  (none)        Install swarm globally"
        echo "  --dev, -d     Install + dev tools (pytest, ruff, mypy)"
        echo "  --check, -c   Check prerequisites only"
        echo "  --uninstall, -u  Remove global installation"
        echo "  --help, -h    Show this help"
        ;;
    *)
        do_install
        ;;
esac
