#!/usr/bin/env python3
import json
import sys

def get_base_port(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    # Get base_port from the info dictionary
    info = config.get('info', {})
    if 'base_port' not in info:
        raise ValueError('base_port not found in info')
    return int(info['base_port'])

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: get_base_port.py <config.json>")
        sys.exit(1)
    print(get_base_port(sys.argv[1]))
