#!/bin/bash

# Exit on any error, and print commands
set -euo pipefail

CONSOLE_CLI="console-cli"
TEST_USERS=()

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
    if [ ${#TEST_USERS[@]} -eq 0 ]; then
        echov "No test users to clean up."
        return
    fi

    echov "Deleting ${#TEST_USERS[@]} test users..."
    for user in "${TEST_USERS[@]}"; do
        echov "Deleting user: $user"
        $CONSOLE_CLI config user delete "$user" || echov "Failed to delete $user, it may have already been removed."
    done

    echov "--- Verifying cleanup ---"
    $CONSOLE_CLI show running-config --users --json

    echov "Cleanup complete."
}

# Ensure cleanup runs on script exit
trap cleanup EXIT

# --- Run Tests ---
echov "--- Running CLI tests for user limits ---"

# 1. Get the user limit from the running configuration
echov "[Step 1] Checking 'no_of_user' limit from running config..."
USER_LIMIT=$($CONSOLE_CLI show running-config --json | grep '"no_of_user"' | awk -F': ' '{print $2}' | tr -d ',')
echov "User limit is set to: $USER_LIMIT"

if ! [[ "$USER_LIMIT" =~ ^[0-9]+$ ]]; then
    echov "Error: Could not parse user limit. Is jq installed and the server running?"
    exit 1
fi

# 2. Get the current number of users
echov "[Step 2] Checking initial number of users..."
INITIAL_USER_COUNT=$($CONSOLE_CLI show running-config --users --json | grep -c '"groups":')
echov "Initial user count: $INITIAL_USER_COUNT"
$CONSOLE_CLI show running-config --users --json

# 3. Add users up to the limit + 1, verifying the last one fails
USERS_TO_ADD=$((USER_LIMIT - INITIAL_USER_COUNT))
echov "[Step 3] Limit is $USER_LIMIT, $INITIAL_USER_COUNT users exist. Will attempt to add $((USERS_TO_ADD + 1)) users..."

if [ $USERS_TO_ADD -lt 0 ]; then
    echov "Warning: Number of users ($INITIAL_USER_COUNT) already exceeds the limit ($USER_LIMIT)."
    USERS_TO_ADD=0
fi

LIMIT_REACHED_SUCCESS=false
for ((i=1; i<=USERS_TO_ADD + 1; i++)); do
    USERNAME="testuser_cli_$i"

    if [ $i -le $USERS_TO_ADD ]; then
        # These should succeed
        echov "Adding user: $USERNAME (should succeed)"
        $CONSOLE_CLI config user add "$USERNAME" --password "password"
        TEST_USERS+=("$USERNAME")
    else
        # This is the "limit + 1" attempt and should fail
        echov "Attempting to add user: $USERNAME (should fail)"
        set +e # Disable exit on error for this command
        OUTPUT=$($CONSOLE_CLI config user add "$USERNAME" --password "password" 2>&1)
        EXIT_CODE=$?
        set -e # Re-enable exit on error

        if [ $EXIT_CODE -ne 0 ] && [[ "$OUTPUT" == *"Failed "* ]]; then
            echov "OK: Server correctly rejected adding user beyond the limit."
            LIMIT_REACHED_SUCCESS=true
        else
            echov "FAIL: Server did not reject user addition as expected."
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

echov "Final user list before cleanup:"
echov "$($CONSOLE_CLI show running-config --users --json)"

# 4. Cleanup is handled by the trap on EXIT
echov "--- All tests passed successfully! ---"
echov "Cleanup will run automatically."
