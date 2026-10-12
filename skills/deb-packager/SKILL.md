---
name: deb-packager
description: Package Linux programs (AppImages, archives, native ELF binaries, shell scripts, and runtime-dependent apps like Python, Java, or Node.js) into standard Debian (.deb) packages. Use whenever the user wants to build a .deb file, make software installable and upgradable via dpkg or apt, or bundle executables with desktop icons, isolated runtime environments, or systemd services.
---

# Debian Package Builder (deb-packager)

This skill provides an end-to-end workflow to package arbitrary Linux programs and archives into production-ready Debian (`.deb`) packages. It separates responsibilities cleanly between **Agent intelligence** (inspecting project manifests and deciding runtime commands on the first build) and **deterministic assembly** (`scripts/make_deb.py` + reusable `.recipe.json` caching for zero-effort version upgrades).

---

## 1. Quick Decision & Inspection Workflow

When a user provides a file or directory without specifying the version or runtime:

```
           User provides file/directory
                        │
                        ▼
       ┌─────────────────────────────────┐
       │ 1. Check for Existing Recipe    │
       │    (<name>.recipe.json present?)│
       └─────────────────────────────────┘
              ├── Yes ──► Fast-track build via --recipe (zero re-inspection)
              └── No  ──► Inspect source & manifests -> Build + Export Recipe
```

### Heuristic Discovery Guide (First-Time Build)
- **Version & Metadata Detection**: Extract semantic versions from filenames (`app-1.2.0-x86_64.AppImage` -> `1.2.0`), project manifests (`package.json`, `pyproject.toml`, `pom.xml`, `.desktop`), or safe CLI probes (`./binary --version`). If the user provides a bare binary with no version info, run a quick web search (`search_web("<app-name> latest release version linux")`) to discover the upstream version, description, and homepage.
- **Smart CLI vs GUI Separation**: Desktop entries (`/usr/share/applications/<name>.desktop`) and icon cache hooks are generated automatically only for GUI apps (`appimage`, archives containing `.desktop` or `app.asar`, or when `--gui`, `--desktop-name`, or `--icon` is passed), keeping CLI packages clean.
- For detailed inspection commands, see [references/inspection_and_discovery.md](references/inspection_and_discovery.md).

---

## 2. Five Core Packaging Categories

All Linux software maps into **5 canonical packaging categories** (`--type`):

| Category (`--type`) | Target Programs | Strategy & Placement | Dependency & Architecture Handling | Key Reference |
| :--- | :--- | :--- | :--- | :--- |
| **`appimage`** | `.AppImage` files | Unpack (`--appimage-extract`) into `/opt/<name>/`; link `/usr/bin/<name>` -> `AppRun`, extract `.desktop`/`.DirIcon`, add AppArmor `userns` profile | `amd64`/`arm64`; GUI + GTK/NSS/ALSA (`t64` compatible) deps | [references/appimage.md](references/appimage.md) |
| **`archive`** | `.tar.gz`, `.tar.xz`, `.tgz`, `.zip` | Extract into `/opt/<name>/` preserving Unix permissions & symlinks; parse Electron `app.asar` or `.desktop` if GUI, or ELF `NEEDED` if CLI | `amd64`/`arm64`; GUI deps (if Electron/desktop) or ELF `NEEDED` deps | [references/appimage.md](references/appimage.md) |
| **`binary`** | Compiled ELF binaries (Go, Rust, C/C++) | Single binary to `/usr/bin/<name>` (`0755`); multi-file binary tree to `/opt/<name>/` with symlink in `/usr/bin/<name>` | Auto-detect ELF CPU arch (`amd64`, `arm64`, etc.) & `readelf -d` (`NEEDED`) `.so` libraries | [references/shell_and_binary.md](references/shell_and_binary.md) |
| **`shell`** | Native Shell scripts (`sh`, `bash`, `zsh`) | Single script to `/usr/bin/<name>` (`0755`); multi-file script tree to `/opt/<name>/` | `Architecture: all`; `bash, coreutils` (+ auto-detected `curl`, `jq`, `git`, `rsync`, `zsh`) | [references/shell_and_binary.md](references/shell_and_binary.md) |
| **`runtime`** | Managed-runtime apps (Python, Java, Node.js, Ruby, .NET, PHP, etc.) | Payload to `/opt/<name>/`; optional `--prepare-cmd` builds isolated env (`venv`, `node_modules`) with auto path relocation; wrapper in `/usr/bin/<name>` runs `exec <runtime_cmd> /opt/<name>/<entrypoint> "$@"` | Auto-detects `all` (pure bytecode/scripts) vs `amd64`/`arm64` (if `/opt/<name>` bundles native ELF/venv); maps runtime package (`python3`, `default-jre`, `nodejs`, etc.) | [references/runtime_programs.md](references/runtime_programs.md) |

---

## 3. Reusable Recipe Caching (High-Reuse Upgrade Workflow)

For `runtime` and complex packages, the Agent inspects the project structure once and passes `--prepare-cmd`, `--runtime-cmd`, `--entrypoint`, `--env`, and `--depends` to `scripts/make_deb.py`. The script automatically persists **all** of these fields (plus any extracted icon) into `<name>.recipe.json`.

