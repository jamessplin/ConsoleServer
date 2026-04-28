# Makefile for XR17v35x PCIe UARTs for Linux 2.6.32 and newer
KVERSION := $(shell uname -r)
KERNEL_SRC := /lib/modules/$(KVERSION)/build
INSTALL_DIR := /lib/modules/$(KVERSION)/kernel/drivers/char

.PHONY: all build install clean

all: build

obj-m += xr17v35x.o

xrpci-objs := xr17v35x.o

EXTRA_CFLAGS += -DDEBUG=1

build:
	$(MAKE) -C $(KERNEL_SRC) M=$(CURDIR) modules

install:
	install -D -m 0644 xr17v35x.ko $(INSTALL_DIR)/xr17v35x.ko
	depmod -a $(KVERSION)

clean:
	$(MAKE) -C $(KERNEL_SRC) M=$(CURDIR) clean
