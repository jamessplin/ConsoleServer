#!/bin/bash
# Test one or more Exar XR17V35x serial ports using physical TX/RX loopbacks.
#
# Defaults can be overridden with environment variables or command-line options:
#   PORT=/dev/ttyXR0 DURATION=10 ./xr_one_port_loopback_test.sh
#   ./xr_one_port_loopback_test.sh -p 0,1,2 -d 10
#   ./xr_one_port_loopback_test.sh -p 0-7 -j -d 30
#   ./xr_one_port_loopback_test.sh -p all -d endless
#   ./xr_one_port_loopback_test.sh -p 0-7 -c -j -d 30

set -u
set -o pipefail
LC_ALL=C

PORT="${PORT:-/dev/ttyXR0}"
BAUD="${BAUD:-115200}"
DURATION="${DURATION:-10}"       # Seconds; use "endless" or 0 for no limit.
WRITE_BYTES="${WRITE_BYTES:-16}"
WRITE_DELAY_MS="${WRITE_DELAY_MS:-10}"
RX_DELAY_MS="${RX_DELAY_MS:-0}"
RX_GRACE_SECONDS="${RX_GRACE_SECONDS:-2}"
BASIC_TIMEOUT_SECONDS="${BASIC_TIMEOUT_SECONDS:-5}"
LOG_FILE="${LOG_FILE:-}"
HARDWARE_FLOW="${HARDWARE_FLOW:-0}"
XR_LOOPBACK_WORKER="${XR_LOOPBACK_WORKER:-0}"
XR_PARENT_MANAGES_CONSOLE="${XR_PARENT_MANAGES_CONSOLE:-0}"
RUN_IN_PARALLEL=0
PORT_SPECS=()
SELECTED_PORTS=()
MULTI_INTERRUPTED=0

ORIGINAL_STTY=""
ORIGINAL_CONSOLE_LEVEL=""
TMP_DIR=""
READER_PID=""
WATCHDOG_PID=""

usage()
{
    cat <<'EOF'
Usage: xr_one_port_loopback_test.sh [options]

Options:
  -p PORTS      Port, comma-separated ports, numeric range, or "all"
                Examples: /dev/ttyXR0 | 0,1,2 | 0-7 | all
                Repeat -p to combine selections.
  -b BAUD       Baud rate (default: 115200)
  -d DURATION   Per-port test seconds, "endless", or 0 (default: 10)
  -w BYTES      Bytes per linux-serial-test write (default: 16)
  -a MS         Delay between writes in milliseconds (default: 10)
  -c            Verify RTS/CTS wiring and enable hardware flow control
  -l MS         Delay reads in milliseconds to exercise backpressure
  -j            Test selected ports in parallel instead of sequentially
  -h            Show this help

Every selected connector must have TX connected to RX. The optional -c test
also requires RTS connected to CTS. Without -c, hardware and software flow
control are disabled. Endless multi-port tests automatically run in parallel.
Press Ctrl-C once to stop an endless test and grade its results.

Examples:
  xr_one_port_loopback_test.sh -p /dev/ttyXR0 -d 10
  xr_one_port_loopback_test.sh -p 0,1,2 -d 10
  xr_one_port_loopback_test.sh -p 0-7 -j -d 30
  xr_one_port_loopback_test.sh -p 0-15 -p 16-23 -j -d 30
  xr_one_port_loopback_test.sh -p all -d endless
  xr_one_port_loopback_test.sh -p 0 -c -d 10
  xr_one_port_loopback_test.sh -p 0-23 -c -j -d 30
  xr_one_port_loopback_test.sh -p 0 -c -l 250 -w 64 -a 10 -d 10
EOF
}

fail_setup()
{
    echo "SETUP ERROR: $*" >&2
    exit 2
}

cleanup()
{
    if [[ -n "$READER_PID" ]]; then
        kill "$READER_PID" 2>/dev/null || true
        wait "$READER_PID" 2>/dev/null || true
    fi

    if [[ -n "$WATCHDOG_PID" ]]; then
        kill "$WATCHDOG_PID" 2>/dev/null || true
        wait "$WATCHDOG_PID" 2>/dev/null || true
    fi

    if [[ -n "$ORIGINAL_STTY" && -c "$PORT" ]]; then
        stty -F "$PORT" "$ORIGINAL_STTY" 2>/dev/null || true
    fi

    if [[ -n "$ORIGINAL_CONSOLE_LEVEL" ]]; then
        dmesg -n "$ORIGINAL_CONSOLE_LEVEL" 2>/dev/null || true
    fi

    if [[ -n "$TMP_DIR" && "$TMP_DIR" == /tmp/xr-loopback.* ]]; then
        rm -f -- "$TMP_DIR/basic-rx" 2>/dev/null || true
        rmdir -- "$TMP_DIR" 2>/dev/null || true
    fi
}

