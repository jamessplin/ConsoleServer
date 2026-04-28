## Console Server Installation & Removal

### Using the console script
- Install console server: `sudo ./console`
- Remove console server: `sudo ./console --remove`

### Using Makefile
- Install console server: `make install`
- Remove console server: `make uninstall`

## XR17 Driver Placement

Place the driver source folder at:

- `drivers/xr17-lnx2.6.32-and-newer-pak_ver2.6/`

Example:

```bash
cp -a ~/workplace/xr17-lnx2.6.32-and-newer-pak_ver2.6 ./drivers/
make driver-build
sudo make driver-install
```
