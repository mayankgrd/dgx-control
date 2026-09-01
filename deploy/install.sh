#!/usr/bin/env bash
#
# Install dgxctl on this machine, then hand over to `dgxctl onboard`.
#
# Deliberately unprivileged: there is no `sudo` anywhere in this script, because on many DGX
# systems sudo is password-protected and nothing here needs root.
#
#   ./deploy/install.sh                 install, then ask how it should be set up
#   ./deploy/install.sh --no-onboard    install only (for scripted/fleet use)
#   ./deploy/install.sh --yes           install and onboard with safe defaults, no questions
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${DGXCTL_VENV:-$HOME/.local/share/dgxctl/venv}"
MIN_PY_MINOR=11

ONBOARD=1
ONBOARD_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --no-onboard) ONBOARD=0 ;;
    --yes|-y)     ONBOARD_ARGS+=("--yes") ;;
    *)            ONBOARD_ARGS+=("$arg") ;;
  esac
done

say()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mnote:\033[0m %s\n' "$*"; }
die()  { printf '\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# --- prerequisites -----------------------------------------------------------

command -v python3 >/dev/null || die "python3 not found. Install Python ${MIN_PY_MINOR}+ first."
PY_MINOR="$(python3 -c 'import sys; print(sys.version_info.minor)')"
PY_MAJOR="$(python3 -c 'import sys; print(sys.version_info.major)')"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt "$MIN_PY_MINOR" ]; }; then
  die "Python 3.${MIN_PY_MINOR}+ required, found $(python3 -V 2>&1)."
fi

case "$(uname -s)" in
  Linux) ;;
  *) warn "dgxctl reads /proc and expects Linux; $(uname -s) will degrade heavily." ;;
esac

# --- install -----------------------------------------------------------------

say "Creating a virtualenv at $VENV"
mkdir -p "$(dirname "$VENV")"
if command -v uv >/dev/null 2>&1; then
  uv venv "$VENV" --quiet
  PIP=(uv pip install --python "$VENV/bin/python" --quiet)
else
  python3 -m venv "$VENV"
  PIP=("$VENV/bin/pip" install --quiet --upgrade)
fi

say "Installing dgxctl"
"${PIP[@]}" "$REPO"

if command -v npm >/dev/null 2>&1; then
  say "Building the web UI"
  (cd "$REPO/web" && npm ci --silent && npm run build --silent)
  PKG_DIR="$("$VENV/bin/python" -c 'import dgxctl, os; print(os.path.dirname(dgxctl.__file__))')"
  rm -rf "$PKG_DIR/_web"
  cp -r "$REPO/web/dist" "$PKG_DIR/_web"
else
  warn "npm not found — skipping the UI build. The API still works at /api/*."
  warn "Install Node 20+ and re-run this script to get the dashboard."
fi

# The onboarding step installs the systemd unit from the package, so ship it inside.
PKG_DIR="$("$VENV/bin/python" -c 'import dgxctl, os; print(os.path.dirname(dgxctl.__file__))')"
mkdir -p "$PKG_DIR/_data"
cp "$REPO/deploy/dgxctl.service" "$PKG_DIR/_data/dgxctl.service"

export PATH="$VENV/bin:$PATH"

if [ "$ONBOARD" -eq 1 ]; then
  say "Setting up"
  echo
  "$VENV/bin/dgxctl" onboard "${ONBOARD_ARGS[@]}"
else
  # Even when the questions are skipped, `dgxctl` should be runnable by name.
  mkdir -p "$HOME/.local/bin"
  if [ -e "$HOME/.local/bin/dgxctl" ] && [ ! -L "$HOME/.local/bin/dgxctl" ]; then
    warn "$HOME/.local/bin/dgxctl exists and is not a symlink; leaving it alone."
  else
    ln -sfn "$VENV/bin/dgxctl" "$HOME/.local/bin/dgxctl"
    say "Linked $HOME/.local/bin/dgxctl"
  fi
  cat <<EOM

Installed. Finish setup with:

  dgxctl onboard

If that is not found, your shell does not have ~/.local/bin on PATH yet — open a new
shell, or run it as $VENV/bin/dgxctl onboard

EOM
fi