trap cleanup EXIT

add_selected_port()
{
    local candidate="$1"
    local existing

    for existing in "${SELECTED_PORTS[@]}"; do
        [[ "$existing" == "$candidate" ]] && return 0
    done

    SELECTED_PORTS+=("$candidate")
}

expand_port_spec()
{
    local specification="$1"
    local token
    local start_index
    local end_index
    local port_index
    local found_count
    local -a tokens

    IFS=',' read -r -a tokens <<<"$specification"
    [[ "${#tokens[@]}" -gt 0 ]] || fail_setup "Empty port selection."

    for token in "${tokens[@]}"; do
        if [[ "$token" == "all" ]]; then
            found_count=0
            for ((port_index = 0; port_index <= 255; port_index++)); do
                if [[ -c "/dev/ttyXR${port_index}" ]]; then
                    add_selected_port "/dev/ttyXR${port_index}"
                    found_count=$((found_count + 1))
                fi
            done
            [[ "$found_count" -gt 0 ]] || fail_setup "No /dev/ttyXR* devices were found."
        elif [[ "$token" =~ ^(/dev/ttyXR|ttyXR)?([0-9]+)-([0-9]+)$ ]]; then
            start_index=$((10#${BASH_REMATCH[2]}))
            end_index=$((10#${BASH_REMATCH[3]}))
            [[ "$start_index" -le "$end_index" ]] || \
                fail_setup "Invalid descending port range: $token"
            [[ $((end_index - start_index)) -le 255 ]] || \
                fail_setup "Port range is too large: $token"

            for ((port_index = start_index; port_index <= end_index; port_index++)); do
                add_selected_port "/dev/ttyXR${port_index}"
            done
        elif [[ "$token" =~ ^(/dev/ttyXR|ttyXR)?([0-9]+)$ ]]; then
            port_index=$((10#${BASH_REMATCH[2]}))
            add_selected_port "/dev/ttyXR${port_index}"
        else
            fail_setup "Invalid port selection: $token"
        fi
    done
}

worker_log_path()
{
    local selected_port="$1"
    local selected_name="${selected_port##*/}"

    if [[ -n "$LOG_FILE" ]]; then
        printf '%s.%s' "$LOG_FILE" "$selected_name"
    else
        printf '%s' ""
    fi
}

run_port_worker()
{
    local selected_port="$1"
    local selected_log

    selected_log="$(worker_log_path "$selected_port")"

    XR_LOOPBACK_WORKER=1 \
    XR_PARENT_MANAGES_CONSOLE=1 \
    PORT="$selected_port" \
    LOG_FILE="$selected_log" \
    HARDWARE_FLOW="$HARDWARE_FLOW" \
    RX_DELAY_MS="$RX_DELAY_MS" \
    RX_GRACE_SECONDS="$RX_GRACE_SECONDS" \
    BASIC_TIMEOUT_SECONDS="$BASIC_TIMEOUT_SECONDS" \
        "$BASH" "${BASH_SOURCE[0]}" \
            -p "$selected_port" \
            -b "$BAUD" \
            -d "$DURATION" \
            -w "$WRITE_BYTES" \
            -a "$WRITE_DELAY_MS"
}

run_multiple_ports()
{
    local selected_port
    local worker_pid
    local worker_status
    local index
    local pass_count=0
    local fail_count=0
    local mode="sequential"
    local flow_description="no flow control"
    local -a worker_pids=()
    local -a worker_statuses=()

    if [[ "$DURATION" == "endless" || "$DURATION" =~ ^0+$ ]]; then
        if [[ "$RUN_IN_PARALLEL" -eq 0 ]]; then
            echo "Endless multi-port testing requires parallel execution; enabling -j."
            RUN_IN_PARALLEL=1
        fi
    fi

    if [[ -r /proc/sys/kernel/printk ]]; then
        read -r ORIGINAL_CONSOLE_LEVEL _ < /proc/sys/kernel/printk || true
    fi
    dmesg -n 1 2>/dev/null || true

    [[ "$RUN_IN_PARALLEL" -eq 0 ]] || mode="parallel"
    [[ "$HARDWARE_FLOW" -eq 0 ]] || flow_description="RTS/CTS hardware flow control"
    echo "XR multi-port loopback test"
    echo "  Ports:         ${SELECTED_PORTS[*]}"
    echo "  Mode:          $mode"
    echo "  Configuration: ${BAUD} baud, 8N1, $flow_description"
    echo "  Duration:      $DURATION per port"
    echo "  Stress rate:   $WRITE_BYTES bytes every ${WRITE_DELAY_MS} ms"
    [[ "$RX_DELAY_MS" -eq 0 ]] || echo "  Read delay:    ${RX_DELAY_MS} ms"
    echo

    if [[ "$RUN_IN_PARALLEL" -eq 0 ]]; then
        for selected_port in "${SELECTED_PORTS[@]}"; do
            echo "----- Starting $selected_port -----"
            run_port_worker "$selected_port"
            worker_status=$?
            worker_statuses+=("$worker_status")
            echo "----- Finished $selected_port: status=$worker_status -----"
            echo
        done
    else
        trap 'MULTI_INTERRUPTED=1' INT

        for selected_port in "${SELECTED_PORTS[@]}"; do
            echo "----- Starting $selected_port in parallel -----"
            run_port_worker "$selected_port" &
            worker_pids+=("$!")
        done

        for worker_pid in "${worker_pids[@]}"; do
            while true; do
                wait "$worker_pid"
                worker_status=$?

                if [[ "$worker_status" -eq 130 ]] && kill -0 "$worker_pid" 2>/dev/null; then
                    continue
                fi

                worker_statuses+=("$worker_status")
                break
            done
        done

        trap - INT
        [[ "$MULTI_INTERRUPTED" -eq 0 ]] || echo "User requested the parallel tests to stop."
    fi

    echo
    echo "========== PER-PORT RESULTS =========="
    for ((index = 0; index < ${#SELECTED_PORTS[@]}; index++)); do
        selected_port="${SELECTED_PORTS[index]}"
        worker_status="${worker_statuses[index]}"

        if [[ "$worker_status" -eq 0 ]]; then
            printf '  %-16s PASS\n' "$selected_port"
            pass_count=$((pass_count + 1))
        else
            printf '  %-16s FAIL (exit %s)\n' "$selected_port" "$worker_status"
            fail_count=$((fail_count + 1))
        fi
    done

    echo "  Passed: $pass_count"
    echo "  Failed: $fail_count"

    if [[ "$fail_count" -ne 0 ]]; then
        echo "OVERALL RESULT: FAIL"
        return 1
    fi

    echo "OVERALL RESULT: PASS"
    return 0
}

while getopts ":p:b:d:w:a:l:cjh" option; do
    case "$option" in
        p) PORT_SPECS+=("$OPTARG") ;;
        b) BAUD="$OPTARG" ;;
        d) DURATION="$OPTARG" ;;
        w) WRITE_BYTES="$OPTARG" ;;
        a) WRITE_DELAY_MS="$OPTARG" ;;
        l) RX_DELAY_MS="$OPTARG" ;;
        c) HARDWARE_FLOW=1 ;;
        j) RUN_IN_PARALLEL=1 ;;
        h) usage; exit 0 ;;
        :) fail_setup "Option -$OPTARG requires an argument." ;;
        \?) fail_setup "Unknown option: -$OPTARG" ;;
    esac
