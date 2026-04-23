#!/bin/bash

# --- Script Configuration ---
VERBOSE=false
if [[ "${1-}" == "-v" ]]; then
    VERBOSE=true
fi

# Redirect stdout/stderr to /dev/null if not in verbose mode
# But save the original stdout/stderr to file descriptors 3 and 4
if [ "$VERBOSE" = false ]; then
    exec 3>&1 4>&2
    exec &>/dev/null
fi

# Helper to print to original stdout only when not verbose
echov() {
    if [ "$VERBOSE" = false ]; then
        echo "$@" >&3
    else
        echo "$@"
    fi
}

set -e

PORT=10


# Step 0: Validate --line all selector
echov "[STEP 0] Validating --line all selector..."
ALL_LINES_CONFIG=$(console-cli show running-config --line all)
if [ "$VERBOSE" = true ]; then
    echo "$ALL_LINES_CONFIG"
fi
if ! echo "$ALL_LINES_CONFIG" | grep -q '"lines"'; then
    echo "[ERROR] --line all did not return a lines object" >&2
    exit 1
fi

# Step 0b: Validate --json output format
echov "[STEP 0b] Validating --json output format..."
ALL_LINES_JSON=$(console-cli show running-config --line all --json)
if [ "$VERBOSE" = true ]; then
    echo "$ALL_LINES_JSON"
fi
if ! echo "$ALL_LINES_JSON" | grep -q '"lines"'; then
    echo "[ERROR] --json output did not return expected JSON content" >&2
    exit 1
fi


# Step 1: Show and save current config
echov "[STEP 1] Saving current config for line $PORT..."
ORIG_CONFIG=$(console-cli show running-config --line $PORT)
if [ "$VERBOSE" = true ]; then
  echo "$ORIG_CONFIG"
fi
echo "$ORIG_CONFIG" > orig_line${PORT}_config.json


# Extract original values using grep/awk
get_val() {
    local key="$1"
    grep "\"$key\"" orig_line${PORT}_config.json | awk -F: '{gsub(/[",]/, "", $2); print $2}' | xargs
}

# Helper to pick a new value different from the original
pick_new() {
    local key="$1"
    local orig="$2"
    case "$key" in
        baudrate)
            for v in 115200 57600 38400 9600; do [ "$v" != "$orig" ] && echo "$v" && return; done
            ;;
        databits)
            for v in 7 8 6 5; do [ "$v" != "$orig" ] && echo "$v" && return; done
            ;;
        parity)
            for v in even odd none; do [ "$v" != "$orig" ] && echo "$v" && return; done
            ;;
        stopbits)
            for v in 2 1; do [ "$v" != "$orig" ] && echo "$v" && return; done
            ;;
        flowcontrol)
            for v in rtscts xonxoff none; do [ "$v" != "$orig" ] && echo "$v" && return; done
            ;;
    esac
}


# Step 2: Change all configurable parameters to different values
echov "[STEP 2] Changing all configurable parameters..."
ORIG_BAUD=$(get_val baudrate)
ORIG_DATABITS=$(get_val databits)
ORIG_PARITY=$(get_val parity)
ORIG_STOPBITS=$(get_val stopbits)
ORIG_FLOW=$(get_val flowcontrol)

NEW_BAUD=$(pick_new baudrate "$ORIG_BAUD")
NEW_DATABITS=$(pick_new databits "$ORIG_DATABITS")
NEW_PARITY=$(pick_new parity "$ORIG_PARITY")
NEW_STOPBITS=$(pick_new stopbits "$ORIG_STOPBITS")
NEW_FLOW=$(pick_new flowcontrol "$ORIG_FLOW")

console-cli config port $PORT \
    --baudrate "$NEW_BAUD" \
    --databits "$NEW_DATABITS" \
    --parity "$NEW_PARITY" \
    --stopbits "$NEW_STOPBITS" \
    --flowcontrol "$NEW_FLOW"


# Step 3: Verify changes
echov "[STEP 3] Verifying changed config..."
NEW_CONFIG=$(console-cli show running-config --line $PORT)
if [ "$VERBOSE" = true ]; then
  echo "$NEW_CONFIG"
fi
echo "$NEW_CONFIG" > new_line${PORT}_config.json
check_val() {
    local key="$1" expected="$2"
    actual=$(grep '"'$key'"' new_line${PORT}_config.json | awk -F: '{gsub(/[",]/, "", $2); print $2}' | xargs)
    if [ "$actual" != "$expected" ]; then
        echo "[ERROR] $key: expected $expected, got $actual" >&2
        exit 1
    else
        echo "[OK] $key set to $actual"
    fi
}
check_val baudrate "$NEW_BAUD"
check_val databits "$NEW_DATABITS"
check_val parity "$NEW_PARITY"
check_val stopbits "$NEW_STOPBITS"
check_val flowcontrol "$NEW_FLOW"

# Step 4: Revert to original config
echov "[STEP 4] Reverting to original config..."
console-cli config port $PORT \
    --baudrate "$(get_val baudrate)" \
    --databits "$(get_val databits)" \
    --parity "$(get_val parity)" \
    --stopbits "$(get_val stopbits)" \
    --flowcontrol "$(get_val flowcontrol)"

# Step 5: Verify revert
echov "[STEP 5] Verifying reverted config..."
REVERTED_CONFIG=$(console-cli show running-config --line $PORT)
if [ "$VERBOSE" = true ]; then
  echo "$REVERTED_CONFIG"
fi
echo "$REVERTED_CONFIG" > reverted_line${PORT}_config.json
check_val_revert() {
    local key="$1" expected="$2"
    actual=$(grep '"'$key'"' reverted_line${PORT}_config.json | awk -F: '{gsub(/[",]/, "", $2); print $2}' | xargs)
    if [ "$actual" != "$expected" ]; then
        echo "[ERROR] (revert) $key: expected $expected, got $actual" >&2
        exit 1
    else
        echo "[OK] (revert) $key set to $actual"
    fi
}
check_val_revert baudrate "$ORIG_BAUD"
check_val_revert databits "$ORIG_DATABITS"
check_val_revert parity "$ORIG_PARITY"
check_val_revert stopbits "$ORIG_STOPBITS"
check_val_revert flowcontrol "$ORIG_FLOW"

echov "Test complete."

# Cleanup temporary files
rm -f orig_line${PORT}_config.json new_line${PORT}_config.json reverted_line${PORT}_config.json