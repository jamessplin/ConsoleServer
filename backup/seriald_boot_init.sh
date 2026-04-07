#!/bin/bash
# seriald_boot_init.sh
# Boot-up initialization script for the seriald server.

usage() {
    echo "Usage: ./tools/seriald/seriald_boot_init.sh [options]"
    echo ""
    echo "This script starts and stops the main seriald server."
    echo "The server itself is responsible for managing all ser2net subprocesses."
    echo "Run this script from the root directory of the repository."
    echo ""
    echo "Options:"
    echo "  -k, --kill     Find and kill the seriald server process."
    echo "  -h, --help     Show this help message and exit."
    echo ""
}

# Show usage if -h or --help is passed
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    usage
    exit 0
fi

# Kill the seriald server process if -k or --kill is passed
if [[ "$1" == "-k" || "$1" == "--kill" ]]; then
    echo "[INFO] Attempting to kill the seriald server..."
    # The server may be running under sudo, so try that as well.
    # The server is designed to trap SIGTERM and kill its children.
    if pgrep -f "server.py --config config.json" > /dev/null; then
        sudo pkill -f "server.py --config config.json"
        echo "[INFO] The seriald server has been terminated."
    else
        echo "[INFO] The seriald server was not found running."
    fi

    # As a safety measure, clean up any orphaned ser2net processes
    if pgrep -f "ser2net" > /dev/null; then
        echo "[INFO] Cleaning up any orphaned ser2net processes..."
        sudo pkill -f "ser2net"
    fi
    exit 0
fi

set -e

# Check for ser2net dependency
if ! command -v ser2net >/dev/null 2>&1; then
    echo "[ERROR] ser2net is not installed. Please install it first."
    echo "  sudo apt-get update && sudo apt-get install ser2net"
    exit 1
fi

# Navigate to the script's directory to ensure paths are correct
cd "$(dirname "$0")"

echo "[INFO] Starting seriald server..."
echo "[INFO] The server will now read config.json and manage ser2net processes."
# The server needs to run with sudo to be able to launch ser2net instances,
# which require root to access /dev/tty* devices.
sudo python3 server.py --config config.json

echo "[INFO] seriald server has been started."

