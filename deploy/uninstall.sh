#!/usr/bin/env bash
#
# Remove dgxctl from this machine. Unprivileged, like the installer.
#
#   ./deploy/uninstall.sh            remove the program; KEEP your config, token and history
#   ./deploy/uninstall.sh --purge    remove those too (a completely fresh slate)
#   ./deploy/uninstall.sh --dry-run  show what would be removed, change nothing
#
# Stopping the service also stops the host processes dgxctl launched (they share its cgroup):
# dgxctl owns what it started. Containers it launched keep running, and anything you started
# outside dgxctl is untouched. Both are listed at the end.
#
set -euo pipefail

VENV="${DGXCTL_VENV:-$HOME/.local/share/dgxctl/venv}"
CONFIG_DIR="${DGXCTL_CONFIG_DIR:-$HOME/.config/dgxctl}"
STATE_DIR="${DGXCTL_STATE_DIR:-$HOME/.local/share/dgxctl}"
UNIT="$HOME/.config/systemd/user/dgxctl.service"
LINK="$HOME/.local/bin/dgxctl"
MARKER="# added by dgxctl"

PURGE=0
DRY=0
for arg in "$@"; do
  case "$arg" in
    --purge)   PURGE=1 ;;
    --dry-run) DRY=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[36m==>\033[0m %s\n' "$*"; }
did()  { if [ "$DRY" -eq 1 ]; then printf '    would %s\n' "$*"; else printf '    %s\n' "$*"; fi; }
run()  { if [ "$DRY" -eq 0 ]; then "$@" >/dev/null 2>&1 || true; fi; }

[ "$DRY" -eq 1 ] && say "Dry run — nothing will be changed."

say "Service"
if [ -f "$UNIT" ] || systemctl --user list-unit-files dgxctl.service >/dev/null 2>&1; then
  did "stop and disable dgxctl.service"
  run systemctl --user disable --now dgxctl.service
  if [ -f "$UNIT" ]; then
    did "remove $UNIT"
    run rm -f "$UNIT"
  fi
  run systemctl --user daemon-reload
else
  did "(no service installed)"
fi

say "NVIDIA Sync"
SYNC="$HOME/.config/NVIDIA/Sync/config/custom.json"
if [ -f "$SYNC" ] && grep -q '"DGX Control"' "$SYNC" 2>/dev/null; then
  did "remove the 'DGX Control' entry (other entries are preserved, file backed up)"
  if [ "$DRY" -eq 0 ] && [ -x "$VENV/bin/dgxctl" ]; then
    "$VENV/bin/dgxctl" sync unregister "DGX Control" >/dev/null 2>&1 || true
  fi
else
  did "(no dgxctl entry registered)"
fi

say "Command"
if [ -L "$LINK" ]; then
  TARGET="$(readlink "$LINK")"
  case "$TARGET" in
    "$VENV"/*|*/dgxctl/venv/bin/dgxctl|*/.cache/uv/builds*)
      did "remove $LINK -> $TARGET"
      run rm -f "$LINK" ;;
    *)
      did "LEAVING $LINK -> $TARGET (not ours)" ;;
  esac
elif [ -e "$LINK" ]; then
  did "LEAVING $LINK (a real file, not our symlink)"
else
  did "(no symlink)"
fi

for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile" "$HOME/.bash_profile"; do
  if [ -f "$rc" ] && grep -q "$MARKER" "$rc" 2>/dev/null; then
    did "remove the PATH line from $rc"
    if [ "$DRY" -eq 0 ]; then
      cp "$rc" "$rc.dgxctl-bak"
      grep -v "$MARKER" "$rc.dgxctl-bak" > "$rc"
    fi
  fi
done

say "Program"
if [ -d "$VENV" ]; then
  did "remove $VENV"
  run rm -rf "$VENV"
else
  did "(no virtualenv)"
fi

say "Data"
if [ "$PURGE" -eq 1 ]; then
  for d in "$CONFIG_DIR" "$STATE_DIR"; do
    if [ -e "$d" ]; then
      did "remove $d  (config, token, history, action log)"
      run rm -rf "$d"
    fi
  done
else
  did "KEEPING $CONFIG_DIR (config + token) — pass --purge to remove"
  did "KEEPING $STATE_DIR (history, action log, logs) — pass --purge to remove"
fi

echo
say "Left running (containers, and anything started outside dgxctl):"
if command -v docker >/dev/null 2>&1; then
  docker ps --filter label=dgxctl.entry --format '    container {{.Names}} ({{.Ports}})' 2>/dev/null || true
fi
if [ -f "$STATE_DIR/processes.json" ] && [ "$PURGE" -eq 0 ]; then
  python3 - "$STATE_DIR/processes.json" <<'PY' 2>/dev/null || true
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    data = {}
for name, rec in data.items():
    print(f"    process {name} (pid {rec.get('pid')}, port {rec.get('port')})")
PY
fi
echo
say "Done. dgxctl is removed."
