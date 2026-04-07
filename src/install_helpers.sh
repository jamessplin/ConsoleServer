#!/usr/bin/env bash
set -euo pipefail

# Installs symlinks or copies for seriald client and console CLI into /usr/local/bin
# Usage:
#   sudo ./tools/seriald/install_helpers.sh         # Install
#   sudo ./tools/seriald/install_helpers.sh --remove  # Uninstall/remove

SRC_ROOT="$(cd "$(dirname "$0")/../../" && pwd)"

CLIENT_SRC="$SRC_ROOT/tools/seriald/client.py"
CLI_SRC="$SRC_ROOT/tools/seriald/console_cli.py"
STATUS_SRC="$SRC_ROOT/tools/seriald/status.py"
DISPATCH_SRC="$SRC_ROOT/tools/seriald/console-ssh-dispatch.sh"
SETUP_SSH_DISPATCH_SRC="$SRC_ROOT/tools/seriald/setup_ssh_dispatch.py"
SERVER_SRC="$SRC_ROOT/tools/seriald/server.py"
CONFIG_SRC="$SRC_ROOT/tools/seriald/config.json"
SERVICE_SRC="$SRC_ROOT/tools/seriald/seriald.service"

CLIENT_DST="/usr/local/bin/seriald-client"
CLI_DST="/usr/local/bin/console-cli"
STATUS_DST="/usr/local/bin/seriald-status"
DISPATCH_DST="/usr/local/bin/console-ssh-dispatch.sh"
SETUP_SSH_DISPATCH_DST="/usr/local/bin/setup_ssh_dispatch.py"
SERVER_DST="/usr/local/bin/server.py"
CONFIG_DST="/etc/seriald/config.json"
SERVICE_DST="/etc/systemd/system/seriald.service"

install_file() {
  local src="$1" dst="$2"
  if [[ ! -f "$src" ]]; then
    echo "ERROR: missing $src" >&2
    exit 1
  fi
  # Prefer copy to avoid symlink traversal issues in ForceCommand
  install -m 0755 "$src" "$dst"
  echo "Installed: $dst"
}

remove_installed() {
  echo "Removing installed files..."

  if [[ -f "$SERVICE_DST" ]]; then
    echo "Stopping and disabling seriald service..."
    systemctl stop seriald.service || true
    systemctl disable seriald.service || true
    rm -f "$SERVICE_DST"
    echo "Removed service file: $SERVICE_DST"
    echo "Reloading systemd daemon..."
    systemctl daemon-reload
  else
    echo "Service file not found: $SERVICE_DST"
  fi

  rm -f "$CLIENT_DST" "$CLI_DST" "$STATUS_DST" "$DISPATCH_DST" "$SETUP_SSH_DISPATCH_DST" "$SERVER_DST" "$CONFIG_DST" "$SERVICE_DST"
  echo "Removed: $CLIENT_DST, $CLI_DST, $STATUS_DST, $DISPATCH_DST, $SETUP_SSH_DISPATCH_DST, $SERVER_DST, $CONFIG_DST, $SERVICE_DST"

  # Remove all SSH/systemd integration created by setup_ssh_dispatch.py
  echo "Removing SSH/systemd integration via setup_ssh_dispatch.py --remove-all ..."
  sudo tools/seriald/setup_ssh_dispatch.py --remove-all || true

  echo "Removal complete."
}

main() {
  if [[ $EUID -ne 0 ]]; then
    echo "Please run as root (sudo)." >&2
    exit 1
  fi

  if [[ "${1:-}" == "--remove" ]]; then
    remove_installed
    exit 0
  fi


  install_file "$CLIENT_SRC" "$CLIENT_DST"
  install_file "$CLI_SRC" "$CLI_DST"
  install_file "$STATUS_SRC" "$STATUS_DST"
  install_file "$DISPATCH_SRC" "$DISPATCH_DST"
  install_file "$SETUP_SSH_DISPATCH_SRC" "$SETUP_SSH_DISPATCH_DST"

  # Install server.py to /usr/local/bin using install_file for consistency
  install_file "$SERVER_SRC" "$SERVER_DST"

  # Install config.json to /etc/seriald
  install -D -m 0644 "$CONFIG_SRC" "$CONFIG_DST"
  echo "Installed: $CONFIG_DST"

  command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 1; }
  echo "Done. Verify paths: $CLIENT_DST, $CLI_DST, $STATUS_DST, $DISPATCH_DST, $SERVER_DST, $CONFIG_DST"

  # Set up SSH dispatch and secondary sshd before enabling seriald service
  echo "Setting up SSH dispatch and secondary sshd..."
  sudo /usr/local/bin/setup_ssh_dispatch.py -s 20001 -e 20024 \
    --address-family inet \
    --port22-dualstack \
    --max-ports-per-sshd 16 \
    --split-at-port 20012 \
    --enable-second-sshd \
    --second-sshd-config /etc/ssh/sshd_config_seriald2 \
    --second-sshd-service ssh-seriald2.service

  echo "Installing and enabling systemd service..."

  if [[ ! -f "$SERVICE_SRC" ]]; then
    echo "ERROR: missing $SERVICE_SRC" >&2
    exit 1
  fi

  install -D -m 0644 "$SERVICE_SRC" "$SERVICE_DST"
  echo "Copied service file to $SERVICE_DST"

  echo "Reloading systemd daemon..."
  systemctl daemon-reload

  echo "Enabling seriald service to start on boot..."
  systemctl enable seriald.service

  echo "Starting seriald service..."
  systemctl start seriald.service

  echo "Systemd service setup complete. Use 'systemctl status seriald.service' to check its status."
}

main "$@"
