# Kernel drivers

Third-party kernel module sources are vendored here.

Current layout:

- `drivers/xr17-lnx2.6.32-and-newer-pak_ver2.6/`

This keeps kernel-space code separate from user-space app code.


From this driver folder:

```bash
cd xr17-lnx2.6.32-and-newer-pak_ver2.6
make build
sudo make install
```

