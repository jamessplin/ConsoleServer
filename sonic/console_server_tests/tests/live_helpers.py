from __future__ import annotations

import re


def normalized(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def find_port_row(output: str, port: int) -> list[str]:
    for line in output.splitlines():
        fields = line.split()
        if fields and fields[0].isdigit() and int(fields[0]) == port:
            return fields
    raise AssertionError(f"console line {port} not found in output:\n{output}")


def value_in_port_row(output: str, port: int, value: str) -> bool:
    return value in find_port_row(output, port)


def extract_product_values(output: str) -> dict[str, int]:
    values = {}
    aliases = {
        "base port": "base_port",
        "max ports": "max_ports",
        "max users": "max_users",
        "max groups": "max_groups",
    }
    for line in output.splitlines():
        m = re.match(r"\s*([^:]+):\s*(\d+)\s*$", line)
        if m and m.group(1).strip().lower() in aliases:
            values[aliases[m.group(1).strip().lower()]] = int(m.group(2))
    return values
