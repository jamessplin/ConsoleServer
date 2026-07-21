# ConsoleServer host package
#
# This rule is gated by INCLUDE_CONSOLE_SERVER. The package source is expected
# at src/console-server.

ifeq ($(INCLUDE_CONSOLE_SERVER), y)
ifneq ($(wildcard $(SRC_PATH)/console-server),)

SONIC_CONSOLE_SERVER_VERSION = 1.0.0
SONIC_CONSOLE_SERVER = console-server_$(SONIC_CONSOLE_SERVER_VERSION)_all.deb

$(SONIC_CONSOLE_SERVER)_SRC_PATH = $(SRC_PATH)/console-server

SONIC_DPKG_DEBS += $(SONIC_CONSOLE_SERVER)
SONIC_HOST_FEATURE_DEBS += $(SONIC_CONSOLE_SERVER)

else
$(warning INCLUDE_CONSOLE_SERVER=y but $(SRC_PATH)/console-server is missing; skipping ConsoleServer package)
endif
endif
