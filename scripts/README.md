# ConsoleServer SONiC Tracking Scripts

These scripts compare and synchronize the ConsoleServer tracking repository
with the real SONiC source tree.

The scripts use an explicit mapping list. They do **not** copy every file in
the tracking repository. Tracking-only files and directories such as
`src/install_helpers.sh`, `sonic/note.txt`, `scripts/`, and `console/` are
intentionally excluded.

## Default folders

When no folder options are supplied, the scripts use:

```text
Tracking repository: ~/git/ConsoleServer
Real SONiC tree:     ~/git/sonic_console
```

Both long option names are accepted:

```text
--tracking-root PATH
--tracking-folder PATH

--sonic-root PATH
--sonic-folder PATH
```

`~` is expanded automatically.

## 1. Compare tracking with SONiC

The comparison is read-only. It checks file contents and executable mode bits.

Using default folders:

```bash
./compare_tracking_with_sonic.py
```

Using custom folders:

```bash
./compare_tracking_with_sonic.py \
    --tracking-folder /path/to/ConsoleServer \
    --sonic-folder /path/to/sonic-buildimage
```

Exit status:

```text
0  All mapped files match.
1  One or more mapped files differ or are missing.
```

## 2. Sync SONiC to tracking

This copies mapped files from the real SONiC tree into the tracking
repository.

Dry run with default folders:

```bash
./sync_sonic_to_tracking.py
```

Apply changes:

```bash
./sync_sonic_to_tracking.py --apply
```

Apply changes using custom folders:

```bash
./sync_sonic_to_tracking.py \
    --tracking-folder /path/to/ConsoleServer \
    --sonic-folder /path/to/sonic-buildimage \
    --apply
```

The dry run reports files that would be updated or obsolete tracking paths
that would be removed. No file is modified unless `--apply` is supplied.

## 3. Sync tracking to SONiC

This copies mapped files from the tracking repository into the real SONiC
tree.

Dry run with default folders:

```bash
./sync_tracking_to_sonic.py
```

Apply changes:

```bash
./sync_tracking_to_sonic.py --apply
```

Apply changes using custom folders:

```bash
./sync_tracking_to_sonic.py \
    --tracking-folder /path/to/ConsoleServer \
    --sonic-folder /path/to/sonic-buildimage \
    --apply
```

Tracking-only files are not copied into the SONiC tree.

## Recommended workflow

Before changing either tree:

```bash
./compare_tracking_with_sonic.py
```

To update the tracking repository from a tested SONiC tree:

```bash
./sync_sonic_to_tracking.py
./sync_sonic_to_tracking.py --apply
./compare_tracking_with_sonic.py
```

To apply tracking-repository changes to a SONiC tree:

```bash
./sync_tracking_to_sonic.py
./sync_tracking_to_sonic.py --apply
./compare_tracking_with_sonic.py
```

Review Git changes after every applied synchronization:

```bash
git status --short
git diff
```

## Help

Each script provides command-line help:

```bash
./compare_tracking_with_sonic.py --help
./sync_sonic_to_tracking.py --help
./sync_tracking_to_sonic.py --help
```
