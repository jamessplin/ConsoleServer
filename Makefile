# Makefile for Console Server Project

DRIVERS_DIR ?= drivers
XR17_DRIVER_DIR ?= $(DRIVERS_DIR)/xr17-lnx2.6.32-and-newer-pak_ver2.6

.PHONY: install uninstall start stop test lint clean driver-build driver-install driver-clean

install:
	sudo ./console

uninstall:
	sudo ./console --remove

start:
	sudo systemctl start seriald.service

stop:
	sudo systemctl stop seriald.service

test:
	@echo "No tests defined yet. Add your test commands here."

lint:
	@echo "No linter defined yet. Add your lint commands here."

clean:
	@echo "No clean steps defined yet. Add your clean commands here."

driver-build:
	$(MAKE) -C $(XR17_DRIVER_DIR)

driver-install:
	sudo $(MAKE) -C $(XR17_DRIVER_DIR) install

driver-clean:
	$(MAKE) -C $(XR17_DRIVER_DIR) clean
