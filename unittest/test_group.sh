#!/bin/bash

# Exit on any error, and print commands
set -euo pipefail

CONSOLE_CLI="console-cli"
TEST_GROUPS=()

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

# --- Helper Functions ---
cleanup() {
    echov "--- Cleaning up ---"
    if [ ${#TEST_GROUPS[@]} -eq 0 ]; then
        echov "No test groups to clean up."
        return
    fi

    echov "Deleting ${#TEST_GROUPS[@]} test groups..."
    for group in "${TEST_GROUPS[@]}"; do
        echov "Deleting group: $group"
        $CONSOLE_CLI config group delete "$group" || echov "Failed to delete $group, it may have already been removed."
    done

    echov "--- Verifying cleanup ---"
    $CONSOLE_CLI show running-config --groups

    echov "Cleanup complete."
}

# Ensure cleanup runs on script exit
trap cleanup EXIT

# --- Run Tests ---
echov "--- Running CLI tests for group limits ---"

# 1. Get the group limit from the running configuration
echov "[Step 1] Checking 'no_of_group' limit from running config..."
GROUP_LIMIT=$($CONSOLE_CLI show running-config | grep '"no_of_group"' | awk -F': ' '{print $2}' | tr -d ',')
echov "Group limit is set to: $GROUP_LIMIT"

if ! [[ "$GROUP_LIMIT" =~ ^[0-9]+$ ]]; then
    echov "Error: Could not parse group limit. Is jq installed and the server running?"
    exit 1
fi

# 2. Get the current number of groups
echov "[Step 2] Checking initial number of groups..."
INITIAL_GROUP_COUNT=$($CONSOLE_CLI show running-config --groups | grep -c '"port_list":')
echov "Initial group count: $INITIAL_GROUP_COUNT"
$CONSOLE_CLI show running-config --groups

# 3. Add groups up to the limit + 1, verifying the last one fails
GROUPS_TO_ADD=$((GROUP_LIMIT - INITIAL_GROUP_COUNT))
echov "[Step 3] Limit is $GROUP_LIMIT, $INITIAL_GROUP_COUNT groups exist. Will attempt to add $((GROUPS_TO_ADD + 1)) groups..."

if [ $GROUPS_TO_ADD -lt 0 ]; then
    echov "Warning: Number of groups ($INITIAL_GROUP_COUNT) already exceeds the limit ($GROUP_LIMIT)."
    GROUPS_TO_ADD=0
fi

LIMIT_REACHED_SUCCESS=false
for ((i=1; i<=GROUPS_TO_ADD + 1; i++)); do
    GROUPNAME="testgroup_cli_$i"

    if [ $i -le $GROUPS_TO_ADD ]; then
        # These should succeed
        echov "Adding group: $GROUPNAME (should succeed)"
        $CONSOLE_CLI config group add "$GROUPNAME"
        TEST_GROUPS+=("$GROUPNAME")
    else
        # This is the "limit + 1" attempt and should fail
        echov "Attempting to add group: $GROUPNAME (should fail)"
        set +e # Disable exit on error for this command
        OUTPUT=$($CONSOLE_CLI config group add "$GROUPNAME" 2>&1)
        EXIT_CODE=$?
        set -e # Re-enable exit on error

        if [ $EXIT_CODE -ne 0 ] && [[ "$OUTPUT" == *"Failed "* ]]; then
            echov "OK: Server correctly rejected adding group beyond the limit."
            LIMIT_REACHED_SUCCESS=true
        else
            echov "FAIL: Server did not reject group addition as expected."
            echov "Exit code: $EXIT_CODE"
            echov "Output: $OUTPUT"
            exit 1
        fi
    fi
done

if [ "$LIMIT_REACHED_SUCCESS" = false ]; then
    echov "FAIL: The limit check was not triggered."
    exit 1
fi

echov "Final group list before cleanup:"
echov "$($CONSOLE_CLI show running-config --groups)"

echov "--- All tests passed successfully! ---"
echov "Cleanup will run automatically."
