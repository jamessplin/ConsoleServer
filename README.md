## Console Server Installation & Removal

### Using the console script
- Install console server: `sudo ./console`
- Remove console server: `sudo ./console --remove`

### Using Makefile
- Install console server: `make install`
- Remove console server: `make uninstall`

## XR17 Driver

The XR17 driver source is vendored in this repository at:

- `drivers/xr17-lnx2.6.32-and-newer-pak_ver2.6/`

Build and install it with:

```bash
make driver-build
sudo make driver-install
```

The driver is for MaxLinear/Exar PCI/PCIe XR17 serial devices, not USB serial
adapters. It is kept under `drivers/` so the kernel module source stays
separate from the user-space console server code.

If you need to refresh the vendored source from a newer upstream copy, replace
the contents of the existing driver directory instead of copying another nested
directory into `drivers/`:

```bash
rsync -a --delete ~/workplace/xr17-lnx2.6.32-and-newer-pak_ver2.6/ \
  drivers/xr17-lnx2.6.32-and-newer-pak_ver2.6/
```
