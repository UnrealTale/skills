# Shell Scripts & Native ELF Binary Packaging Guide

This guide covers Bash/Sh script utilities and compiled native standalone binaries (Go, Rust, C/C++).

---

## 1. Single-File Shell Scripts

- **Architecture**: `Architecture: all` (portable shell script).
- **Placement**: Direct installation to `/usr/bin/<package-name>`.
- **Permissions**: Must be `0755` (`chmod 755`).
- **Dependencies**: Automatically detects `zsh` shebangs and common CLI commands (`curl`, `wget`, `jq`, `git`, `rsync`) on top of `bash, coreutils`.
- **Desktop Integration**: Omitted by default for CLI scripts (pass `--gui` only if a desktop entry is desired).

---

## 2. Multi-File Shell Projects

For complex shell scripts containing shared libraries or templates:
- Install the project tree into `/opt/<package-name>/`.
- Create a launcher in `/usr/bin/<package-name>`:
  ```sh
  #!/bin/sh
  exec /opt/<package-name>/main.sh "$@"
  ```

---

## 3. Compiled Native ELF Binaries (Go / Rust / C / C++)

### Architecture & Shared Library Detection
Inspect ELF headers to identify the target architecture:
- `EM_X86_64` (`0x3E`) -> `amd64`
- `EM_AARCH64` (`0xB7`) -> `arm64`
- `EM_386` (`0x03`) -> `i386`
- `EM_ARM` (`0x28`) -> `armhf`
- `EM_RISCV` (`0xF3`) -> `riscv64`

`scripts/make_deb.py` automatically inspects ELF `NEEDED` headers via `readelf -d` / `objdump -p` and maps system shared libraries to Debian packages (including Ubuntu 24.04+ `t64` package alternatives), while excluding any `.so` libraries already bundled in `/opt/<package-name>/`.

---

## 4. Background Services (Systemd Integration)

If the utility runs as a system daemon, pass `--systemd-service /path/to/<name>.service` to `scripts/make_deb.py`, or configure manually:
1. Place unit file at `/lib/systemd/system/<package-name>.service` (`0644`).
2. Register and start in `DEBIAN/postinst`:
   ```sh
   if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
       systemctl daemon-reload >/dev/null 2>&1 || true
       systemctl enable --now <package-name>.service >/dev/null 2>&1 || true
   fi
   ```
3. Stop and disable in `DEBIAN/prerm`:
   ```sh
   if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
       systemctl stop <package-name>.service >/dev/null 2>&1 || true
       systemctl disable <package-name>.service >/dev/null 2>&1 || true
   fi
   ```

---

## Quick Build Commands

```bash
# Shell script (CLI)
python3 scripts/make_deb.py \
  --source ./backup-tool.sh \
  --name backup-tool \
  --type shell \
  --depends "bash, tar, gzip, rsync"

# Compiled ELF binary (Go/Rust) with auto-detected arch & NEEDED libs
python3 scripts/make_deb.py \
  --source ./bin/my-go-cli \
  --name my-go-cli \
  --type binary \
  --arch auto \
  --description "High performance CLI tool"

# Compiled ELF daemon with systemd service unit
python3 scripts/make_deb.py \
  --source ./bin/my-daemon \
  --name my-daemon \
  --type binary \
  --systemd-service ./my-daemon.service
```
