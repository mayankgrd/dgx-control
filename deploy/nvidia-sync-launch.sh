#!/usr/bin/env bash
# Launch script for the NVIDIA Sync "Add Custom" dialog.
#
# The dialog runs this with "Launch in Terminal" unchecked, i.e. in the background with no
# TTY, so this script must not block, must not require input, and must exit promptly.
# It is also run every time the tool is opened, so it must be IDEMPOTENT: if the service
# is already listening, do nothing and succeed.
set -euo pipefail

PORT="${DGXCTL_PORT:-8770}"
VENV="${DGXCTL_VENV:-$HOME/.local/share/dgxctl/venv}"
BIN="$VENV/bin/dgxctl"

listening() {
  if command -v ss >/dev/null 2>&1; then
    ss -tln 2>/dev/null | grep -qE "[:.]${PORT}[[:space:]]"
  else
    (exec 3<>"/dev/tcp/127.0.0.1/${PORT}") 2>/dev/null
  fi
}

if listening; then
  echo "dgxctl is already listening on port ${PORT}"
  exit 0
fi

if [ ! -x "$BIN" ]; then
  echo "dgxctl is not installed at $BIN — run deploy/install.sh first" >&2
  exit 1
fi

# Prefer the user service so the process survives this script exiting and is managed
# consistently; fall back to a detached process where systemd --user is unavailable.
if command -v systemctl >/dev/null 2>&1 && systemctl --user list-unit-files dgxctl.service >/dev/null 2>&1; then
  systemctl --user start dgxctl.service
else
  nohup "$BIN" serve >"$HOME/.local/share/dgxctl/dgxctl.log" 2>&1 &
  disown || true
fi

for _ in $(seq 1 30); do
  if listening; then
    echo "dgxctl is listening on port ${PORT}"
    exit 0
  fi
  sleep 0.5
done

echo "dgxctl did not come up on port ${PORT} within 15s" >&2
exit 1
