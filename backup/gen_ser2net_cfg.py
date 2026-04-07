"""
Usage:
    python3 gen_ser2net_cfg.py [base_port] [num_ports]

This script generates YAML files (cs1.yaml to csN.yaml) in the ser2net_cfg directory,
each configured for a different serial port and Telnet port.

Arguments:
    base_port   (optional) The starting Telnet port number (default: 50000)
    num_ports   (optional) The number of ports/files to generate (default: 24)
"""
import os
import sys

def main():
    script_dir = os.path.abspath(os.path.dirname(__file__))
    base_dir = os.path.join(script_dir, 'ser2net_cfg')
    print(f"[DEBUG] Creating output directory at: {base_dir}")
    os.makedirs(base_dir, exist_ok=True)
    print(f"[DEBUG] Output directory: {base_dir}")

    # Get base port and number of ports from user input or defaults
    base_port = 50000
    num_ports = 24
    if len(sys.argv) > 1:
        try:
            base_port = int(sys.argv[1])
        except ValueError:
            print("[ERROR] Invalid base port number. Using default 50000.")
            base_port = 50000
    if len(sys.argv) > 2:
        try:
            num_ports = int(sys.argv[2])
        except ValueError:
            print("[ERROR] Invalid number of ports. Using default 24.")
            num_ports = 24

    banner = r'define: &banner \r\nser2net port \p device \d [\B]\r\n\r\n'
    for i in range(1, num_ports + 1):
        port = base_port + i
        usb = f'ttyUSB{i-1}'
        fname = f'cs{i}.yaml'
        content = f'''%YAML 1.1
---
{banner}
connection: &com{i}_telnet
  accepter: telnet,{port}
  enable: on
  options:
    banner: *banner
    max-connections: 4
    kickolduser: false
  connector: serialdev,/dev/{usb},115200n81,local
'''
        file_path = os.path.join(base_dir, fname)
        with open(file_path, 'w') as f:
            f.write(content)
        print(f"[DEBUG] Created {file_path}")

if __name__ == "__main__":
    main()
