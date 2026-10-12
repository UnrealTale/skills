# Environment & Version Inspection Heuristics

Users often provide a raw executable without knowing its exact version, runtime environment, or packaging requirements.
This guide outlines the systematic inspection and discovery workflow.

---

## 1. Automated Version Extraction

Inspect sources in the following priority order:

1. **Filename Patterns**:
   Parse semantic version strings using regular expressions:
   - `myapp-1.2.3-x86_64.AppImage` -> `1.2.3`
   - `cli_v0.5.1_linux_amd64.tar.gz` -> `0.5.1`
   - `tool-2024.1.bin` -> `2024.1`

2. **Embedded Metadata Files**:
   - Node.js / Electron / Tarball: Parse `package.json` (`"version": "..."`)
   - AppImage / Desktop apps: Parse `.desktop` (`X-AppImage-Version=...` or `Version=...`)
   - Python: Parse `pyproject.toml`, `setup.cfg`, or `setup.py`
   - Java: Inspect `META-INF/MANIFEST.MF` (`Implementation-Version` or `Bundle-Version`)

3. **Safe Command Probe**:
   If the binary is runnable in the local environment, test with a brief timeout:
   ```bash
   ./binary --version
   ./binary -v
   ```

4. **Web Search Fallback**:
   If the file contains no version information (e.g. `slack-desktop-linux.AppImage` or `fzf-linux`), perform a web search or check the upstream release page:
   - Query: `"<app-name>" latest release version linux github`
   - Retrieve the latest stable release tag, project homepage, and application description.

---

## 2. Runtime Environment & Dependency Identification

Use standard Linux diagnostics to identify binary dependencies:

### Diagnostics Commands

1. **File Type & Architecture**:
   ```bash
   file <binary>
   ```
   Identifies whether the target is an ELF 64-bit LSB executable, shell script, zip archive, or Python script.

2. **Shared Library Dependencies (ELF)**:
   ```bash
   readelf -d <binary> | grep NEEDED
   # or
   objdump -p <binary> | grep NEEDED
   ```
   Maps needed dynamic libraries to Debian package names:
   - `libgtk-3.so.0` -> `libgtk-3-0`
   - `libQt5Core.so.5` -> `libqt5core5a`
   - `libnss3.so` -> `libnss3`
   - `libasound.so.2` -> `libasound2`
   - `libX11.so.6` -> `libx11-6`

3. **AppImage & Electron Frameworks**:
   - Check for `resources/app.asar` or `chrome-sandbox` inside extracted AppImages.
   - If present, mark as an Electron/Chromium app and automatically configure the AppArmor profile for Ubuntu 24.04+ user namespace sandboxing.

4. **Script Interpeters**:
   - Read the first line (Shebang): `head -n 1 <script>`
   - `#!/usr/bin/env python3` -> requires `python3`
   - `#!/bin/bash` -> requires `bash, coreutils`
   - `#!/usr/bin/env node` -> requires `nodejs`

---

## 3. Graceful Fallbacks

- If the version cannot be identified from any heuristic, default to `1.0.0` and allow user override.
- If dependencies cannot be extracted dynamically, apply the standard default runtime dependencies defined for the detected package type.