done

shift $((OPTIND - 1))
[[ $# -eq 0 ]] || fail_setup "Unexpected argument: $1"

for command_name in stty dd linux-serial-test tee grep tail sed mktemp; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail_setup "Required command not found: $command_name"
done

[[ "$HARDWARE_FLOW" == "0" || "$HARDWARE_FLOW" == "1" ]] || \
    fail_setup "HARDWARE_FLOW must be 0 or 1."

if [[ "$HARDWARE_FLOW" -eq 1 ]]; then
    command -v python3 >/dev/null 2>&1 || \
        fail_setup "The RTS/CTS signal test requires python3."
fi

[[ "$BAUD" =~ ^[0-9]+$ && "$BAUD" -gt 0 ]] || fail_setup "Invalid baud rate: $BAUD"
[[ "$WRITE_BYTES" =~ ^[0-9]+$ && "$WRITE_BYTES" -gt 0 ]] || fail_setup "Invalid write size: $WRITE_BYTES"
[[ "$WRITE_DELAY_MS" =~ ^[0-9]+$ ]] || fail_setup "Invalid write delay: $WRITE_DELAY_MS"
[[ "$RX_DELAY_MS" =~ ^[0-9]+$ ]] || fail_setup "Invalid read delay: $RX_DELAY_MS"
[[ "$RX_GRACE_SECONDS" =~ ^[0-9]+$ ]] || fail_setup "Invalid RX grace period."
[[ "$BASIC_TIMEOUT_SECONDS" =~ ^[0-9]+$ && "$BASIC_TIMEOUT_SECONDS" -gt 0 ]] || \
    fail_setup "Invalid basic-test timeout."

if [[ "$DURATION" != "endless" && ! "$DURATION" =~ ^[0-9]+$ ]]; then
    fail_setup "Duration must be a positive number, 0, or endless."
fi

if [[ "${#PORT_SPECS[@]}" -eq 0 ]]; then
    PORT_SPECS+=("${PORTS:-$PORT}")
fi

for port_specification in "${PORT_SPECS[@]}"; do
    expand_port_spec "$port_specification"
done

[[ "${#SELECTED_PORTS[@]}" -gt 0 ]] || fail_setup "No ports were selected."

for selected_port in "${SELECTED_PORTS[@]}"; do
    [[ -c "$selected_port" ]] || fail_setup "$selected_port is not a character device."
done

if [[ "$XR_LOOPBACK_WORKER" -eq 0 && "${#SELECTED_PORTS[@]}" -gt 1 ]]; then
    run_multiple_ports
    exit $?
fi

[[ "${#SELECTED_PORTS[@]}" -eq 1 ]] || fail_setup "Worker mode accepts exactly one port."
PORT="${SELECTED_PORTS[0]}"

ORIGINAL_STTY="$(stty -F "$PORT" -g 2>/dev/null)" || \
    fail_setup "Cannot read settings from $PORT. Is it already in use?"

if [[ "$XR_PARENT_MANAGES_CONSOLE" -eq 0 ]]; then
    if [[ -r /proc/sys/kernel/printk ]]; then
        read -r ORIGINAL_CONSOLE_LEVEL _ < /proc/sys/kernel/printk || true
    fi

    # Prevent driver printk messages from corrupting the terminal display. They
    # remain available through dmesg. Failure is non-fatal for non-root users.
    dmesg -n 1 2>/dev/null || true
fi

if [[ -z "$LOG_FILE" ]]; then
    port_name="${PORT##*/}"
    LOG_FILE="/tmp/${port_name}_loopback_$(date +%Y%m%d_%H%M%S).log"
fi

total_steps=3
flow_description="no flow control"
if [[ "$HARDWARE_FLOW" -eq 1 ]]; then
    total_steps=4
    flow_description="RTS/CTS hardware flow control"
fi

echo "XR one-port loopback test"
echo "  Port:          $PORT"
echo "  Configuration: ${BAUD} baud, 8N1, $flow_description"
echo "  Duration:      $DURATION"
echo "  Stress rate:   $WRITE_BYTES bytes every ${WRITE_DELAY_MS} ms"
[[ "$RX_DELAY_MS" -eq 0 ]] || echo "  Read delay:    ${RX_DELAY_MS} ms"
echo "  Log:           $LOG_FILE"
echo

echo "[1/$total_steps] Configuring $PORT ..."
if ! stty -F "$PORT" "$BAUD" cs8 -cstopb -parenb clocal \
        -crtscts -ixon -ixoff raw -echo min 1 time 0; then
    fail_setup "Failed to configure $PORT."
fi

settings="$(stty -F "$PORT" -a 2>&1)" || fail_setup "Cannot verify $PORT settings."
echo "$settings"

if ! grep -q "speed $BAUD baud" <<<"$settings" ||
   ! grep -Eq '(^|[[:space:]])cs8([[:space:]]|$)' <<<"$settings" ||
   ! grep -Eq '(^|[[:space:]])-parenb([[:space:]]|$)' <<<"$settings" ||
   ! grep -Eq '(^|[[:space:]])-cstopb([[:space:]]|$)' <<<"$settings" ||
   ! grep -Eq '(^|[[:space:]])-crtscts([[:space:]]|$)' <<<"$settings" ||
   ! grep -Eq '(^|[[:space:]])-ixon([[:space:]]|$)' <<<"$settings" ||
   ! grep -Eq '(^|[[:space:]])-ixoff([[:space:]]|$)' <<<"$settings"; then
    echo "FAIL: termios settings do not match the requested configuration."
    exit 1
fi
echo "PASS: port configuration verified."
echo

echo "[2/$total_steps] Running basic TX/RX loopback ..."
TMP_DIR="$(mktemp -d /tmp/xr-loopback.XXXXXX)" || fail_setup "Cannot create temporary directory."
BASIC_RX="$TMP_DIR/basic-rx"
payload="XR_LOOPBACK_${$}_$(date +%s)"
payload_length=${#payload}

dd if="$PORT" of="$BASIC_RX" bs=1 count="$payload_length" 2>/dev/null &
READER_PID=$!
sleep 1

(
    sleep "$BASIC_TIMEOUT_SECONDS"
    kill -TERM "$READER_PID" 2>/dev/null || true
) &
WATCHDOG_PID=$!

if ! printf '%s' "$payload" > "$PORT"; then
    echo "FAIL: basic test could not write to $PORT."
    exit 1
fi

wait "$READER_PID"
reader_status=$?
READER_PID=""
kill "$WATCHDOG_PID" 2>/dev/null || true
wait "$WATCHDOG_PID" 2>/dev/null || true
WATCHDOG_PID=""

received=""
[[ -f "$BASIC_RX" ]] && received="$(<"$BASIC_RX")"

if [[ "$reader_status" -ne 0 || "$received" != "$payload" ]]; then
    echo "FAIL: basic loopback mismatch or timeout."
    echo "  Sent:     '$payload' (${#payload} bytes)"
    echo "  Received: '$received' (${#received} bytes)"
    exit 1
fi

echo "PASS: basic loopback returned all $payload_length bytes correctly."
echo

if [[ "$HARDWARE_FLOW" -eq 1 ]]; then
    echo "[3/$total_steps] Testing physical RTS/CTS signal loopback ..."

    if ! python3 - "$PORT" <<'PY'
import array
import fcntl
import os
import sys
import termios
import time

device = sys.argv[1]
fd = -1
original = None
failures = 0


def get_modem_bits():
    bits = array.array("i", [0])
    fcntl.ioctl(fd, termios.TIOCMGET, bits, True)
    return bits[0]


def set_modem_bits(value):
    bits = array.array("i", [value])
    fcntl.ioctl(fd, termios.TIOCMSET, bits)


try:
    fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    original = get_modem_bits()

    for asserted in (True, False, True, False):
        current = get_modem_bits()

        if asserted:
            requested = current | termios.TIOCM_RTS
        else:
            requested = current & ~termios.TIOCM_RTS

        set_modem_bits(requested)
        time.sleep(0.2)

        observed = get_modem_bits()
        rts = bool(observed & termios.TIOCM_RTS)
        cts = bool(observed & termios.TIOCM_CTS)
        passed = rts == asserted and cts == asserted

        print(
            f"requested RTS={int(asserted)} "
            f"observed RTS={int(rts)} "
            f"observed CTS={int(cts)} "
            f"{'PASS' if passed else 'FAIL'}"
        )

        if not passed:
            failures += 1

except (OSError, AttributeError) as error:
    print(f"RTS/CTS signal test error: {error}", file=sys.stderr)
    failures += 1

finally:
    if fd >= 0:
        if original is not None:
            try:
                set_modem_bits(original)
            except OSError as error:
                print(f"Cannot restore modem-control bits: {error}", file=sys.stderr)
                failures += 1
        os.close(fd)

print("RTS/CTS RESULT:", "PASS" if failures == 0 else "FAIL")
sys.exit(0 if failures == 0 else 1)
PY
    then
        echo "FAIL: RTS/CTS did not follow the requested signal transitions."
        exit 1
    fi

    if ! stty -F "$PORT" crtscts; then
        echo "FAIL: cannot enable RTS/CTS hardware flow control on $PORT."
        exit 1
    fi

    flow_settings="$(stty -F "$PORT" -a 2>&1)" || \
        fail_setup "Cannot verify RTS/CTS settings for $PORT."

    if ! grep -Eq '(^|[[:space:]])crtscts([[:space:]]|$)' <<<"$flow_settings"; then
        echo "FAIL: RTS/CTS hardware flow control was not enabled."
        exit 1
    fi

    echo "PASS: RTS/CTS transitions verified and hardware flow control enabled."
    echo
fi

echo "[$total_steps/$total_steps] Running linux-serial-test ..."
test_command=(
    linux-serial-test
    -p "$PORT"
    -b "$BAUD"
    -s
    -e
    -S
    -w "$WRITE_BYTES"
    -a "$WRITE_DELAY_MS"
)

if [[ "$HARDWARE_FLOW" -eq 1 ]]; then
    test_command+=( -c )
fi

if [[ "$RX_DELAY_MS" -gt 0 ]]; then
    test_command+=( -l "$RX_DELAY_MS" )
fi

if [[ "$DURATION" != "endless" && "$DURATION" -ne 0 ]]; then
    effective_rx_grace=$((10#$RX_GRACE_SECONDS))

    if [[ "$HARDWARE_FLOW" -eq 1 && "$RX_DELAY_MS" -gt 0 && "$effective_rx_grace" -lt 10 ]]; then
        effective_rx_grace=10
        echo "Allowing ${effective_rx_grace}s for delayed receive data to drain."
    fi

    receive_duration=$((10#$DURATION + effective_rx_grace))
    test_command+=( -o "$DURATION" -i "$receive_duration" )
else
    echo "Endless mode selected. Press Ctrl-C once to stop and grade the test."
fi

echo "Command: ${test_command[*]}"
echo

# The shell and tee ignore Ctrl-C, while linux-serial-test installs its own
# SIGINT handler and exits cleanly. This lets endless mode reach result parsing.
trap '' INT
"${test_command[@]}" 2>&1 | tee "$LOG_FILE"
test_status=${PIPESTATUS[0]}
trap - INT

stats_line="$(grep 'count for this session:' "$LOG_FILE" | tail -n 1)"
rx_count=""
tx_count=""
rx_errors=""

if [[ "$stats_line" =~ rx=([0-9]+),[[:space:]]tx=([0-9]+),[[:space:]]rx[[:space:]]err=([0-9]+) ]]; then
    rx_count="${BASH_REMATCH[1]}"
    tx_count="${BASH_REMATCH[2]}"
    rx_errors="${BASH_REMATCH[3]}"
fi

echo
echo "Result summary"
echo "  linux-serial-test status: $test_status"
echo "  RX bytes:                ${rx_count:-unknown}"
echo "  TX bytes:                ${tx_count:-unknown}"
echo "  RX errors:               ${rx_errors:-unknown}"

test_failed=0

if [[ -z "$rx_count" || -z "$tx_count" || -z "$rx_errors" ]]; then
    echo "  Reason: final statistics could not be parsed."
    test_failed=1
elif [[ "$rx_count" -eq 0 || "$tx_count" -eq 0 ]]; then
    echo "  Reason: no loopback traffic completed."
    test_failed=1
elif [[ "$rx_errors" -ne 0 ]]; then
    echo "  Reason: received data-pattern errors were detected."
    test_failed=1
elif [[ "$rx_count" -ne "$tx_count" ]]; then
    echo "  Reason: RX and TX byte counts do not match."
    test_failed=1
fi

if grep -q 'No data received' "$LOG_FILE"; then
    echo "  Reason: the test detected an RX progress timeout."
    test_failed=1
fi

if grep -q 'No data transmitted' "$LOG_FILE"; then
    if [[ "$HARDWARE_FLOW" -eq 1 && "$RX_DELAY_MS" -gt 0 ]]; then
        echo "  Note: TX paused during intentional RTS/CTS receive backpressure."
    else
        echo "  Reason: the test detected a TX progress timeout."
        test_failed=1
    fi
fi

if [[ "$test_status" -ne 0 ]]; then
    echo "  Reason: linux-serial-test returned a nonzero status."
    test_failed=1
fi

if grep -q 'Error setting RS-232 mode: Inappropriate ioctl for device' "$LOG_FILE"; then
    echo "  Note: xr17v35x does not implement the RS-485-mode ioctl used by the test tool."
fi

if [[ "$test_failed" -ne 0 ]]; then
    echo "FINAL RESULT: FAIL"
    exit 1
fi

echo "FINAL RESULT: PASS"
exit 0
