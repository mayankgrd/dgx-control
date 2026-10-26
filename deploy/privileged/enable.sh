#!/usr/bin/env bash
#
# Enable dgxctl's optional privileged helper (spec R17). Run it once, deliberately:
#
#   sudo ./deploy/privileged/enable.sh                      install for the user who ran sudo
#   sudo ./deploy/privileged/enable.sh --remove             undo it completely
#        ./deploy/privileged/enable.sh --print-sudoers USER show the rule, change nothing
#
# It grants one user permission to run, as root, exactly these two commands and no others:
#
#   /usr/local/libexec/dgxctl/dgxctl-helper check
#   /usr/local/libexec/dgxctl/dgxctl-helper sockets
#
# The helper is read-only: it lists which process owns each listening socket, which an
# unprivileged `ss` cannot see for other users' processes.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR=/usr/local/libexec/dgxctl
HELPER="$DEST_DIR/dgxctl-helper"
SUDOERS=/etc/sudoers.d/dgxctl

valid_user() {
  # Anything else could inject a second rule into the sudoers file.
  [[ "$1" =~ ^[a-z_][a-z0-9_.-]{0,31}$ ]] && [ "$1" != "root" ]
}

sudoers_rule() {
  local user="$1"
  valid_user "$user" || { echo "refusing user name: '$user'" >&2; exit 1; }
  printf '# Installed by dgx-control deploy/privileged/enable.sh. Remove with --remove.\n'
  printf '# Read-only: lets %s list socket owners. Each argv is exact; sudo refuses any other.\n' "$user"
  printf '# Logging is suppressed for ALLOWED runs of this one command only, since dgxctl polls it\n'
  printf '# every few seconds; denied attempts are still logged.\n'
  printf 'Defaults!%s !log_allowed, !pam_session\n' "$HELPER"
  printf '%s ALL=(root) NOPASSWD: %s check, %s sockets\n' "$user" "$HELPER" "$HELPER"
}

if [ "${1:-}" = "--print-sudoers" ]; then
  [ -n "${2:-}" ] || { echo "usage: $0 --print-sudoers USER" >&2; exit 2; }
  sudoers_rule "$2"
  exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "This must run as root: sudo $0 ${1:-}" >&2
  exit 1
fi

if [ "${1:-}" = "--remove" ]; then
  rm -f "$SUDOERS" "$HELPER"
  rmdir "$DEST_DIR" 2>/dev/null || true
  echo "Removed. dgxctl is back to unprivileged visibility."
  echo "Restart it to notice: systemctl --user restart dgxctl"
  exit 0
fi

USER_NAME="${SUDO_USER:-}"
if [ -z "$USER_NAME" ] || [ "$USER_NAME" = "root" ]; then
  echo "Run this with sudo from the account that runs dgxctl, not as root directly." >&2
  exit 1
fi

install -d -o root -g root -m 0755 "$DEST_DIR"
install -o root -g root -m 0755 "$HERE/dgxctl-helper" "$HELPER"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
sudoers_rule "$USER_NAME" > "$tmp"
# A malformed file in /etc/sudoers.d can break sudo for the whole machine: validate first.
visudo -cf "$tmp" >/dev/null
install -o root -g root -m 0440 "$tmp" "$SUDOERS"

echo "Enabled for $USER_NAME."
echo "  helper:  $HELPER  (root-owned, read-only)"
echo "  sudoers: $SUDOERS"
echo "Restart dgxctl to pick it up: systemctl --user restart dgxctl"
