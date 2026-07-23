# Adding `sonic_console_server_manager` to `sonic-utilities`

**Project:** SONiC ConsoleServer  
**Target:** SONiC 202511  
**Purpose:** Describe how to integrate the shared ConsoleServer manager, CLI modules, generator script, service packaging, and tests into the real `sonic-utilities` source tree.

---

## 1. Scope

The tracking repository contains:

```text
sonic-utilities/
├── config/
│   ├── console_server.py
│   └── main.py
├── connect/
│   ├── console_server.py
│   └── main.py
├── scripts/
│   └── console-server-config-generate
├── setup.py
├── show/
│   ├── console_server.py
│   └── main.py
├── sonic_console_server_manager/
│   ├── __init__.py
│   ├── config_generate.py
│   └── manager.py
├── sonic-utilities-data/
│   └── debian/
│       ├── console-server.service
│       ├── install
│       └── links
└── tests/
    └── sonic_console_server_manager/
```

These files form one integrated feature and should be migrated together.

---

## 2. Component Responsibilities

### `sonic_console_server_manager/`

This is the shared Python implementation layer.

It provides:

- ConfigDB access;
- validation;
- port-expression parsing;
- group handling;
- label validation;
- product-information handling;
- runtime command execution;
- session retrieval;
- generated runtime configuration.

The CLI modules should call this package instead of duplicating logic.

### `config/console_server.py`

Implements configuration commands such as:

```text
config console-server port ...
config console-server operation ...
config console-server group ...
config console-server user ...
```

### `show/console_server.py`

Implements operational and configuration display commands such as:

```text
show console-server running-config
show console-server startup-config
show console-server sessions
show console-server product-info
show console-server port
```

### `connect/console_server.py`

Implements:

```text
connect console-server line <port>
connect console-server label <label>
```

### `scripts/console-server-config-generate`

Provides the SONiC startup/config-load generator:

```text
ConfigDB
    ↓
console-server-config-generate
    ↓
/run/seriald/config.json
```

### `sonic-utilities-data/debian/`

Packages:

- `console-server.service`;
- service links;
- installed support files.

---

## 3. Target Tree

The real SONiC 202511 target is expected to contain:

```text
src/sonic-utilities/
├── config/
├── connect/
├── scripts/
├── show/
├── sonic_console_server_manager/
├── sonic-utilities-data/
├── tests/
└── setup.py
```

Before modifying anything, compare the tracking files with the actual 202511 files.

Do not replace entire shared files such as:

```text
setup.py
config/main.py
show/main.py
connect/main.py
sonic-utilities-data/debian/install
sonic-utilities-data/debian/links
```

Merge only the required ConsoleServer additions.

---

## 4. Migration Order

### Step 1 — Add the shared manager package

Copy:

```text
sonic_console_server_manager/__init__.py
sonic_console_server_manager/manager.py
sonic_console_server_manager/config_generate.py
```

to:

```text
src/sonic-utilities/sonic_console_server_manager/
```

Verify imports directly:

```bash
python3 - <<'PY'
import sonic_console_server_manager
from sonic_console_server_manager import manager
from sonic_console_server_manager import config_generate
print("imports passed")
PY
```

---

### Step 2 — Register the Python package in `setup.py`

This is the only SONiC-specific change required to make
`sonic_console_server_manager` importable after installation.

Add the package to the package list in `setup.py`:

```python
packages=[
    ...
    'sonic_console_server_manager',
]
```

Nothing else is required for the Python package itself because:

- `sonic_console_server_manager/` is a normal Python package.
- It already contains `__init__.py`.
- All ConsoleServer modules import it using the package name.

Verification:

```bash
python3 - <<'PY'
import sonic_console_server_manager
from sonic_console_server_manager import manager
from sonic_console_server_manager import config_generate

print(sonic_console_server_manager.__file__)
print("sonic_console_server_manager import passed")
PY
```

> **Note**
>
> Registering the package in `setup.py` is independent of installing the
> `console-server-config-generate` executable. That script still requires its
> normal script installation entry so that:
>
> ```bash
> command -v console-server-config-generate
> ```
>
> succeeds after installation.


### Step 3 — Add CLI implementation modules

Copy:

```text
config/console_server.py
show/console_server.py
connect/console_server.py
```

to their corresponding directories.

These modules must import shared logic from:

```python
sonic_console_server_manager
```

They should not contain duplicate ConfigDB or validation implementations.

---

### Step 4 — Register CLI command groups

Merge the ConsoleServer command registration into:

```text
config/main.py
show/main.py
connect/main.py
```

Expected command groups:

```text
config console-server
show console-server
connect console-server
```

The exact registration style must match the native 202511 Click structure.

