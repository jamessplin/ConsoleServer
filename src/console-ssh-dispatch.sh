#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${SSH_CONNECTION:-}" ]]; then
  echo "SSH_CONNECTION not set" >&2
  exit 2
fi

read -r _client_ip _client_port _server_ip server_port <<<"$SSH_CONNECTION"

base=20000

if [[ "$server_port" == "22" ]]; then
  if [[ "${DRY_RUN:-}" == "1" ]]; then
    echo "dispatch: cli"
    exit 0
  fi
  exec /usr/local/bin/console-cli
elif [[ "$server_port" =~ ^[0-9]+$ ]] && (( server_port >= 20001 && server_port <= 20024 )); then
  line=$(( server_port - base ))
  if [[ "${DRY_RUN:-}" == "1" ]]; then
    echo "dispatch: seriald-client --line ${line}"
    exit 0
  fi
  export SSH_CLIENT_IP="$_client_ip"
  export SSH_CLIENT_PORT="$_client_port"
  exec /usr/bin/python3 /usr/local/bin/seriald-client --line "$line"
else
  echo "Unsupported target port: ${server_port}" >&2
  exit 1
fi
