# Kernel drivers

Third-party kernel module sources are vendored here.

Current layout:

- `drivers/xr17-lnx2.6.32-and-newer-pak_ver2.6/`

This keeps kernel-space code separate from user-space app code.

The XR17 driver is for MaxLinear/Exar PCI/PCIe serial devices, not USB serial
adapters. Keeping it as vendored source is fine for this project because the
build depends on a specific patched version. If more third-party drivers are
added later, use a clearer vendor layout such as `drivers/vendor/<name>/`.

From the repository root:

```bash
make driver-build
sudo make driver-install
```

If refreshing the vendored driver from an upstream source package, copy the
contents into the existing directory:

```bash
rsync -a --delete ~/workplace/xr17-lnx2.6.32-and-newer-pak_ver2.6/ \
  drivers/xr17-lnx2.6.32-and-newer-pak_ver2.6/
```
