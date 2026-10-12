# Debian Package Specifications & Standards Reference

A Debian `.deb` package is an `ar` archive containing:
1. `debian-binary`: Format version (`2.0\n`).
2. `control.tar.xz` or `control.tar.gz`: Package metadata and maintainer scripts.
3. `data.tar.xz` or `data.tar.gz`: File payload installed to the target system.

Package building is carried out via `dpkg-deb -b <staging_dir> <output.deb>`.

---

## 1. `DEBIAN/control` Field Specifications

```control
Package: example-app
Version: 1.0.0-1
Section: utils
Priority: optional
Architecture: amd64
Installed-Size: 1024
Maintainer: Your Name <user@example.com>
Homepage: https://example.com
Depends: libc6 (>= 2.31), libgtk-3-0
Recommends: ca-certificates
Description: Single-line short description
 Multi-line detailed description.
 Each continuation line must start with a leading space.
 A single space followed by a dot denotes an empty line.
```

### Policy Rules
- **Package**: Lowercase alphanumeric characters, plus (`+`), hyphen (`-`), and period (`.`). No underscores or uppercase letters.
- **Version**: Format `[epoch:]upstream_version[-debian_revision]`, e.g. `1.0.0`.
- **Architecture**: `all` (for portable scripts/Java) or specific target (`amd64`, `arm64`, `armhf`, `i386`).
- **Depends**: Comma-separated dependencies. Supports pipe `|` for alternative packages.
- **Installed-Size**: Approximate disk size in KiB.

---

## 2. Maintainer Script Lifecycle

All maintainer scripts live under `DEBIAN/` with permissions `0755` and begin with `#!/bin/sh` and `set -e`.

| Script | Invocation Trigger | Primary Use |
| :--- | :--- | :--- |
| `preinst` | Before unpacking payload | Clean up conflicting legacy files, pre-install checks |
| `postinst` | After unpacking (`configure`) | Configure permissions (SUID), update desktop database, reload AppArmor, register services |
| `prerm` | Before removal (`remove`/`deconfigure`) | Stop daemon services, unload security profiles |
| `postrm` | After removal (`remove`/`purge`) | Clean caches; in `purge` remove configuration and state |

---

## 3. Ownership and Permissions

- Normal files and assets: `0644` (`rw-r--r--`).
- Binaries and scripts: `0755` (`rwxr-xr-x`).
- Maintainer scripts: `0755`.
- Electron SUID root sandbox: Setuid bit cannot be bundled directly; configure in `postinst` via `chown root:root && chmod 4755 /opt/<pkg>/chrome-sandbox`.
- Ownership normalization: Always invoke `dpkg-deb` with `--root-owner-group` to normalize ownership to `root:root`.
