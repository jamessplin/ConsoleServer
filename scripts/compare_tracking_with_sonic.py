#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Mapping:
    tracking: str
    sonic: str


MAPPINGS = [
    # Parent SONiC integration files.
    Mapping(
        "sonic/device/hyve/arm64-hyve_hwa024m_hm-r0/"
        "hyve_hwa024m_hm/console_server.json",
        "device/hyve/arm64-hyve_hwa024m_hm-r0/"
        "hyve_hwa024m_hm/console_server.json",
    ),
    Mapping("sonic/rules/config", "rules/config"),
    Mapping("sonic/rules/console-server.mk", "rules/console-server.mk"),
    Mapping("sonic/slave.mk", "slave.mk"),
    Mapping(
        "sonic/src/sonic-config-engine/console_server_config.py",
        "src/sonic-config-engine/console_server_config.py",
    ),
    Mapping(
        "sonic/src/sonic-config-engine/setup.py",
        "src/sonic-config-engine/setup.py",
    ),
    Mapping(
        "sonic/src/sonic-config-engine/sonic-cfggen",
        "src/sonic-config-engine/sonic-cfggen",
    ),
    Mapping(
        "sonic/src/sonic-config-engine/tests/test_console_server_config.py",
        "src/sonic-config-engine/tests/test_console_server_config.py",
    ),
    Mapping(
        "sonic/src/sonic-yang-models/setup.py",
        "src/sonic-yang-models/setup.py",
    ),
    Mapping(
        "sonic/src/sonic-yang-models/tests/files/sample_config_db.json",
        "src/sonic-yang-models/tests/files/sample_config_db.json",
    ),
    Mapping(
        "sonic/src/sonic-yang-models/tests/yang_model_tests/tests/"
        "console_server.json",
        "src/sonic-yang-models/tests/yang_model_tests/tests/"
        "console_server.json",
    ),
    Mapping(
        "sonic/src/sonic-yang-models/tests/yang_model_tests/tests_config/"
        "console_server.json",
        "src/sonic-yang-models/tests/yang_model_tests/tests_config/"
        "console_server.json",
    ),
    Mapping(
        "sonic/src/sonic-yang-models/yang-models/sonic-console-server.yang",
        "src/sonic-yang-models/yang-models/sonic-console-server.yang",
    ),

    # ConsoleServer package copied under src/console-server.
    Mapping("Makefile", "src/console-server/Makefile"),
    Mapping("README.md", "src/console-server/README.md"),
    Mapping("config/config.json", "src/console-server/config/config.json"),
    Mapping(
        "config/config_default.json",
        "src/console-server/config/config_default.json",
    ),
    Mapping(
        "config/get_base_port.py",
        "src/console-server/config/get_base_port.py",
    ),
    Mapping(
        "config/update_base_port.py",
        "src/console-server/config/update_base_port.py",
    ),
    Mapping("debian/README.SONiC", "src/console-server/debian/README.SONiC"),
    Mapping("debian/changelog", "src/console-server/debian/changelog"),
    Mapping("debian/control", "src/console-server/debian/control"),
    Mapping("debian/copyright", "src/console-server/debian/copyright"),
    Mapping("debian/rules", "src/console-server/debian/rules"),
    Mapping("debian/source/format", "src/console-server/debian/source/format"),
    Mapping(
        "doc/24_port_data_center_console_server_software_specification.md",
        "src/console-server/doc/"
        "24_port_data_center_console_server_software_specification.md",
    ),
    Mapping("doc/cli_manual.md", "src/console-server/doc/cli_manual.md"),
    Mapping(
        "doc/console_server_user_management_implementation.md",
        "src/console-server/doc/"
        "console_server_user_management_implementation.md",
    ),
    Mapping(
        "doc/console_server_yang_cvl_implementation_note.md",
        "src/console-server/doc/"
        "console_server_yang_cvl_implementation_note.md",
    ),
    Mapping(
        "doc/cs_installation_guide.md",
        "src/console-server/doc/cs_installation_guide.md",
    ),
    Mapping(
        "doc/design_spec/README.md",
        "src/console-server/doc/design_spec/README.md",
    ),
    Mapping(
        "doc/design_spec/README_1.md",
        "src/console-server/doc/design_spec/README_1.md",
    ),
    Mapping(
        "doc/design_spec/RFC2217_EXPLAINED.md",
        "src/console-server/doc/design_spec/RFC2217_EXPLAINED.md",
    ),
    Mapping(
        "doc/design_spec/client_design_spec.md",
        "src/console-server/doc/design_spec/client_design_spec.md",
    ),
    Mapping(
        "doc/design_spec/client_design_spec_2.md",
        "src/console-server/doc/design_spec/client_design_spec_2.md",
    ),
    Mapping(
        "doc/design_spec/client_design_spec_3.md",
        "src/console-server/doc/design_spec/client_design_spec_3.md",
    ),
    Mapping(
        "doc/design_spec/client_rfc2217_design_spec.md",
        "src/console-server/doc/design_spec/client_rfc2217_design_spec.md",
    ),
    Mapping(
        "doc/design_spec/client_select.md",
        "src/console-server/doc/design_spec/client_select.md",
    ),
    Mapping(
        "doc/design_spec/console_cli_design_spec.md",
        "src/console-server/doc/design_spec/console_cli_design_spec.md",
    ),
    Mapping(
        "doc/design_spec/cs_share_mode.md",
        "src/console-server/doc/design_spec/cs_share_mode.md",
    ),
    Mapping(
        "doc/design_spec/design_spec.md",
        "src/console-server/doc/design_spec/design_spec.md",
    ),
    Mapping(
        "doc/design_spec/server_design_spec.md",
        "src/console-server/doc/design_spec/server_design_spec.md",
    ),
    Mapping(
        "doc/design_spec/systemctl.md",
        "src/console-server/doc/design_spec/systemctl.md",
    ),
    Mapping(
        "service/seriald.service",
        "src/console-server/service/seriald.service",
    ),
    Mapping("src/client.py", "src/console-server/src/client.py"),
    Mapping(
        "src/console-ssh-dispatch.sh",
        "src/console-server/src/console-ssh-dispatch.sh",
    ),
    Mapping(
        "src/console-ssh-dispatch.sh.j2",
        "src/console-server/src/console-ssh-dispatch.sh.j2",
    ),
    Mapping("src/console_cli.py", "src/console-server/src/console_cli.py"),
    Mapping("src/server.py", "src/console-server/src/server.py"),
    Mapping(
        "src/setup_ssh_dispatch.py",
        "src/console-server/src/setup_ssh_dispatch.py",
    ),
    Mapping("src/status.py", "src/console-server/src/status.py"),
    Mapping(
        "unittest/test_config.sh",
        "src/console-server/unittest/test_config.sh",
    ),
    Mapping(
        "unittest/test_group.sh",
        "src/console-server/unittest/test_group.sh",
    ),
    Mapping(
        "unittest/test_install.sh",
        "src/console-server/unittest/test_install.sh",
    ),
    Mapping(
        "unittest/test_operation.sh",
        "src/console-server/unittest/test_operation.sh",
    ),
    Mapping(
        "unittest/test_port.sh",
        "src/console-server/unittest/test_port.sh",
    ),
    Mapping(
        "unittest/test_share_mode.sh",
        "src/console-server/unittest/test_share_mode.sh",
    ),
    Mapping(
        "unittest/test_user.sh",
        "src/console-server/unittest/test_user.sh",
    ),

    # sonic-utilities submodule files.
    Mapping(
        "sonic/src/sonic-utilities/.gitignore",
        "src/sonic-utilities/.gitignore",
    ),
    Mapping(
        "sonic/src/sonic-utilities/config/console_server.py",
        "src/sonic-utilities/config/console_server.py",
    ),
    Mapping(
        "sonic/src/sonic-utilities/config/main.py",
        "src/sonic-utilities/config/main.py",
    ),
    Mapping(
        "sonic/src/sonic-utilities/connect/console_server.py",
        "src/sonic-utilities/connect/console_server.py",
    ),
    Mapping(
        "sonic/src/sonic-utilities/connect/main.py",
        "src/sonic-utilities/connect/main.py",
    ),
    Mapping(
        "sonic/src/sonic-utilities/scripts/console-server-config-generate",
        "src/sonic-utilities/scripts/console-server-config-generate",
    ),
    Mapping(
        "sonic/src/sonic-utilities/setup.py",
        "src/sonic-utilities/setup.py",
    ),
    Mapping(
        "sonic/src/sonic-utilities/show/console_server.py",
        "src/sonic-utilities/show/console_server.py",
    ),
    Mapping(
        "sonic/src/sonic-utilities/show/main.py",
        "src/sonic-utilities/show/main.py",
    ),
    Mapping(
        "sonic/src/sonic-utilities/sonic-utilities-data/debian/"
        "console-server.service",
        "src/sonic-utilities/sonic-utilities-data/debian/"
        "console-server.service",
    ),
    Mapping(
        "sonic/src/sonic-utilities/sonic-utilities-data/debian/install",
        "src/sonic-utilities/sonic-utilities-data/debian/install",
    ),
    Mapping(
        "sonic/src/sonic-utilities/sonic-utilities-data/debian/links",
        "src/sonic-utilities/sonic-utilities-data/debian/links",
    ),
    Mapping(
        "sonic/src/sonic-utilities/sonic_console_server_manager/__init__.py",
        "src/sonic-utilities/sonic_console_server_manager/__init__.py",
    ),
    Mapping(
        "sonic/src/sonic-utilities/"
        "sonic_console_server_manager/config_generate.py",
        "src/sonic-utilities/"
        "sonic_console_server_manager/config_generate.py",
    ),
    Mapping(
        "sonic/src/sonic-utilities/sonic_console_server_manager/manager.py",
        "src/sonic-utilities/sonic_console_server_manager/manager.py",
    ),
    Mapping(
        "sonic/src/sonic-utilities/tests/sonic_console_server_manager/"
        "test_config_generate.py",
        "src/sonic-utilities/tests/sonic_console_server_manager/"
        "test_config_generate.py",
    ),
    Mapping(
        "sonic/src/sonic-utilities/tests/sonic_console_server_manager/"
        "test_connect_console_server.py",
        "src/sonic-utilities/tests/sonic_console_server_manager/"
        "test_connect_console_server.py",
    ),
    Mapping(
        "sonic/src/sonic-utilities/tests/sonic_console_server_manager/"
        "test_console_server.py",
        "src/sonic-utilities/tests/sonic_console_server_manager/"
        "test_console_server.py",
    ),
    Mapping(
        "sonic/src/sonic-utilities/tests/sonic_console_server_manager/"
        "test_console_server_manager.py",
        "src/sonic-utilities/tests/sonic_console_server_manager/"
        "test_console_server_manager.py",
    ),
    Mapping(
        "sonic/src/sonic-utilities/tests/sonic_console_server_manager/"
        "test_show_console_server.py",
        "src/sonic-utilities/tests/sonic_console_server_manager/"
        "test_show_console_server.py",
    ),
]


