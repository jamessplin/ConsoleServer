# SONiC ConsoleServer CLI Tests

The same pytest files support two backends:

- **stub**: local development, no SONiC switch required;
- **live**: execute the public SONiC CLI directly on the switch where pytest runs.

The test files no longer import stub classes. `tests/conftest.py` selects the backend, so there is no need to delete or edit tests before moving them to a switch.

## Local stub run

```bash
./run_stub.sh
```

Equivalent command:

```bash
python3 -m pytest -q --backend=stub
```

## Live SONiC read-only run

Copy the directory to the SONiC switch and run:

```bash
./run_live.sh
```

Equivalent command:

```bash
python3 -m pytest -q --backend=live
```

The default live run executes read-only and negative-input checks. Tests that change configuration are skipped.

## Live configuration tests

Use a console line reserved for testing:

```bash
./run_live.sh --allow-destructive --test-port 24
```

These tests can change port and group configuration. Run them only in a controlled environment and restore the desired configuration afterward.

## Live user tests

User tests are separately guarded because they create and delete a Linux/NSS user:

```bash
export SONIC_CLI_TEST_USER=cs_pytest_user
export SONIC_CLI_TEST_GROUP=all-test-lines
export SONIC_CLI_TEST_PASSWORD='temporary-test-password'

./run_live.sh \
    --allow-destructive \
    --allow-user-tests \
    --test-port 24
```

Do not use a production account or password.

## Excluding manual cases

Manual cases are skipped automatically, but can also be excluded explicitly:

```bash
./run_live.sh -m 'not manual'
```

See `MANUAL_TEST_CASES.md` for tests requiring serial hardware, interactive terminals, multiple clients, service restart, or reboot.

## Backend design

```text
test_*.py
    ↓
cli_for fixture
    ├── --backend=stub → tests/stubs/stub_*.py
    └── --backend=live → subprocess with shell=False
```

The live backend executes commands locally on the SONiC switch. It adds `sudo -n` to privileged commands when pytest is not already running as root.
