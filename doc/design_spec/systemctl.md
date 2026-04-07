# Managing Per-Port ser2net Instances with systemd

## 1. Required Files

### a. systemd Template Unit: `/etc/systemd/system/ser2net@.service`
Defines how to start a ser2net instance for each port/config.

### b. YAML Config Files: `tools/seriald/ser2net_cfg/`
One YAML file per port, e.g. `cs1.yaml`, `cs2.yaml`.

### c. (Optional) Helper Script: `tools/seriald/reload_ser2net.sh`
Script to reload/restart all instances after config changes.

---

## 2. File Contents

### a. `/etc/systemd/system/ser2net@.service`
```ini
[Unit]
Description=ser2net instance for %i
After=network.target

[Service]
ExecStart=/usr/sbin/ser2net -n -d -c /home/james/git/diag_test_gen/tools/seriald/ser2net_cfg/%i.yaml
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### b. Example YAML Config: `tools/seriald/ser2net_cfg/cs1.yaml`
```yaml
connection: &cs1
  accepter: tcp,2001
  connector: serialdev,/dev/ttyUSB0,115200n81,local
```
- Adjust `accepter`, `connector`, device, and baud rate as needed for each port.

### c. (Optional) Helper Script: `tools/seriald/reload_ser2net.sh`
```bash
#!/bin/bash
sudo systemctl daemon-reload
for cfg in tools/seriald/ser2net_cfg/cs*.yaml; do
  name=$(basename "$cfg" .yaml)
  sudo systemctl restart ser2net@"$name"
done
```

---

## 3. Boot Behavior
- Enable and start each instance (once per port):
  ```
  sudo systemctl enable --now ser2net@cs1
  sudo systemctl enable --now ser2net@cs2
  ```
- On boot, systemd starts all enabled instances, each using its own YAML config.

---

## 4. Enabling and Starting Instances: One-Time vs. Repeated Use
- You only need to run:
  ```
  sudo systemctl enable --now ser2net@cs1
  sudo systemctl enable --now ser2net@cs2
  ```
  once for each instance. This enables the service to start at every boot and starts it immediately.
- On future boots, systemd will automatically start all enabled instances. You do not need to run these commands again unless you add new instances or want to disable/remove them.
- **Note:** For convenience, you might write a script to enable/disable or manage all instances in bulk. This is useful for initial setup or when adding/removing many ports at once.

---

## 5. Applying Parameter Changes (e.g., Baud Rate)
- Edit the relevant YAML config (e.g., `cs1.yaml`).
- Reload the config by restarting the instance:
  ```
  sudo systemctl restart ser2net@cs1
  ```
- Or use the helper script to restart all:
  ```
  ./tools/seriald/reload_ser2net.sh
  ```
  **Note:** This will restart all console ports. It is not recommended for a data center (DC) console server, as it will interrupt all sessions. Prefer restarting only the affected instance.

---

## 6. Adding/Removing Ports
- To add a port: create a new YAML config and enable a new instance.
- To remove a port: disable and stop the instance, and remove the YAML config.

---

## 7. Monitoring and Logs
- Check status:
  ```
  sudo systemctl status ser2net@cs1
  ```
- View logs:
  ```
  journalctl -u ser2net@cs1
  ```

---

## 8. Example: Multiple Ports
- `tools/seriald/ser2net_cfg/cs1.yaml`:
  ```yaml
  connection: &cs1
    accepter: tcp,2001
    connector: serialdev,/dev/ttyUSB0,115200n81,local
  ```
- `tools/seriald/ser2net_cfg/cs2.yaml`:
  ```yaml
  connection: &cs2
    accepter: tcp,2002
    connector: serialdev,/dev/ttyUSB1,9600n81,local
  ```
- Enable both:
  ```
  sudo systemctl enable --now ser2net@cs1
  sudo systemctl enable --now ser2net@cs2
  ```

---

## 9. Notes
- Adjust all paths as needed for your environment.
- Each instance is independent; changes to one do not affect others.
- Use unique names (cs1, cs2, etc.) matching your YAML files.

---
