#!/usr/bin/env bash
# ConsoleServer Debian package VM verification script
# ser2net is launched with -n and must remain in the foreground.
set -Eeuo pipefail

SERVICE="seriald.service"
DIST_SER2NET_SERVICE="ser2net.service"
PACKAGE="console-server"
BUILD_PACKAGE=1
KEEP_INSTALLED=0
DEB=""
LOG_DIR="/tmp/console-server-vm-test"
RESULT_LOG="${LOG_DIR}/result.log"
PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

usage() {
    cat <<'USAGE'
Usage: ./test_vm_package.sh [options]
  --deb PATH          Test an existing .deb
  --skip-build        Do not run dpkg-buildpackage
  --keep-installed    Leave console-server installed after the test
  -h, --help          Show help
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --deb) DEB="$(readlink -f "$2")"; shift 2 ;;
        --skip-build) BUILD_PACKAGE=0; shift ;;
        --keep-installed) KEEP_INSTALLED=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown option: $1"; usage; exit 2 ;;
    esac
done

mkdir -p "$LOG_DIR"
: > "$RESULT_LOG"
log(){ printf '%s\n' "$*" | tee -a "$RESULT_LOG"; }
section(){ log ""; log "================================================================"; log "$*"; log "================================================================"; }
pass(){ PASS_COUNT=$((PASS_COUNT+1)); log "PASS: $*"; }
warn(){ WARN_COUNT=$((WARN_COUNT+1)); log "WARN: $*"; }
fail(){ FAIL_COUNT=$((FAIL_COUNT+1)); log "FAIL: $*"; }
summary(){ section "TEST SUMMARY"; log "Pass: $PASS_COUNT"; log "Warnings: $WARN_COUNT"; log "Fail: $FAIL_COUNT"; log "Log: $RESULT_LOG"; [[ $FAIL_COUNT -eq 0 ]] && log "OVERALL RESULT: PASS" || log "OVERALL RESULT: FAIL"; }
die(){ fail "$*"; summary; exit 1; }
require_command(){ command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"; }
service_state(){ systemctl "$2" "$1" 2>/dev/null || true; }
cleanup_runtime(){ sudo systemctl stop "$SERVICE" >/dev/null 2>&1 || true; sudo systemctl disable --now "$DIST_SER2NET_SERVICE" >/dev/null 2>&1 || true; sudo systemctl daemon-reload >/dev/null 2>&1 || true; }
cleanup_on_exit(){ rc=$?; cleanup_runtime; if [[ $KEEP_INSTALLED -eq 0 ]]; then sudo dpkg -P "$PACKAGE" >/dev/null 2>&1 || true; sudo systemctl daemon-reload >/dev/null 2>&1 || true; fi; if [[ $rc -ne 0 && $FAIL_COUNT -eq 0 ]]; then fail "script terminated unexpectedly with exit status $rc"; fi; }
trap cleanup_on_exit EXIT

section "PRE-FLIGHT"
for cmd in awk grep sed find readlink dpkg dpkg-deb dpkg-query systemctl journalctl python3 pgrep ps sha256sum; do require_command "$cmd"; done
if [[ $BUILD_PACKAGE -eq 1 ]]; then for cmd in fakeroot dpkg-buildpackage dpkg-parsechangelog; do require_command "$cmd"; done; fi
for path in src/server.py src/client.py src/status.py src/console_cli.py src/setup_ssh_dispatch.py service/seriald.service config/config.json debian/control debian/rules; do [[ -f "$path" ]] || die "run from ConsoleServer repository root; missing $path"; done
pass "repository layout detected"

section "SOURCE VALIDATION"
grep -nE 'sudo.*ser2net|pkill.*ser2net|/usr/sbin/ser2net' src/server.py || true
if grep -q 'cmd = \["/usr/sbin/ser2net", "-n", "-c", cfg_path\]' src/server.py; then pass "server.py launches ser2net directly"; else fail "direct ser2net launch not found"; fi
if grep -nE 'sudo.*ser2net|pkill.*ser2net' src/server.py >/dev/null; then fail "sudo/pkill ser2net management remains"; else pass "no sudo/pkill ser2net management"; fi
if grep -q '^KillMode=control-group$' service/seriald.service; then pass "KillMode=control-group present"; else fail "KillMode=control-group missing"; fi
if python3 -m py_compile src/server.py src/client.py src/status.py src/console_cli.py src/setup_ssh_dispatch.py; then pass "source Python files compile"; else fail "source Python compilation failed"; fi
rm -rf src/__pycache__

section "PACKAGE BUILD"
if [[ $BUILD_PACKAGE -eq 1 ]]; then
    fakeroot debian/rules clean && dpkg-buildpackage -us -uc -b && pass "package build completed" || die "package build failed"
else
    warn "package build skipped"
fi
if [[ -z "$DEB" ]]; then
    VERSION="$(dpkg-parsechangelog -S Version 2>/dev/null || true)"
    if [[ -n "$VERSION" && -f "../${PACKAGE}_${VERSION}_all.deb" ]]; then DEB="$(readlink -f "../${PACKAGE}_${VERSION}_all.deb")"; else DEB="$(find .. -maxdepth 1 -type f -name "${PACKAGE}_*_all.deb" -printf '%T@ %p\n' | sort -nr | awk 'NR==1 {$1=""; sub(/^ /, ""); print; exit}')"; [[ -n "$DEB" ]] && DEB="$(readlink -f "$DEB")"; fi
fi
[[ -f "$DEB" ]] || die "Debian package not found"
pass "package found: $DEB"

section "PACKAGE CONTENT AND CONTROL"
CONTENTS_FILE="$LOG_DIR/package-contents.txt"
dpkg-deb --contents "$DEB" | tee "$CONTENTS_FILE"
for expected in ./etc/seriald/config.json ./lib/systemd/system/seriald.service ./usr/local/bin/console-cli ./usr/local/bin/console-ssh-dispatch ./usr/local/bin/seriald-client ./usr/local/bin/seriald-status ./usr/local/bin/server.py ./usr/local/bin/setup_ssh_dispatch.py; do grep -Fq "$expected" "$CONTENTS_FILE" && pass "package contains $expected" || fail "package missing $expected"; done
CONTROL_DIR="$LOG_DIR/control"; rm -rf "$CONTROL_DIR"; mkdir -p "$CONTROL_DIR"; dpkg-deb --control "$DEB" "$CONTROL_DIR"
MAINTAINER_SCRIPTS="$(find "$CONTROL_DIR" -maxdepth 1 -type f \( -name preinst -o -name postinst -o -name prerm -o -name postrm \) -print)"
[[ -z "$MAINTAINER_SCRIPTS" ]] && pass "no maintainer service scripts" || { fail "unexpected maintainer scripts"; log "$MAINTAINER_SCRIPTS"; }
SERVICE_LOGIC="$(grep -R -nE 'systemctl|deb-systemd-helper|deb-systemd-invoke' "$CONTROL_DIR" 2>/dev/null || true)"
[[ -z "$SERVICE_LOGIC" ]] && pass "no service activation logic" || { fail "service activation logic found"; log "$SERVICE_LOGIC"; }

section "CLEAN INSTALLATION"
cleanup_runtime
sudo dpkg -P "$PACKAGE" >/dev/null 2>&1 || true
sudo systemctl daemon-reload
sudo dpkg -i "$DEB" && pass "fresh installation completed" || die "installation failed"
STATUS="$(dpkg-query -W -f='${Status}' "$PACKAGE" 2>/dev/null || true)"
[[ "$STATUS" == "install ok installed" ]] && pass "dpkg reports installed" || fail "unexpected dpkg status: $STATUS"

section "INSTALLED FILE VALIDATION"
for path in /usr/local/bin/console-cli /usr/local/bin/console-ssh-dispatch /usr/local/bin/seriald-client /usr/local/bin/seriald-status /usr/local/bin/server.py /usr/local/bin/setup_ssh_dispatch.py /etc/seriald/config.json /lib/systemd/system/seriald.service; do [[ -f "$path" ]] && pass "installed file exists: $path" || fail "installed file missing: $path"; done
python3 -m json.tool /etc/seriald/config.json >/dev/null && pass "config.json valid" || fail "config.json invalid"
sudo python3 -m py_compile /usr/local/bin/console-cli /usr/local/bin/seriald-client /usr/local/bin/seriald-status /usr/local/bin/server.py /usr/local/bin/setup_ssh_dispatch.py && pass "installed Python files compile" || fail "installed Python compilation failed"
grep -q 'cmd = \["/usr/sbin/ser2net", "-n", "-c", cfg_path\]' /usr/local/bin/server.py && pass "installed server.py has direct launch" || fail "installed direct launch missing"
if grep -nE 'sudo.*ser2net|pkill.*ser2net' /usr/local/bin/server.py >/dev/null; then fail "installed server.py still has sudo/pkill"; else pass "installed server.py has no sudo/pkill"; fi
CONFFILES="$(dpkg-query -W -f='${Conffiles}\n' "$PACKAGE" 2>/dev/null || true)"; grep -q '/etc/seriald/config.json' <<<"$CONFFILES" && pass "config.json registered as conffile" || fail "config.json not registered as conffile"

section "SERVICE POLICY"
sudo systemctl daemon-reload
SERIALD_ENABLED="$(service_state "$SERVICE" is-enabled)"; SERIALD_ACTIVE="$(service_state "$SERVICE" is-active)"
[[ "$SERIALD_ENABLED" == disabled ]] && pass "seriald disabled after install" || fail "seriald enablement=$SERIALD_ENABLED"
[[ "$SERIALD_ACTIVE" == inactive ]] && pass "seriald inactive after install" || fail "seriald active state=$SERIALD_ACTIVE"
sudo systemctl disable --now "$DIST_SER2NET_SERVICE" >/dev/null 2>&1 || true
sudo systemctl reset-failed "$DIST_SER2NET_SERVICE" >/dev/null 2>&1 || true
[[ "$(service_state "$DIST_SER2NET_SERVICE" is-enabled)" == disabled ]] && pass "distribution ser2net disabled" || warn "distribution ser2net not disabled"
[[ "$(service_state "$DIST_SER2NET_SERVICE" is-active)" == inactive ]] && pass "distribution ser2net inactive" || warn "distribution ser2net not inactive"
pgrep -x ser2net >/dev/null && { fail "ser2net exists before lifecycle test"; pgrep -a ser2net | tee -a "$RESULT_LOG"; } || pass "no ser2net before lifecycle test"

section "CLI SMOKE TEST"
console-cli --help >/dev/null && pass "console-cli help works" || fail "console-cli help failed"
seriald-status --help >/dev/null && pass "seriald-status help works" || fail "seriald-status help failed"
seriald-client --help >/dev/null && pass "seriald-client help works" || fail "seriald-client help failed"

section "NORMAL START AND PID OWNERSHIP"
TEST_START="$(date '+%Y-%m-%d %H:%M:%S')"
sudo systemctl start "$SERVICE" || fail "service start command failed"
sleep 4
systemctl is-active --quiet "$SERVICE" || { journalctl -u "$SERVICE" --since "$TEST_START" --no-pager | tee -a "$RESULT_LOG"; die "service did not become active"; }
pass "seriald became active"
MAIN_PID="$(systemctl show -p MainPID --value "$SERVICE")"; [[ "$MAIN_PID" =~ ^[0-9]+$ && "$MAIN_PID" -gt 0 ]] && pass "main PID=$MAIN_PID" || fail "invalid main PID=$MAIN_PID"
SER2NET_PIDS="$(pgrep -x ser2net || true)"; [[ -n "$SER2NET_PIDS" ]] && pass "ser2net children launched" || fail "no ser2net children"
for pid in $SER2NET_PIDS; do
    ARGS="$(ps -p "$pid" -o args= 2>/dev/null || true)"; PPID_VALUE="$(ps -p "$pid" -o ppid= 2>/dev/null | tr -d ' ' || true)"; CGROUP_PATH="$(cat "/proc/$pid/cgroup" 2>/dev/null || true)"
    [[ "$ARGS" == /usr/sbin/ser2net\ -n\ -c\ /tmp/seriald_ser2net_configs/cs*.yaml ]] && pass "PID $pid is managed ser2net" || fail "PID $pid unexpected args: $ARGS"
    grep -q 'seriald.service' <<<"$CGROUP_PATH" && pass "PID $pid in seriald cgroup" || fail "PID $pid outside seriald cgroup"
    if [[ "$PPID_VALUE" == "$MAIN_PID" ]]; then
        pass "PID $pid is a direct child of server.py PID $MAIN_PID"
    else
        fail "PID $pid has PPID $PPID_VALUE, expected server.py PID $MAIN_PID"
    fi
done
STARTUP_LOG="$LOG_DIR/startup.log"; journalctl -u "$SERVICE" --since "$TEST_START" --no-pager | tee "$STARTUP_LOG" >/dev/null
LOGGED_PIDS="$(sed -n 's/.*started with PID \([0-9][0-9]*\).*/\1/p' "$STARTUP_LOG")"; [[ -n "$LOGGED_PIDS" ]] && pass "startup log contains child PIDs" || fail "startup log contains no child PIDs"
for pid in $LOGGED_PIDS; do ARGS="$(ps -p "$pid" -o args= 2>/dev/null || true)"; [[ "$ARGS" == /usr/sbin/ser2net\ -n\ -c\ /tmp/seriald_ser2net_configs/cs*.yaml ]] && pass "logged PID $pid is actual ser2net" || fail "logged PID $pid not actual ser2net: $ARGS"; done
if grep -E 'sudo|pam_unix\(sudo|pkill' "$STARTUP_LOG" >/dev/null; then fail "startup journal contains sudo/pkill"; grep -E 'sudo|pam_unix\(sudo|pkill' "$STARTUP_LOG" | tee -a "$RESULT_LOG"; else pass "startup journal has no sudo/pkill"; fi

section "NORMAL STOP AND CLEANUP"
sudo systemctl stop "$SERVICE"; sleep 3
[[ "$(service_state "$SERVICE" is-active)" == inactive ]] && pass "seriald inactive after stop" || fail "seriald not inactive after stop"
pgrep -x ser2net >/dev/null && { fail "orphan ser2net after stop"; pgrep -a ser2net | tee -a "$RESULT_LOG"; } || pass "no ser2net after stop"
STOP_LOG="$LOG_DIR/stop.log"; journalctl -u "$SERVICE" --since "$TEST_START" --no-pager | tee "$STOP_LOG" >/dev/null
grep -q 'Server has been shut down' "$STOP_LOG" && pass "shutdown completion logged" || warn "shutdown completion message not found"
if grep -E 'process.*not found|sudo|pam_unix\(sudo|pkill' "$STOP_LOG" >/dev/null; then fail "shutdown journal contains stale PID/sudo/pkill"; grep -E 'process.*not found|sudo|pam_unix\(sudo|pkill' "$STOP_LOG" | tee -a "$RESULT_LOG"; else pass "shutdown journal clean"; fi

section "REPEATED START/STOP"
for cycle in 1 2 3; do
    sudo systemctl start "$SERVICE" || { fail "cycle $cycle start failed"; break; }; sleep 2
    systemctl is-active --quiet "$SERVICE" || { fail "cycle $cycle not active"; break; }
    pgrep -x ser2net >/dev/null || { fail "cycle $cycle no children"; break; }
    sudo systemctl stop "$SERVICE"; sleep 2
    if pgrep -x ser2net >/dev/null; then fail "cycle $cycle orphan child"; pgrep -a ser2net | tee -a "$RESULT_LOG"; break; fi
    pass "cycle $cycle completed"
done

section "CGROUP EMERGENCY CLEANUP"
sudo systemctl start "$SERVICE"; sleep 3
if systemctl is-active --quiet "$SERVICE"; then
    sudo systemctl kill --kill-who=all --signal=SIGKILL "$SERVICE" || true
    sudo systemctl stop "$SERVICE" || true
    sleep 3
    pgrep -x ser2net >/dev/null && { fail "ser2net remains after cgroup kill"; pgrep -a ser2net | tee -a "$RESULT_LOG"; } || pass "cgroup kill removed all children"
else fail "service did not start for cgroup test"; fi
sudo systemctl reset-failed "$SERVICE" >/dev/null 2>&1 || true

section "CONFFILE PRESERVATION"
BACKUP="$LOG_DIR/config.json.original"; sudo cp /etc/seriald/config.json "$BACKUP"
sudo python3 - <<'PY'
import json
p='/etc/seriald/config.json'
with open(p, encoding='utf-8') as f: data=json.load(f)
with open(p,'w',encoding='utf-8') as f: json.dump(data,f,indent=4); f.write('\n')
PY
MODIFIED_SUM="$(sha256sum /etc/seriald/config.json | awk '{print $1}')"
sudo dpkg -i "$DEB" >/dev/null && CURRENT_SUM="$(sha256sum /etc/seriald/config.json | awk '{print $1}')" || CURRENT_SUM=""
[[ "$MODIFIED_SUM" == "$CURRENT_SUM" ]] && pass "modified conffile preserved" || fail "modified conffile changed"
sudo cp "$BACKUP" /etc/seriald/config.json; sudo rm -f "$BACKUP"

section "PACKAGE INTEGRITY"
VERIFY_OUTPUT="$(sudo dpkg --verify "$PACKAGE" 2>&1 || true)"; [[ -z "$VERIFY_OUTPUT" ]] && pass "dpkg verify clean" || { fail "dpkg verify differences"; log "$VERIFY_OUTPUT"; }
if command -v lintian >/dev/null 2>&1; then
    LINTIAN_LOG="$LOG_DIR/lintian.log"; lintian "$DEB" >"$LINTIAN_LOG" 2>&1 || true
    UNEXPECTED="$(grep '^E:' "$LINTIAN_LOG" | grep -vE 'dir-in-usr-local|file-in-usr-local' || true)"
    [[ -z "$UNEXPECTED" ]] && pass "no unexpected Lintian errors" || { fail "unexpected Lintian errors"; log "$UNEXPECTED"; }
    grep -E 'dir-in-usr-local|file-in-usr-local|file-in-unusual-dir' "$LINTIAN_LOG" >/dev/null && warn "accepted /usr/local Lintian findings remain: $LINTIAN_LOG"
else warn "lintian not installed"; fi

section "FINAL STATE"
cleanup_runtime
sudo systemctl reset-failed "$DIST_SER2NET_SERVICE" >/dev/null 2>&1 || true
log "seriald enabled: $(service_state "$SERVICE" is-enabled)"
log "seriald active:  $(service_state "$SERVICE" is-active)"
log "ser2net enabled: $(service_state "$DIST_SER2NET_SERVICE" is-enabled)"
log "ser2net active:  $(service_state "$DIST_SER2NET_SERVICE" is-active)"
pgrep -x ser2net >/dev/null && { fail "ser2net remains at end"; pgrep -a ser2net | tee -a "$RESULT_LOG"; } || pass "no ser2net remains at end"
summary
[[ $FAIL_COUNT -eq 0 ]]