Verification:

```bash
config console-server --help
show console-server --help
connect console-server --help
```

Also verify the existing unrelated CLI commands still load.

---

### Step 5 — Install the generator script

Copy:

```text
scripts/console-server-config-generate
```

to the real `scripts/` directory.

Ensure `setup.py` or Debian packaging installs it at the expected runtime path, for example:

```text
/usr/bin/console-server-config-generate
```

The service file and `config load` implementation must use the same path.

Verification:

```bash
command -v console-server-config-generate
console-server-config-generate --help
```

---

### Step 6 — Add service packaging

Merge:

```text
sonic-utilities-data/debian/console-server.service
```

and the related entries from:

```text
sonic-utilities-data/debian/install
sonic-utilities-data/debian/links
```

Expected service path:

```text
/lib/systemd/system/console-server.service
```

Expected SONiC target link:

```text
sonic.target.wants/console-server.service
```

Do not overwrite the complete upstream `install` or `links` files.

Verification after package build:

```bash
dpkg-deb -c <sonic-utilities-data.deb> | grep console-server
```

---

## 5. Required Runtime Relationship

The final runtime dependency chain should be:

```text
config/main.py
show/main.py
connect/main.py
        │
        ▼
sonic_console_server_manager
        │
        ├── ConfigDB
        ├── console-cli
        ├── seriald-status/runtime socket
        └── product information
```

Startup path:

```text
console-server.service
        │
        ├── ExecStartPre=console-server-config-generate
        │
        ▼
/run/seriald/config.json
        │
        ▼
server.py
```

---

## 6. Tests to Migrate

Copy the focused tests into:

```text
src/sonic-utilities/tests/sonic_console_server_manager/
```

Current tracked tests include:

```text
test_config_generate.py
test_connect_console_server.py
test_console_server.py
test_manager.py
test_show_console_server.py
```

The temporary test:

```text
tmp/test_config_load_console_server.py
```

should remain deferred until the feature is integrated into the native 202511 `config/main.py` environment.

After migration:

1. adapt imports and mocks to the actual 202511 code;
2. move the test into the proper test directory;
3. run it against the native `config.main`;
4. remove the temporary copy only after it passes.

---

## 7. Focused Verification

Run syntax checks:

```bash
python3 -m py_compile \
    config/console_server.py \
    show/console_server.py \
    connect/console_server.py \
    sonic_console_server_manager/__init__.py \
    sonic_console_server_manager/manager.py \
    sonic_console_server_manager/config_generate.py
```

Run focused unit tests:

```bash
pytest -q tests/sonic_console_server_manager
```

Run CLI registration tests:

```bash
config console-server --help
show console-server --help
connect console-server --help
```

Run generator tests:

```bash
console-server-config-generate \
    --bootstrap-config /etc/seriald/config.json \
    --output /tmp/console-server-config.json
```

Validate output:

```bash
python3 -m json.tool /tmp/console-server-config.json >/dev/null
```

---

## 8. Common Integration Mistakes

### Package copied but not registered

Symptom:

```text
ModuleNotFoundError: sonic_console_server_manager
```

Cause:

- directory exists in source;
- `setup.py` does not install it.

### CLI module copied but command is missing

Symptom:

```text
No such command: console-server
```

Cause:

- `console_server.py` exists;
- corresponding `main.py` registration is missing.

### Generator exists in source but not in package

Symptom:

```text
console-server-config-generate: command not found
```

Cause:

- script was copied;
- Debian/setup installation entry was not added.

### Service installed but not linked

Symptom:

```text
console-server.service exists but does not start with sonic.target
```

Cause:

- service file is packaged;
- `debian/links` entry is missing or incorrect.

### Shared files overwritten

Symptom:

- unrelated SONiC CLI commands or package files disappear.

Cause:

- complete tracking copies of `main.py`, `setup.py`, `install`, or `links` replaced the 202511 versions.

---

## 9. Definition of Done

The `sonic_console_server_manager` integration is complete when:

- the package imports successfully;
- `setup.py` installs it;
- config/show/connect CLI groups are registered;
- all focused unit tests pass;
- the generator script is installed;
- `console-server.service` is included in `sonic-utilities-data`;
- the service is linked to `sonic.target`;
- existing unrelated sonic-utilities functions still work;
- the deferred `config load` test passes in the native 202511 framework.

---

## 10. Recommended Commit Structure

Use separate commits where practical:

```text
sonic-utilities: add console server manager package
sonic-utilities: add console server config show and connect commands
sonic-utilities: add console server config generator
sonic-utilities-data: package console server service
sonic-utilities: add console server tests
```

This makes review, rollback, and upstream discussion easier.
