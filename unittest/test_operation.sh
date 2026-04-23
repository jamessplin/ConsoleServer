#!/bin/bash

# --- Script Configuration ---
VERBOSE=false
if [[ "${1-}" == "-v" ]]; then
  VERBOSE=true
fi

if [ "$VERBOSE" = false ]; then
  exec 3>&1 4>&2
  exec &>/dev/null
fi

echov() {
  if [ "$VERBOSE" = false ]; then
    echo "$@" >&3
  else
    echo "$@"
  fi
}

set -e

PORT=1

# Step 1: Show and save current operation config
echov "[STEP 1] Saving current operation config for line $PORT..."
ORIG_CONFIG=$(console-cli show running-config --line $PORT --json)
if [ "$VERBOSE" = true ]; then
    echo "$ORIG_CONFIG"
fi

# Extract original values using grep/awk directly from the variable
get_val() {
    local key="$1"
    echo "$ORIG_CONFIG" | grep "\"$key\"" | awk -F: '{gsub(/[",]/, "", $2); print $2}' | xargs
}

# Helper to pick a new value different from the original
pick_new() {
    local key="$1"
    local orig="$2"
    case "$key" in
        mode)
            [ "$orig" = "shared" ] && echo "exclusive" || echo "shared"
            ;;
        max_clients)
            for v in 1 2 3 4; do [ "$v" != "$orig" ] && echo "$v" && return; done
            ;;
        idle_timeout)
            for v in 0 60 600 1200; do [ "$v" != "$orig" ] && echo "$v" && return; done
            ;;
        label)
            [ "$orig" = "TestLabel" ] && echo "AnotherLabel" || echo "TestLabel"
            ;;
    esac
}

# Step 2: Change all configurable parameters to different values
echov "[STEP 2] Changing all operation parameters..."
ORIG_MODE=$(get_val mode)
ORIG_MAX_CLIENTS=$(get_val max_clients)
ORIG_IDLE_TIMEOUT=$(get_val idle_timeout)
ORIG_LABEL=$(get_val label)

NEW_MODE=$(pick_new mode "$ORIG_MODE")
NEW_MAX_CLIENTS=$(pick_new max_clients "$ORIG_MAX_CLIENTS")
NEW_IDLE_TIMEOUT=$(pick_new idle_timeout "$ORIG_IDLE_TIMEOUT")
NEW_LABEL=$(pick_new label "$ORIG_LABEL")

console-cli config operation $PORT \
    --mode "$NEW_MODE" \
    --max-clients "$NEW_MAX_CLIENTS" \
    --idle-timeout "$NEW_IDLE_TIMEOUT" \
    --label "$NEW_LABEL"

# Step 3: Verify changes
echov "[STEP 3] Verifying changed operation config..."
NEW_CONFIG=$(console-cli show running-config --line $PORT --json)
if [ "$VERBOSE" = true ]; then
    echo "$NEW_CONFIG"
fi
check_val() {
    local key="$1" expected="$2"
    actual=$(echo "$NEW_CONFIG" | grep "\"$key\"" | awk -F: '{gsub(/[",]/, "", $2); print $2}' | xargs)
    if [ "$actual" != "$expected" ]; then
        echov "[FAIL] $key: expected $expected, got $actual"
        exit 1
    else
        echov "[OK] $key = $actual"
    fi
}
check_val mode "$NEW_MODE"
check_val max_clients "$NEW_MAX_CLIENTS"
check_val idle_timeout "$NEW_IDLE_TIMEOUT"
check_val label "$NEW_LABEL"

# Step 4: Revert to original config
echov "[STEP 4] Reverting to original operation config..."
console-cli config operation $PORT \
    --mode "$ORIG_MODE" \
    --max-clients "$ORIG_MAX_CLIENTS" \
    --idle-timeout "$ORIG_IDLE_TIMEOUT" \
    --label "$ORIG_LABEL"

# Step 5: Verify revert
echov "[STEP 5] Verifying reverted operation config..."
REVERTED_CONFIG=$(console-cli show running-config --line $PORT --json)
if [ "$VERBOSE" = true ]; then
    echo "$REVERTED_CONFIG"
fi
check_val_revert() {
    local key="$1" expected="$2"
    actual=$(echo "$REVERTED_CONFIG" | grep "\"$key\"" | awk -F: '{gsub(/[",]/, "", $2); print $2}' | xargs)
    if [ "$actual" != "$expected" ]; then
        echov "[FAIL] (revert) $key: expected $expected, got $actual"
        exit 1
    else
        echov "[OK] (revert) $key = $actual"
    fi
}
check_val_revert mode "$ORIG_MODE"
check_val_revert max_clients "$ORIG_MAX_CLIENTS"
check_val_revert idle_timeout "$ORIG_IDLE_TIMEOUT"
check_val_revert label "$ORIG_LABEL"

echov "--- All tests passed successfully! ---"