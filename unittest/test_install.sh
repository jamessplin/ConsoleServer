#!/usr/bin/env bash
set -euo pipefail


# Get base_port from config.json
base_port=$(jq -r '.info.base_port' ../config/config.json)

# 1. Check listening ports (base_port+1 to base_port+24)
for ((port=base_port+1; port<=base_port+24; port++)); do
    if ! ss -lnt | grep -q ":$port "; then
        echo "Port $port is NOT listening"
        exit 1
    fi
done
echo "All expected ports are listening."

# 2. Check if ser2net is running for all expected configs
for ((i=1; i<=24; i++)); do
    cfg="cs${i}.yaml"
    cmd="pgrep -af 'ser2net.*$cfg'"
    #echo "Checking: $cmd"
    if ! pgrep -af "ser2net.*$cfg" > /dev/null; then
        echo "ser2net is NOT running for config $cfg"
        exit 1
    fi
done
echo "ser2net is running for all expected configs."

# 3. Check base port in console-ssh-dispatch.sh
dispatch_base=$(grep '^base=' /usr/local/bin/console-ssh-dispatch.sh | head -n1 | cut -d= -f2)
if [[ "$dispatch_base" != "$base_port" ]]; then
    echo "Base port in console-ssh-dispatch.sh does not match config.json, found: $dispatch_base, expected: $base_port"
    exit 1
fi
echo "Base port in console-ssh-dispatch.sh matches config.json: $dispatch_base"

echo "All checks passed."