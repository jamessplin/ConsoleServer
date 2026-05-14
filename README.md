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
