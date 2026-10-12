# AppImage & Archive Packaging Guide for Debian (.deb)

AppImages and prebuilt archives (`.tar.gz`, `.tar.xz`, `.zip`) are standalone distribution formats bundling an application with its runtime dependencies.

## Core Challenges and Solutions

1. **FUSE Runtime Dependency (AppImage)**:
   - Raw AppImages require `libfuse2` or `fuse3` at execution time. Modern distributions (such as Ubuntu 22.04+, Debian 12+) do not always provide `libfuse2` by default.
   - **Recommended Solution**: Extract the AppImage during package build using `--appimage-extract` and install the extracted filesystem tree (`squashfs-root`) to `/opt/<package-name>/`. Link `/usr/bin/<package-name>` to `/opt/<package-name>/AppRun` so bundled environment variables (`LD_LIBRARY_PATH`, `QT_PLUGIN_PATH`) remain intact without needing FUSE.

2. **Desktop Integration & Icons (`.desktop`, `.DirIcon`, `app.asar`)**:
   - AppImages and Electron tarballs typically bundle an embedded `.desktop` file, `.DirIcon`, or `resources/app.asar` containing `package.json` and icons.
   - `scripts/make_deb.py` automatically parses `app.asar` and `.desktop` files, resolves `.DirIcon` symlinks and magic bytes (`.png` / `.svg`), sets `Exec=/usr/bin/<package-name> %U`, and installs the desktop file to `/usr/share/applications/<package-name>.desktop`.
   - Icons are installed into `/usr/share/icons/hicolor/512x512/apps/<package-name>.png` (or `scalable/apps/` for `.svg`) and `/usr/share/pixmaps/`.

3. **Ubuntu 24.04+ Sandbox & AppArmor Profiles**:
   - Electron and Chromium based applications rely on unprivileged user namespaces. Ubuntu 24.04+ restricts unprivileged user namespaces by default, which can cause apps to crash or report `chrome-sandbox` errors.
   - **Solution**: Install a scoped profile to `/etc/apparmor.d/<package-name>` and list `/etc/apparmor.d/<package-name>` in `DEBIAN/conffiles`:
     ```apparmor
     abi <abi/4.0>,
     include <tunables/global>

     profile <package-name> /opt/<package-name>/** flags=(unconfined) {
       userns,
       include if exists <local/<package-name>>
     }
     ```
   - Reload AppArmor during package configuration in `DEBIAN/postinst`:
     ```sh
     if command -v aa-enabled >/dev/null 2>&1 && aa-enabled --quiet 2>/dev/null; then
         apparmor_parser -r -W -T "/etc/apparmor.d/<package-name>" 2>/dev/null || true
     fi
     ```

## Standard Staging Layout

```
pkg_root/
├── DEBIAN/
│   ├── conffiles (lists /etc/apparmor.d/<package-name>)
│   ├── control
│   ├── postinst
│   ├── prerm
│   └── postrm
├── opt/
│   └── <package-name>/
│       ├── AppRun (chmod 0755)
│       └── ...
├── usr/
│   ├── bin/
│   │   └── <package-name> -> /opt/<package-name>/AppRun
│   └── share/
│       ├── applications/
│       │   └── <package-name>.desktop
│       └── icons/hicolor/512x512/apps/
│           └── <package-name>.png
└── etc/apparmor.d/ (for Electron/Chromium apps)
    └── <package-name>
```

## Quick Build Commands

```bash
# Package an AppImage
python3 scripts/make_deb.py \
  --source /path/to/app.AppImage \
  --name my-app \
  --type appimage \
  --description "Desktop application from AppImage"

# Package an Electron or GUI .tar.gz / .zip release
python3 scripts/make_deb.py \
  --source /path/to/app-linux-x64.tar.gz \
  --name my-app \
  --type archive
```