TRACKING_ONLY = [
    "src/install_helpers.sh",
    "sonic/note.txt",
    "scripts",
    "console",
]


OBSOLETE_TRACKING_PATHS = [
    "sonic/device/console_server.json",
    "sonic/src/sonic-utilities/tests/sonic_console_server_manager/"
    "test_manager.py",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def executable_bits(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode) & 0o111


def validate_roots(tracking_root: Path, sonic_root: Path) -> None:
    if not tracking_root.is_dir():
        raise SystemExit(f"ERROR: tracking root not found: {tracking_root}")
    if not sonic_root.is_dir():
        raise SystemExit(f"ERROR: SONiC root not found: {sonic_root}")
    if not (tracking_root / ".git").exists():
        raise SystemExit(f"ERROR: not a Git work tree: {tracking_root}")
    if not (sonic_root / ".git").exists():
        raise SystemExit(f"ERROR: not a Git work tree: {sonic_root}")


def copy_verified(source: Path, target: Path) -> str:
    if not source.is_file():
        raise SystemExit(f"ERROR: source file missing: {source}")
    if target.exists() and not target.is_file():
        raise SystemExit(f"ERROR: target is not a regular file: {target}")

    if target.is_file():
        same_data = sha256(source) == sha256(target)
        same_exec = executable_bits(source) == executable_bits(target)
        if same_data and same_exec:
            return "UNCHANGED"

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

    if sha256(source) != sha256(target):
        raise SystemExit(f"ERROR: copy verification failed: {target}")
    if executable_bits(source) != executable_bits(target):
        raise SystemExit(f"ERROR: executable mode verification failed: {target}")

    return "UPDATED"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare only the explicitly mapped ConsoleServer files between "
            "the tracking repository and the real SONiC tree."
        )
    )
    parser.add_argument(
        "--tracking-root",
        type=Path,
        default=Path.home() / "git/ConsoleServer",
    )
    parser.add_argument(
        "--sonic-root",
        type=Path,
        default=Path.home() / "git/sonic_console",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tracking_root = args.tracking_root.expanduser().resolve()
    sonic_root = args.sonic_root.expanduser().resolve()
    validate_roots(tracking_root, sonic_root)

    differences = 0

    for item in MAPPINGS:
        tracking = tracking_root / item.tracking
        sonic = sonic_root / item.sonic

        if not tracking.is_file():
            print(f"MISSING IN TRACKING: {item.tracking}")
            differences += 1
            continue

        if not sonic.is_file():
            print(f"MISSING IN SONIC:    {item.sonic}")
            differences += 1
            continue

        if sha256(tracking) != sha256(sonic):
            print(f"CONTENT DIFFERS:     {item.tracking}")
            differences += 1
            continue

        if executable_bits(tracking) != executable_bits(sonic):
            print(f"MODE DIFFERS:        {item.tracking}")
            differences += 1

    for relative in OBSOLETE_TRACKING_PATHS:
        path = tracking_root / relative
        if path.exists():
            print(f"OBSOLETE IN TRACKING: {relative}")
            differences += 1

    print()
    print(f"Compared {len(MAPPINGS)} explicitly mapped files.")
    print("Tracking-only paths are intentionally ignored:")
    for relative in TRACKING_ONLY:
        print(f"  {relative}")

    if differences:
        print(f"RESULT: {differences} difference(s) found")
        return 1

    print("PASS: all mapped files match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
