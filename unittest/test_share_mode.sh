#!/usr/bin/env bash
set -euo pipefail


base_port=$(jq -r '.info.base_port' ../config/config.json)
PORT=$((base_port+1))
USER=ted
PASS='ted'  # Replace with the actual password
MAX_CLIENTS=3  # Change this value for configuration and testing

# Configure port 1 to shared mode and set max-clients
echo "[INFO] Setting port 1 to shared mode and max-clients=$MAX_CLIENTS..."
console-cli config operation 1 --mode shared
console-cli config operation 1 --max-clients $MAX_CLIENTS
echo "[INFO] Configured port 1 to shared mode with max-clients=$MAX_CLIENTS."


# Start $MAX_CLIENTS SSH sessions in the background
echo "[INFO] Starting $MAX_CLIENTS SSH sessions as $USER on port $PORT..."
for ((i=1; i<=MAX_CLIENTS; i++)); do
    cmd="sshpass -p \"$PASS\" ssh -p $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $USER@localhost sleep 300"
    echo "[DEBUG] Starting SSH session $i with command:"
    echo "        $cmd"
    eval $cmd &
    pids[$i]=$!
done
echo "[INFO] All SSH sessions started."

# Wait a few seconds to ensure sessions are established
echo "[INFO] Waiting for sessions to establish..."
sleep 10

# Check sessions and verify number of USER sessions on line 1
echo "[INFO] Checking active sessions for $USER on line 1..."
session_output=$(console-cli show sessions)
echo "[DEBUG] console-cli show sessions output:"
echo "$session_output"
session_count=$(echo "$session_output" | awk -v user="$USER" '/- line 1 /,/- line [0-9]+ / { if ($0 ~ user) count++ } END { print count+0 }')
echo "[DEBUG] Found $session_count sessions for $USER on line 1."
if [[ "$session_count" -ne "$MAX_CLIENTS" ]]; then
    echo "[ERROR] Expected $MAX_CLIENTS sessions for $USER on line 1, found $session_count"
    exit 1
fi
echo "[INFO] Found $MAX_CLIENTS sessions for $USER on line 1."

# Try to open one more session than allowed (should fail or be rejected)
echo "[INFO] Attempting to open one more session than allowed (should fail or be rejected)..."
set +e
sshpass -p "$PASS" ssh -p $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $USER@localhost 'echo "Should not connect"'
rc=$?
set -e
echo "[DEBUG] Extra session attempt exit code: $rc"

# Cleanup: kill background SSH sessions
echo "[INFO] Cleaning up background SSH sessions..."
for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
done
echo "[INFO] Cleanup complete."