- **First build (Agent discovers config & exports recipe)**:
  ```bash
  python3 scripts/make_deb.py \
    --source ./myapp-src \
    --name myapp \
    --type runtime \
    --prepare-cmd "python3 -m venv --copies venv && ./venv/bin/pip install --no-cache-dir -r requirements.txt" \
    --runtime-cmd "/opt/myapp/venv/bin/python3" \
    --entrypoint "main.py" \
    --save-recipe ./myapp.recipe.json
  ```
- **Subsequent version upgrades (100% deterministic, zero re-analysis)**:
  ```bash
  python3 scripts/make_deb.py --source ./myapp-v1.2.0-src --recipe ./myapp.recipe.json
  ```
- **Generate standalone builder script**:
  ```bash
  python3 scripts/make_deb.py --source ./myapp-src --recipe ./myapp.recipe.json --generate-builder ./build_myapp_deb.py
  ```
- Detailed recipe schema: [references/recipes.md](references/recipes.md).

---

## 4. Method 1: Using Bundled Automation Script (`scripts/make_deb.py`)

### Common Usage Examples across the 5 Categories

1. **`appimage` / `archive` (AppImage or Electron `.tar.gz`/`.zip`)**:
   ```bash
   python3 scripts/make_deb.py \
     --source /path/to/app-v1.2.0-x86_64.AppImage \
     --type appimage
   ```

2. **`shell` (Native Shell CLI utility, no `.desktop` pollution)**:
   ```bash
   python3 scripts/make_deb.py \
     --source /path/to/my-script.sh \
     --name my-tool \
     --type shell \
     --depends "bash, coreutils, curl, jq"
   ```

3. **`binary` (Compiled Go/Rust/C++ ELF binary with optional systemd service)**:
   ```bash
   python3 scripts/make_deb.py \
     --source /path/to/compiled-binary \
     --name my-daemon \
     --type binary \
     --systemd-service /path/to/my-daemon.service
   ```

4. **`runtime` — Isolated Environment Mode (e.g., Python `venv` or Node.js `npm`)**:
   ```bash
   # Python isolated venv (PEP 668 safe)
   python3 scripts/make_deb.py \
     --source /path/to/python-project \
     --name my-py-app \
     --type runtime \
     --prepare-cmd "python3 -m venv --copies venv && ./venv/bin/pip install --no-cache-dir -r requirements.txt" \
     --runtime-cmd "/opt/my-py-app/venv/bin/python3" \
     --entrypoint "main.py" \
     --depends "python3"

   # Node.js bundled node_modules
   python3 scripts/make_deb.py \
     --source /path/to/node-project \
     --name my-node-cli \
     --type runtime \
     --prepare-cmd "npm install --omit=dev --no-audit" \
     --runtime-cmd "node" \
     --entrypoint "dist/index.js" \
     --depends "nodejs"
   ```

5. **`runtime` — Host Runtime Mode (e.g., Java JAR, system Python/Node/Ruby/.NET)**:
   ```bash
   python3 scripts/make_deb.py \
     --source /path/to/application.jar \
     --name my-java-app \
     --type runtime \
     --runtime-cmd "java -Xms128m -Xmx512m -jar" \
     --depends "default-jre | openjdk-21-jre | openjdk-17-jre"
   ```

---

## 5. Method 2: Manual Packaging Workflow

If custom staging steps or specialized system integration (such as custom udev rules or kernel module hooks) are required:

1. **Create Staging Tree**:
   ```bash
   BUILD_DIR=$(mktemp -d -t deb_stage_XXXXXX)
   mkdir -p "$BUILD_DIR/DEBIAN" "$BUILD_DIR/usr/bin" "$BUILD_DIR/opt/<package-name>"
   ```
2. **Install Payload & Launcher**:
   - Place payload in `/opt/<package-name>/` or `/usr/bin/<package-name>` (`chmod 0755`).
3. **Desktop Integration (GUI apps only)**:
   - Write `$BUILD_DIR/usr/share/applications/<package-name>.desktop` and place icons under `/usr/share/icons/hicolor/512x512/apps/` (or `scalable/apps/` for `.svg`).
4. **Write `DEBIAN/control` & `DEBIAN/conffiles`**:
   - Ensure `Description` has a single-line synopsis followed by space-indented extended description lines.
   - Any file under `/etc/` (such as `/etc/apparmor.d/<package-name>`) must be listed in `DEBIAN/conffiles` (`0644`).
5. **Build Package**:
   ```bash
   dpkg-deb --root-owner-group -b "$BUILD_DIR" "<package-name>_<version>_<arch>.deb"
   rm -rf "$BUILD_DIR"
   ```

---

## 6. Package Verification Checklist

1. **Inspect metadata**: `dpkg-deb -I <package>.deb` (verify `Package`, `Version`, `Architecture`, `Depends`, `conffiles`).
2. **Inspect file list & permissions**: `dpkg-deb -c <package>.deb` (verify `root/root` ownership, `0755` on binaries/launchers, no unintended `.desktop` files for CLI tools, and valid symlink targets).
3. **Install / Upgrade test**: `sudo apt install ./<package>.deb`.
