# SONiC Package Architecture Guide (v3)

## Understanding How a Standalone Linux Application Becomes Part of a SONiC Image

**Case Study:** ConsoleServer Integration

---

# 1. Introduction

This guide explains the complete architecture of integrating a standalone Linux application into SONiC.

It focuses on three questions:

1. How does SONiC discover a package?
2. How is the Debian package built?
3. How does the package end up inside the final SONiC image?

---

# 2. End-to-End Architecture

```text
                    make target/sonic-<platform>.bin
                                   │
                                   ▼
                             Top-level Makefile
                                   │
                                   ▼
                               include slave.mk
                                   │
         ┌─────────────────────────┴────────────────────────┐
         ▼                                                  ▼
   include rules/*.mk                              platform/*.mk
         │
         ▼
 Register package metadata
         │
         ▼
   SONIC_DPKG_DEBS list
         │
         ▼
 Generic Debian package build framework
         │
         ▼
 console-server_1.0.0_all.deb
         │
         ▼
 installer *_INSTALLS list
         │
         ▼
 RootFS generation
         │
         ▼
 target/sonic-<platform>.bin
```

---

# 3. Repository Responsibilities

```text
ConsoleServer/
├── debian/          # Debian package definition
├── src/             # Application source
├── service/         # Systemd service files
└── sonic/           # SONiC integration
    ├── rules/
    │   └── console-server.mk
    └── slave.mk
```

The application remains SONiC-agnostic; only the `sonic/` directory contains SONiC-specific integration.

---

# 4. Phase 1 – Debian Packaging

The `debian/` directory defines:

- Package metadata
- Dependencies
- Installed files
- Version
- Maintainer
- Installation paths

Running Debian packaging manually:

```bash
dpkg-buildpackage -us -uc -b
```

Produces:

```text
console-server_<version>_all.deb
```

---

# 5. Phase 2 – Package Registration

`rules/console-server.mk` does **not** build the package.

Instead it registers metadata with SONiC.

Example:

```make
SONIC_CONSOLE_SERVER = console-server_1.0.0_all.deb

$(SONIC_CONSOLE_SERVER)_SRC_PATH = $(SRC_PATH)/console-server

SONIC_DPKG_DEBS += $(SONIC_CONSOLE_SERVER)
```

Meaning:

- package name
- source tree
- package type

The source tree contains `debian/`, which the generic SONiC package builder later uses.

---

# 6. Phase 3 – Generic Debian Build

Conceptually:

```text
SONIC_DPKG_DEBS
      │
      ▼
Generic SONiC package rules
      │
      ▼
src/console-server/
      │
      ├── debian/control
      ├── debian/rules
      └── ...
      │
      ▼
dpkg-buildpackage
      │
      ▼
console-server_1.0.0_all.deb
```

`rules/console-server.mk` does **not** invoke `dpkg-buildpackage` directly. The SONiC build framework does.

---

# 7. Phase 4 – Image Installation

After the `.deb` exists, it must be selected for installation.

`slave.mk` contributes packages to installer targets.

Conceptually:

```text
console-server_1.0.0_all.deb
          │
          ▼
*_INSTALLS
          │
          ▼
Installer
          │
          ▼
RootFS
```

Building a package and installing it into an image are separate phases.

---

# 8. Phase 5 – Root Filesystem

The installer installs the package into the image root filesystem.

Typical results:

```text
/usr/bin/console-cli
/usr/bin/seriald-client
/usr/lib/console-server/
/etc/seriald/
/lib/systemd/system/
```

---

# 9. Make Variable Flow

```text
rules/console-server.mk
        │
        ├── SONIC_CONSOLE_SERVER
        ├── SRC_PATH
        └── SONIC_DPKG_DEBS
                  │
                  ▼
       Generic SONiC package builder
                  │
                  ▼
      console-server_1.0.0_all.deb
                  │
                  ▼
          *_INSTALLS (slave.mk)
                  │
                  ▼
             RootFS Builder
                  │
                  ▼
           SONiC Image (.bin)
```

---

# 10. Build Stage vs Install Stage

| Stage | Responsible Component | Output |
|-------|------------------------|--------|
| Package definition | `debian/` | Packaging metadata |
| Package registration | `rules/console-server.mk` | SONIC_DPKG_DEBS entry |
| Package build | Generic SONiC framework | `.deb` |
| Image selection | `slave.mk` | `*_INSTALLS` |
| RootFS generation | Installer | Installed files |
| Image generation | Build system | `.bin` |

---


---

# Parsing Order: Why `SONIC_HOST_FEATURE_DEBS` Works

A common question is:

> Does `slave.mk` execute before `rules/*.mk`?

The answer is **yes, but only partially**.

GNU Make first starts parsing `slave.mk`. When it reaches the `include rules/*.mk` statement, it temporarily switches to parsing the rule files, then returns to continue parsing the remainder of `slave.mk`.

Conceptually:

```text
Top-level Makefile
        │
        ▼
parse slave.mk
        │
        ▼
include rules/*.mk
        │
        ▼
parse rules/console-server.mk
        │
        ├── SONIC_DPKG_DEBS += $(SONIC_CONSOLE_SERVER)
        └── SONIC_HOST_FEATURE_DEBS += $(SONIC_CONSOLE_SERVER)
        │
        ▼
return to slave.mk
        │
        ▼
continue parsing slave.mk
```

Later in `slave.mk`, the following code is evaluated:

```make
$(foreach installer,$(SONIC_INSTALLERS),\
    $(eval $(installer)_INSTALLS += $(SONIC_HOST_FEATURE_DEBS)))
```

At this point, `SONIC_HOST_FEATURE_DEBS` has already been populated by
`rules/console-server.mk`.

Therefore, each installer receives:

```text
console-server_1.0.0_all.deb
        │
        ▼
sonic-<platform>.bin_INSTALLS
```

This is why the placement of the `include rules/*.mk` statement is important. The package-registration variables must be defined before `slave.mk` expands the installer package lists.


# 11. Common Mistakes

- Assuming `rules/*.mk` builds the package.
- Assuming `slave.mk` builds the package.
- Forgetting to add the package to the installer.
- Modifying the application for SONiC-specific behavior.

---

# 12. Key Takeaways

```text
debian/
    = How to build the package

rules/console-server.mk
    = Tell SONiC that the package exists

Generic SONiC build framework
    = Build the Debian package

slave.mk
    = Decide which images install the package

Installer
    = Populate the RootFS

SONiC Image
    = Final deliverable
```

The separation of responsibilities makes applications reusable outside SONiC while allowing the SONiC build system to package and deploy them consistently.
