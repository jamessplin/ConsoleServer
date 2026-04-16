#!/usr/bin/env python3
import sys
import json

if len(sys.argv) != 3:
    print("Usage: update_base_port.py <config.json> <BASE_PORT>")
    sys.exit(1)

config_path = sys.argv[1]
base_port = int(sys.argv[2])

with open(config_path, 'r', encoding='utf-8') as f:
    config = json.load(f)

for line in config.get('lines', {}).values():
    offset = int(line['ser2net_port']) - int(list(config['lines'].values())[0]['ser2net_port'])
    line['ser2net_port'] = base_port + offset

with open(config_path, 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
