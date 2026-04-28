.PHONY: build install clean

SUBDIR := xr17-lnx2.6.32-and-newer-pak_ver2.6
KVERSION := $(shell uname -r)
KERNEL_SRC = /lib/modules/$(KVERSION)/build

build:
	$(MAKE) -C $(KERNEL_SRC) M=$(CURDIR)/$(SUBDIR) modules

install:
	$(MAKE) -C $(SUBDIR) install

clean:
	$(MAKE) -C $(SUBDIR) clean
