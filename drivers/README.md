# Kernel drivers

Place third-party kernel module source folders here.

Recommended layout:

- `drivers/xr17-lnx2.6.32-and-newer-pak_ver2.6/`

This keeps kernel-space code separate from user-space app code in `src/`.

Example:

```bash
cp -a ~/workplace/xr17-lnx2.6.32-and-newer-pak_ver2.6 ./drivers/
make driver-build
sudo make driver-install
```
