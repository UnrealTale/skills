#!/usr/bin/env python3
"""
Universal Debian (.deb) Package Builder
========================================
Automates packaging Linux programs into standard Debian (.deb) packages across 5 core categories:
1. appimage : Extract SquashFS (--appimage-extract) to /opt/<name>, link AppRun, parse .desktop/.DirIcon, AppArmor userns
2. archive  : Extract .tar.gz/.tar.xz/.zip preserving Unix permissions & symlinks, parse Electron app.asar or .desktop
3. binary   : Native ELF executables (Go/Rust/C/C++), auto-detect ELF CPU arch and NEEDED shared library dependencies
4. shell    : Native Shell scripts (sh/bash/zsh) installed to /usr/bin/<name> (single-file) or /opt/<name> (multi-file)
5. runtime  : Managed-runtime programs (Python, Java, Node.js, Ruby, .NET, PHP, etc.) unified via:
              - Optional build/isolation hook (--prepare-cmd, e.g. venv + pip, npm ci --omit=dev)
              - Automatic build-path relocation inside /opt/<name>
              - Configurable runtime launcher (--runtime-cmd, --entrypoint, --env)

Recipe Caching (--save-recipe / --recipe / --generate-builder):
Persists all discovered metadata AND runtime hooks (prepare_cmd, runtime_cmd, entrypoint, env_vars, depends, icon_path)
so future version upgrades execute deterministically in one command without LLM re-analysis.
"""

import argparse
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Electron Asar Reader
# ---------------------------------------------------------------------------
class AsarArchive:
    """Lightweight reader for Electron .asar archives."""

    def __init__(self, asar_path: Path):
        self.asar_path = asar_path
        with open(asar_path, "rb") as f:
            u1, u2, u3, json_len = struct.unpack("<IIII", f.read(16))
            self.header_base = 8 + u2
            self.header = json.loads(f.read(json_len).decode("utf-8"))

    def find_file(self, target_name: str):
        """Recursively search for a file in the asar header by filename."""
        def _search(d, prefix=""):
            for k, v in d.items():
                p = f"{prefix}/{k}" if prefix else k
                if "files" in v:
                    found = _search(v["files"], p)
                    if found:
                        return found
                elif k == target_name:
                    return p
            return None
        return _search(self.header.get("files", {}))

    def read_file(self, rel_path: str) -> bytes:
        """Read file contents by relative path."""
        parts = rel_path.strip("/").split("/")
        curr = self.header["files"]
        for i, p in enumerate(parts):
            if p not in curr:
                raise KeyError(f"'{rel_path}' not found in asar archive")
            node = curr[p]
            if i < len(parts) - 1:
                curr = node.get("files", {})
            else:
                curr = node

        offset = int(curr["offset"])
        size = int(curr["size"])
        with open(self.asar_path, "rb") as f:
            f.seek(self.header_base + offset)
            return f.read(size)


# ---------------------------------------------------------------------------
# Architecture, ELF, and Shared Library Detection
# ---------------------------------------------------------------------------
ELF_MACHINE_MAP = {
    0x3E: "amd64",    # EM_X86_64
    0xB7: "arm64",    # EM_AARCH64
    0x03: "i386",     # EM_386
    0x28: "armhf",    # EM_ARM
    0xF3: "riscv64",  # EM_RISCV
}

SONAME_TO_DEB_MAP = {
    "libc.so.6": "libc6 (>= 2.31)",
    "libstdc++.so.6": "libstdc++6",
    "libgcc_s.so.1": "libgcc-s1",
    "libglib-2.0.so.0": "libglib2.0-0 | libglib2.0-0t64",
    "libgtk-3.so.0": "libgtk-3-0 | libgtk-3-0t64",
    "libgtk-4.so.1": "libgtk-4-1",
    "libgdk-3.so.0": "libgtk-3-0 | libgtk-3-0t64",
    "libatk-1.0.so.0": "libatk1.0-0 | libatk1.0-0t64",
    "libatk-bridge-2.0.so.0": "libatspi2.0-0 | libatspi2.0-0t64",
    "libatspi.so.0": "libatspi2.0-0 | libatspi2.0-0t64",
    "libnotify.so.4": "libnotify4",
    "libnss3.so": "libnss3",
    "libnspr4.so": "libnspr4",
    "libasound.so.2": "libasound2 | libasound2t64",
    "libdrm.so.2": "libdrm2",
    "libgbm.so.1": "libgbm1",
    "libX11.so.6": "libx11-6",
    "libXcomposite.so.1": "libxcomposite1",
    "libXdamage.so.1": "libxdamage1",
    "libXext.so.6": "libxext6",
    "libXfixes.so.3": "libxfixes3",
    "libXrandr.so.2": "libxrandr2",
    "libxcb.so.1": "libxcb1",
    "libxkbcommon.so.0": "libxkbcommon0",
    "libwayland-client.so.0": "libwayland-client0",
    "libcups.so.2": "libcups2 | libcups2t64",
    "libpango-1.0.so.0": "libpango-1.0-0",
    "libcairo.so.2": "libcairo2",
    "libdbus-1.so.3": "libdbus-1-3",
    "libexpat.so.1": "libexpat1",
    "libz.so.1": "zlib1g",
    "libssl.so.3": "libssl3 | libssl3t64",
    "libcrypto.so.3": "libssl3 | libssl3t64",
    "libcurl.so.4": "libcurl4 | libcurl4t64",
    "libsqlite3.so.0": "libsqlite3-0",
    "libQt5Core.so.5": "libqt5core5a | libqt5core5t64",
    "libQt5Gui.so.5": "libqt5gui5 | libqt5gui5t64",
    "libQt5Widgets.so.5": "libqt5widgets5 | libqt5widgets5t64",
    "libQt6Core.so.6": "libqt6core6 | libqt6core6t64",
    "libQt6Gui.so.6": "libqt6gui6 | libqt6gui6t64",
    "libQt6Widgets.so.6": "libqt6widgets6 | libqt6widgets6t64",
    "libwebkit2gtk-4.0.so.37": "libwebkit2gtk-4.0-37",
    "libwebkit2gtk-4.1.so.0": "libwebkit2gtk-4.1-0",
    "libayatana-appindicator3.so.1": "libayatana-appindicator3-1",
    "libsecret-1.so.0": "libsecret-1-0",
}

GLIBC_CORE_SONAMES = {
    "libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0",
    "librt.so.1", "libresolv.so.2", "libutil.so.1", "ld-linux-x86-64.so.2",
    "ld-linux-aarch64.so.1", "ld-linux.so.2", "ld-linux-armhf.so.3",
}

# Lightweight fallback lookup for managed runtime extensions -> (default runtime_cmd, default apt Depends)
RUNTIME_EXT_DEFAULTS = {
    ".jar": ("java -jar", ["default-jre | openjdk-21-jre | openjdk-17-jre | openjdk-11-jre"]),
    ".py":  ("python3", ["python3"]),
    ".js":  ("node", ["nodejs"]),
    ".mjs": ("node", ["nodejs"]),
    ".cjs": ("node", ["nodejs"]),
    ".rb":  ("ruby", ["ruby"]),
    ".php": ("php", ["php-cli"]),
    ".pl":  ("perl", ["perl"]),
    ".lua": ("lua", ["lua5.4 | lua5.3"]),
    ".dll": ("dotnet", ["dotnet-runtime-8.0 | dotnet-runtime-7.0 | dotnet-runtime-6.0"]),
}


def is_elf_file(path: Path) -> bool:
    """Return True if path is a regular file with ELF magic bytes."""
    try:
        if not path.is_file() or path.is_symlink():
            return False
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except Exception:
        return False


def detect_elf_arch(elf_path: Path) -> str:
    """Detect Debian architecture (amd64, arm64, etc.) from ELF binary header."""
    try:
        if not elf_path.is_file():
            return "all"
        with open(elf_path, "rb") as f:
            if f.read(4) != b"\x7fELF":
                return "all"
            f.seek(18)
            machine = struct.unpack("<H", f.read(2))[0]
            return ELF_MACHINE_MAP.get(machine, "amd64")
    except Exception:
        return "amd64"


def detect_elf_needed_deps(elf_path: Path, bundled_libs: set[str] | None = None) -> list[str]:
    """Inspect ELF NEEDED dynamic libraries via readelf/objdump and map to Debian packages."""
    if not is_elf_file(elf_path):
        return []
    bundled_libs = bundled_libs or set()
    sonames = []

    for cmd in (["readelf", "-d", str(elf_path)], ["objdump", "-p", str(elf_path)]):
        if not shutil.which(cmd[0]):
            continue
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if "NEEDED" in line:
                        m = re.search(r"\[([^\]]+\.so(?:\.[0-9]+)*)\]", line)
                        if m:
                            sonames.append(m.group(1))
                        else:
                            parts = line.strip().split()
                            if len(parts) >= 2 and ".so" in parts[-1]:
                                sonames.append(parts[-1])
                break
        except Exception:
            pass

    if not sonames:
        return ["libc6 (>= 2.31)"]

    deps = []
    for so in sonames:
        if so in bundled_libs:
            continue
        pkg = "libc6 (>= 2.31)" if so in GLIBC_CORE_SONAMES else SONAME_TO_DEB_MAP.get(so)
        if pkg and pkg not in deps:
            deps.append(pkg)

    return deps or ["libc6 (>= 2.31)"]


def sanitize_package_name(name: str) -> str:
    """Ensure package name conforms to Debian policy: lowercase, alphanumeric + hyphen."""
    name = name.lower()
    for suffix in [".appimage", ".tar.gz", ".tar.xz", ".tgz", ".tar.bz2", ".tar", ".zip", ".jar", ".sh", ".py", ".js", ".bin"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    name = re.sub(r"[-_](?:x86_64|x64|amd64|arm64|aarch64|i386|armhf|linux|gnu|musl)+$", "", name)
    name = re.sub(r"[-_vV.]+\d+\.\d+(?:\.\d+)?(?:[-~+._][0-9a-zA-Z.]+)?$", "", name)
    name = re.sub(r"[^a-z0-9+.-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-.")
    if not name or not name[0].isalnum():
        name = "pkg-" + name if name else "custom-app"
    if len(name) == 1:
        name = f"{name}-app"
    return name


def sanitize_version(version: str) -> str:
    """Ensure version conforms to Debian version policy (must start with a digit)."""
    v = re.sub(r"[^0-9a-zA-Z.+:~-]", ".", str(version).strip().lstrip("vV"))
    v = re.sub(r"\.+", ".", v).strip(".")
    if not v or not v[0].isdigit():
        m = re.search(r"(\d+(?:\.\d+)*)", v)
        v = m.group(1) if m else "1.0.0"
    return v


def detect_version_from_filename(filename: str) -> str | None:
    """Extract semantic version patterns from filename."""
    m = re.search(r"[-_vV.](\d+\.\d+(?:\.\d+)?(?:[-~+][0-9a-zA-Z.]+)?)(?:[-_.]|$)", filename)
    if m:
        return m.group(1).lstrip("vV")
    return None


def probe_binary_version(executable: Path) -> str | None:
    """Safely probe executable with --version / -V to extract semantic version string."""
    if not executable.is_file() or not os.access(executable, os.X_OK):
        return None
    if executable.name.lower().endswith(".appimage"):
        return None
    for flag in ("--version", "-V", "version"):
        try:
            res = subprocess.run(
                [str(executable), flag],
                capture_output=True,
                text=True,
                timeout=2,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"},
                stdin=subprocess.DEVNULL,
                check=False,
            )
            output = (res.stdout or "") + "\n" + (res.stderr or "")
            m = re.search(r"\b[vV]?(\d+\.\d+\.\d+(?:[-+~][0-9a-zA-Z.]+)?)\b", output)
            if not m:
                m = re.search(r"\b[vV]?(\d+\.\d+)\b", output)
            if m:
                return m.group(1)
        except Exception:
            continue
    return None


def normalize_package_type(raw_type: str | None, source: Path | None) -> str:
    """Normalize package type into one of the 5 core types: appimage, archive, binary, shell, runtime."""
    if raw_type and raw_type != "auto":
        # Backward-compatible aliases map cleanly to 'runtime'
        if raw_type in ("python", "java", "nodejs", "node", "ruby", "dotnet"):
            return "runtime"
        return raw_type

    if not source:
        return "binary"

    if source.is_dir():
        files = [f for f in source.iterdir() if f.is_file()]
        if any(f.suffix.lower() in RUNTIME_EXT_DEFAULTS for f in files) or any(
            (source / m).exists() for m in ("package.json", "pyproject.toml", "requirements.txt", "setup.py", "Gemfile")
        ):
            return "runtime"
        if list(source.glob("*.sh")) and not any(is_elf_file(f) for f in files):
            return "shell"
        return "binary"

    name_lower = source.name.lower()
    if name_lower.endswith(".appimage"):
        return "appimage"
    if any(name_lower.endswith(ext) for ext in (".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".tar", ".zip")):
        return "archive"
    if any(name_lower.endswith(ext) for ext in RUNTIME_EXT_DEFAULTS):
        return "runtime"
    if name_lower.endswith((".sh", ".bash", ".zsh")):
        return "shell"

    try:
        with open(source, "rb") as f:
            header = f.read(256)
            if header.startswith(b"\x7fELF"):
                if len(header) >= 11 and header[8:11] == b"\x41\x49\x02":
                    return "appimage"
                return "binary"
            if header.startswith(b"PK\x03\x04"):
                try:
                    with zipfile.ZipFile(source, "r") as zf:
                        if "META-INF/MANIFEST.MF" in zf.namelist():
                            return "runtime"
                except Exception:
                    pass
                return "archive"
            if header.startswith(b"#!"):
                shebang = header.split(b"\n")[0].decode("utf-8", errors="ignore").lower()
                if any(sh in shebang for sh in ("/sh", "/bash", "/dash", "/zsh", "env sh", "env bash", "env zsh")):
                    return "shell"
                return "runtime"
    except Exception:
        pass

    return "shell"


def detect_icon_extension(icon_path: Path) -> str:
    """Determine proper icon extension (.png or .svg) from suffix or file magic bytes."""
    ext = icon_path.suffix.lower()
    if ext in (".png", ".svg", ".xpm"):
        return ext
    try:
        data = icon_path.resolve().read_bytes()[:256]
        if data.startswith(b"\x89PNG"):
            return ".png"
        if b"<svg" in data.lower() or data.lstrip().startswith(b"<?xml"):
            return ".svg"
    except Exception:
        pass
    return ".png"


def format_control_description(summary: str, pkg_name: str) -> str:
    """Format single-line synopsis and multi-line extended description per Debian Policy §5.6.13."""
    lines = [line.strip() for line in (summary or "").strip().splitlines() if line.strip()]
    if not lines:
        synopsis = f"{pkg_name} packaged as a Debian package"
        extended_lines = [
            f"{pkg_name} packaged as a Debian package.",
            "Automatically generated by Universal Deb Packager.",
        ]
    else:
        synopsis = lines[0]
        extended_lines = lines[1:] if len(lines) > 1 else [
            f"{pkg_name} packaged as a Debian package.",
            "Automatically generated by Universal Deb Packager.",
        ]

    formatted_ext = [(" ." if not line else f" {line}") for line in extended_lines]
    return f"{synopsis}\n" + "\n".join(formatted_ext)


# ---------------------------------------------------------------------------
# Builder Core
# ---------------------------------------------------------------------------
class DebPackageBuilder:
    def __init__(self, args):
        self.args = args
        self.source = Path(args.source).resolve() if args.source else None
        self.output_dir = Path(args.output_dir).resolve() if args.output_dir else Path.cwd()
        self.keep_temp = getattr(args, "keep_build_dir", False)
        self.temp_base = Path(args.temp_dir).resolve() if getattr(args, "temp_dir", None) else Path(tempfile.gettempdir())

        if self.source and not self.source.exists():
            raise FileNotFoundError(f"Source file or directory does not exist: {self.source}")

        self.recipe_path = Path(args.recipe).resolve() if getattr(args, "recipe", None) else None
        self.recipe_data = {}
        if self.recipe_path:
            if self.recipe_path.exists():
                print(f"[*] Loading configuration from recipe: {self.recipe_path}")
                self.recipe_data = json.loads(self.recipe_path.read_text(encoding="utf-8"))
            else:
                print(f"[!] Warning: Recipe file {self.recipe_path} not found. Proceeding with heuristics.")

        # Priority: CLI args > Recipe > Source heuristics > Defaults
        raw_type = args.type if (args.type and args.type != "auto") else self.recipe_data.get("type")
        self.pkg_type = normalize_package_type(raw_type, self.source)

        raw_name = (
            args.name
            or self.recipe_data.get("name")
            or (self.source.stem if (self.source and self.source.is_file()) else (self.source.name if self.source else None))
        )
        self.pkg_name = sanitize_package_name(raw_name or "custom-app")

        detected_version = detect_version_from_filename(self.source.name) if self.source else None
        probed_version = None
        if not args.version and not detected_version and not self.recipe_data.get("version"):
            if self.source and self.source.is_file() and self.pkg_type in ("binary", "shell"):
                probed_version = probe_binary_version(self.source)

        raw_version = (
            args.version
            or detected_version
            or probed_version
            or self.recipe_data.get("version")
            or self.recipe_data.get("last_built_version")
            or "1.0.0"
        )
        self.version = sanitize_version(raw_version)
        if not args.version:
            if detected_version:
                print(f"[*] Inferred version from filename: {self.version}")
            elif probed_version:
                print(f"[*] Inferred version from binary --version probe: {self.version}")

        self.maintainer = (
            args.maintainer
            or self.recipe_data.get("maintainer")
            or f"{os.getenv('USER', 'admin')} <{os.getenv('USER', 'admin')}@localhost>"
        )
        self.summary = (
            args.description
            or self.recipe_data.get("description")
            or f"{self.pkg_name} packaged as Debian package"
        )
        self.section = (
            args.section
            or self.recipe_data.get("section")
            or ("devel" if self.pkg_type in ["runtime", "shell"] else "utils")
        )
        self.priority = "optional"
        self.homepage = args.homepage or self.recipe_data.get("homepage") or "https://example.com"

        self.desktop_name = args.desktop_name or self.recipe_data.get("desktop_name")
        self.desktop_category = args.category or self.recipe_data.get("category") or "Utility;"
        self.icon_path = Path(args.icon).resolve() if args.icon else None
        if not self.icon_path and self.recipe_data.get("icon_path"):
            cand = Path(self.recipe_data["icon_path"])
            if not cand.is_absolute() and self.recipe_path:
                cand = (self.recipe_path.parent / cand).resolve()
            if cand.exists():
                self.icon_path = cand

        # Unified runtime configuration (CLI > Recipe > Auto-inference)
        self.prepare_cmd = getattr(args, "prepare_cmd", None) or self.recipe_data.get("prepare_cmd")
        self.runtime_cmd = getattr(args, "runtime_cmd", None) or self.recipe_data.get("runtime_cmd")
        self.entrypoint = getattr(args, "entrypoint", None) or self.recipe_data.get("entrypoint")
        self.env_vars = list(getattr(args, "env", None) or self.recipe_data.get("env_vars") or [])

        # Backward compatibility for legacy flags (--python-mode, --java-opts)
        legacy_py_mode = getattr(args, "python_mode", None) or self.recipe_data.get("python_mode")
        legacy_java_opts = getattr(args, "java_opts", None) or self.recipe_data.get("java_opts")
        if legacy_py_mode == "venv" and not self.prepare_cmd and not self.runtime_cmd:
            if self.source and (self.source.is_dir() or self.source.suffix.lower() == ".py"):
                self.prepare_cmd = (
                    "python3 -m venv --copies venv && "
                    "if [ -f requirements.txt ] && grep -q '[^[:space:]#]' requirements.txt; then "
                    "./venv/bin/pip install --no-cache-dir -r requirements.txt; fi"
                )
                self.runtime_cmd = f"/opt/{self.pkg_name}/venv/bin/python3"
        if legacy_java_opts and not self.runtime_cmd:
            self.runtime_cmd = f"java {legacy_java_opts} -jar"

        self.custom_depends = []
        if args.depends:
            self.custom_depends = [d.strip() for d in args.depends.split(",") if d.strip()]
        elif self.recipe_data.get("depends"):
            self.custom_depends = list(self.recipe_data["depends"])

        self.apparmor_needed = bool(args.apparmor or self.recipe_data.get("apparmor", False))
        self.has_chrome_sandbox = False

        self.systemd_service_path = None
        raw_service = getattr(args, "systemd_service", None) or self.recipe_data.get("systemd_service")
        if raw_service:
            cand_svc = Path(raw_service).resolve()
            if cand_svc.exists():
                self.systemd_service_path = cand_svc
            else:
                raise FileNotFoundError(f"Systemd service file not found: {cand_svc}")

        if getattr(args, "no_desktop", False):
            self.is_gui = False
        elif (
            getattr(args, "gui", False)
            or args.desktop_name
            or args.icon
            or self.recipe_data.get("is_gui")
            or self.recipe_data.get("desktop_name")
            or self.icon_path
            or self.pkg_type == "appimage"
        ):
            self.is_gui = True
        else:
            self.is_gui = False

        self.work_dir = None
        self.staging_dir = None
        self.arch = args.arch or self.recipe_data.get("arch") or "auto"
        self.default_depends = []

    def setup_workdir(self):
        self.temp_base.mkdir(parents=True, exist_ok=True)
        self.work_dir = Path(tempfile.mkdtemp(prefix=f"deb_build_{self.pkg_name}_", dir=self.temp_base))
        self.staging_dir = self.work_dir / "pkg_root"
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        print(f"[*] Temporary staging directory: {self.work_dir}")

    def build(self) -> Path:
        self.setup_workdir()
        try:
            print(f"[*] Packaging {self.pkg_name} (v{self.version}) [Type: {self.pkg_type}]")

            if self.pkg_type == "appimage":
                self._handle_appimage()
            elif self.pkg_type == "archive":
                self._handle_archive()
            elif self.pkg_type == "shell":
                self._handle_shell()
            elif self.pkg_type == "binary":
                self._handle_binary()
            elif self.pkg_type == "runtime":
                self._handle_runtime()
            else:
                raise ValueError(f"Unsupported package type: {self.pkg_type}")

            self._handle_systemd_service()
            self._handle_desktop_and_icon()
            self._write_maintainer_scripts()
            self._write_conffiles()
            self._write_control()
            self._fix_permissions()
            self._verify_staging_symlinks()

            self.output_dir.mkdir(parents=True, exist_ok=True)
            deb_filename = f"{self.pkg_name}_{self.version}_{self.arch}.deb"
            target_deb = self.output_dir / deb_filename
            print(f"[*] Running dpkg-deb to build: {target_deb} ...")
            cmd = ["dpkg-deb", "--root-owner-group", "-b", str(self.staging_dir), str(target_deb)]
            subprocess.check_call(cmd)

            size_mb = target_deb.stat().st_size / (1024 * 1024)
            print(f"[✓] Successfully built: {target_deb} ({size_mb:.2f} MB)")

            if getattr(self.args, "save_recipe", None) or (
                not getattr(self.args, "no_save_recipe", False) and getattr(self.args, "save_recipe", None) is not False
            ):
                self._save_recipe()

            if getattr(self.args, "generate_builder", None):
                self._generate_builder_script()

            return target_deb

        finally:
            if not self.keep_temp and self.work_dir:
                shutil.rmtree(self.work_dir, ignore_errors=True)
            elif self.work_dir:
                print(f"[*] Preserved temporary build directory: {self.work_dir}")

    # -----------------------------------------------------------------------
    # 1. Native Shell Script Handler (shell)
    # -----------------------------------------------------------------------
    def _handle_shell(self):
        """Shell script packaging."""
        self.arch = "all" if self.arch == "auto" else self.arch
        bin_dir = self.staging_dir / "usr" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)

        target_exec = bin_dir / self.pkg_name
        script_to_scan = None
        if self.source.is_file():
            shutil.copy2(self.source, target_exec)
            script_to_scan = target_exec
        else:
            opt_dir = self.staging_dir / "opt" / self.pkg_name
            shutil.copytree(self.source, opt_dir, symlinks=True)
            entry = opt_dir / (self.entrypoint or f"{self.pkg_name}.sh")
            if not entry.is_file():
                entry = opt_dir / "main.sh"
            if not entry.is_file():
                scripts = [f for f in opt_dir.glob("*.sh") if f.is_file()]
                entry = scripts[0] if scripts else (opt_dir / self.pkg_name)
            if entry.is_file():
                entry.chmod(0o755)
                self.entrypoint = entry.name
                script_to_scan = entry
            target_exec.write_text(f"#!/bin/sh\nexec /opt/{self.pkg_name}/{entry.name} \"$@\"\n", encoding="utf-8")

        target_exec.chmod(0o755)
        self.default_depends = self._detect_shell_deps(script_to_scan)

    def _detect_shell_deps(self, script_path: Path | None) -> list[str]:
        deps = ["bash", "coreutils"]
        if not script_path or not script_path.is_file():
            return deps
        try:
            content = script_path.read_text(encoding="utf-8", errors="ignore")
            lines = content.splitlines()
            if lines and lines[0].startswith("#!") and "zsh" in lines[0]:
                deps.append("zsh")
            for tool in ("jq", "curl", "wget", "rsync", "git"):
                if re.search(rf"\b{tool}\b", content) and tool not in deps:
                    deps.append(tool)
        except Exception:
            pass
        return deps

    # -----------------------------------------------------------------------
    # 2. Native ELF Binary Handler (binary)
    # -----------------------------------------------------------------------
    def _handle_binary(self):
        """Compiled ELF binary packaging with ELF NEEDED shared library detection."""
        bundled_libs = set()
        if self.source.is_file():
            self.arch = detect_elf_arch(self.source) if self.arch == "auto" else self.arch
            bin_dir = self.staging_dir / "usr" / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            target_exec = bin_dir / self.pkg_name
            shutil.copy2(self.source, target_exec)
            target_exec.chmod(0o755)
            main_bin = target_exec
        else:
            opt_dir = self.staging_dir / "opt" / self.pkg_name
            shutil.copytree(self.source, opt_dir, symlinks=True)
            bundled_libs = {f.name for f in opt_dir.rglob("*.so*")}
            main_bin = opt_dir / (self.entrypoint or self.pkg_name)
            if not main_bin.is_file():
                execs = [
                    f for f in opt_dir.iterdir()
                    if f.is_file() and os.access(f, os.X_OK) and not f.name.endswith(".so") and ".so." not in f.name
                ]
                if not execs:
                    execs = [f for f in opt_dir.iterdir() if is_elf_file(f) and not f.name.endswith(".so")]
                main_bin = execs[0] if execs else (opt_dir / "run.sh")
            if main_bin.is_file():
                main_bin.chmod(0o755)
                self.entrypoint = str(main_bin.relative_to(opt_dir))
            self.arch = detect_elf_arch(main_bin) if self.arch == "auto" else self.arch
            bin_dir = self.staging_dir / "usr" / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            (bin_dir / self.pkg_name).symlink_to(f"/opt/{self.pkg_name}/{self.entrypoint}")

        self.default_depends = detect_elf_needed_deps(main_bin, bundled_libs=bundled_libs)

    # -----------------------------------------------------------------------
    # 3. Unified Managed-Runtime Handler (runtime: Python, Java, Node.js, etc.)
    # -----------------------------------------------------------------------
    def _handle_runtime(self):
        """Unified handler for any interpreter/VM/isolated-env program."""
        opt_dir = self.staging_dir / "opt" / self.pkg_name
        opt_dir.mkdir(parents=True, exist_ok=True)
        bin_dir = self.staging_dir / "usr" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)

        # 1. Stage source payload into /opt/<pkg_name>
        if self.source.is_dir():
            shutil.copytree(self.source, opt_dir, dirs_exist_ok=True, symlinks=True)
        else:
            target_name = f"{self.pkg_name}.jar" if self.source.suffix.lower() == ".jar" else self.source.name
            shutil.copy2(self.source, opt_dir / target_name)
            if not self.entrypoint:
                self.entrypoint = target_name

        # 2. Run optional environment preparation hook (--prepare-cmd, e.g. venv/pip, npm ci)
        if self.prepare_cmd:
            formatted_cmd = self.prepare_cmd.format(opt_dir=str(opt_dir), pkg_name=self.pkg_name)
            print(f"      Executing runtime prepare_cmd: {formatted_cmd}")
            subprocess.run(formatted_cmd, shell=True, cwd=opt_dir, check=True)

        # 3. Relocate any hardcoded build-staging paths inside /opt/<pkg_name>
        self._relocate_staged_paths(opt_dir, f"/opt/{self.pkg_name}")

        # 4. Resolve entrypoint if not explicitly set
        if not self.entrypoint:
            self.entrypoint = self._infer_runtime_entrypoint(opt_dir)

        # 5. Resolve runtime_cmd and default_depends if not explicitly set
        entry_ext = Path(self.entrypoint).suffix.lower() if self.entrypoint else ""
        if not self.runtime_cmd:
            if (opt_dir / "venv" / "bin" / "python3").exists():
                self.runtime_cmd = f"/opt/{self.pkg_name}/venv/bin/python3"
                self.default_depends = ["python3"]
            elif entry_ext in RUNTIME_EXT_DEFAULTS:
                self.runtime_cmd, self.default_depends = RUNTIME_EXT_DEFAULTS[entry_ext]
            else:
                # Inspect shebang of entrypoint
                shebang_cmd, shebang_deps = self._infer_runtime_from_shebang(opt_dir / (self.entrypoint or ""))
                self.runtime_cmd = shebang_cmd
                self.default_depends = shebang_deps
        elif not self.default_depends:
            if entry_ext in RUNTIME_EXT_DEFAULTS:
                _, self.default_depends = RUNTIME_EXT_DEFAULTS[entry_ext]
            elif "python" in self.runtime_cmd:
                self.default_depends = ["python3"]
            elif "java" in self.runtime_cmd:
                self.default_depends = ["default-jre | openjdk-21-jre | openjdk-17-jre | openjdk-11-jre"]
            elif "node" in self.runtime_cmd:
                self.default_depends = ["nodejs"]

        # 6. Auto-detect Architecture: scan /opt/<pkg_name> for any ELF binaries/shared objects
        if self.arch == "auto":
            detected_arch = "all"
            for f in opt_dir.rglob("*"):
                if is_elf_file(f):
                    detected_arch = detect_elf_arch(f)
                    if detected_arch != "all":
                        break
            self.arch = detected_arch

        # 7. Generate /usr/bin/<pkg_name> launcher wrapper
        wrapper_lines = ["#!/bin/sh"]
        for env_pair in self.env_vars:
            wrapper_lines.append(f"export {env_pair}")
        if self.entrypoint:
            target_entry = f"/opt/{self.pkg_name}/{self.entrypoint.lstrip('/')}"
            if self.runtime_cmd:
                wrapper_lines.append(f"exec {self.runtime_cmd} {target_entry} \"$@\"")
            else:
                wrapper_lines.append(f"exec {target_entry} \"$@\"")
        else:
            wrapper_lines.append(f"exec {self.runtime_cmd} \"$@\"")

        launcher = bin_dir / self.pkg_name
        launcher.write_text("\n".join(wrapper_lines) + "\n", encoding="utf-8")
        launcher.chmod(0o755)

    def _infer_runtime_entrypoint(self, opt_dir: Path) -> str:
        """Heuristically locate the main file inside /opt/<pkg_name> when --entrypoint is omitted."""
        # Check package.json "bin" or "main" if present
        pkg_json = opt_dir / "package.json"
        if pkg_json.is_file():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                if isinstance(data.get("bin"), str):
                    return data["bin"].lstrip("./")
                if isinstance(data.get("bin"), dict) and data["bin"]:
                    return next(iter(data["bin"].values())).lstrip("./")
                if isinstance(data.get("main"), str):
                    return data["main"].lstrip("./")
            except Exception:
                pass

        for ext in (".jar", ".py", ".js", ".mjs", ".rb", ".php", ".pl", ".dll"):
            for stem in (self.pkg_name, "main", "index", "app", "cli"):
                cand = opt_dir / f"{stem}{ext}"
                if cand.is_file():
                    return cand.name
            matches = [f for f in opt_dir.glob(f"*{ext}") if f.is_file() and f.name != "setup.py"]
            if matches:
                return matches[0].name
        return "main"

    def _infer_runtime_from_shebang(self, entry_path: Path) -> tuple[str, list[str]]:
        if entry_path.is_file():
            try:
                first_line = entry_path.read_text(encoding="utf-8", errors="ignore").splitlines()[0].lower()
                if "node" in first_line:
                    return "node", ["nodejs"]
                if "python" in first_line:
                    return "python3", ["python3"]
                if "ruby" in first_line:
                    return "ruby", ["ruby"]
                if "perl" in first_line:
                    return "perl", ["perl"]
                if "php" in first_line:
                    return "php", ["php-cli"]
            except Exception:
                pass
        return "sh", ["bash", "coreutils"]

    def _relocate_staged_paths(self, staged_root: Path, target_prefix: str):
        """Rewrite hardcoded build staging paths inside scripts/configs (venv, binstubs, etc.) and strip .pyc."""
        staging_bytes = str(staged_root).encode("utf-8")
        target_bytes = target_prefix.encode("utf-8")

        for item in staged_root.rglob("*"):
            if item.is_symlink() or not item.is_file():
                continue
            if item.suffix == ".pyc":
                try:
                    item.unlink()
                except Exception:
                    pass
                continue
            if is_elf_file(item) or item.stat().st_size > 2 * 1024 * 1024:
                continue
            try:
                raw = item.read_bytes()
                if staging_bytes in raw:
                    item.write_bytes(raw.replace(staging_bytes, target_bytes))
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # 4 & 5. AppImage & Archive Handlers (appimage, archive)
    # -----------------------------------------------------------------------
    def _handle_appimage(self):
        """Extract AppImage to /opt/<pkg_name> and extract desktop & icon assets."""
        print("      Extracting AppImage (--appimage-extract, no FUSE needed)...")
        extract_dir = self.work_dir / "squashfs-root"
        self.source.chmod(self.source.stat().st_mode | 0o111)

        try:
            cmd = [str(self.source), "--appimage-extract"]
            subprocess.run(cmd, cwd=self.work_dir, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.SubprocessError as e:
            raise RuntimeError(f"AppImage extraction failed: {e}")

        if not extract_dir.exists():
            raise FileNotFoundError(f"squashfs-root not found in {self.work_dir}")

        self._process_extracted_app_root(extract_dir, is_appimage=True)

    def _handle_archive(self):
        """Extract tar or zip archive (preserving permissions & symlinks) and locate application tree."""
        print(f"      Unpacking archive: {self.source.name} ...")
        extract_dir = self.work_dir / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)

        if self.source.name.lower().endswith(".zip"):
            self._extract_zip_preserving_modes(self.source, extract_dir)
        else:
            with tarfile.open(self.source, "r:*") as tar:
                safe_members = [
                    m for m in tar.getmembers()
                    if str((extract_dir / m.name).resolve()).startswith(str(extract_dir.resolve()))
                ]
                try:
                    tar.extractall(extract_dir, members=safe_members, filter="fully_trusted")
                except TypeError:
                    tar.extractall(extract_dir, members=safe_members)

        app_root = extract_dir
        asars = list(extract_dir.glob("**/resources/app.asar"))
        if asars:
            app_root = asars[0].parent.parent
        else:
            subdirs = [d for d in extract_dir.iterdir() if d.is_dir()]
            files = [f for f in extract_dir.iterdir() if f.is_file()]
            if len(subdirs) == 1 and not files:
                app_root = subdirs[0]

        print(f"      Located application root: {app_root}")
        self._process_extracted_app_root(app_root, is_appimage=False)

    def _extract_zip_preserving_modes(self, zip_path: Path, extract_dir: Path):
        """Extract a ZIP archive while preserving Unix executable permissions and symlinks."""
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                target_path = (extract_dir / info.filename).resolve()
                if not str(target_path).startswith(str(extract_dir.resolve())):
                    continue
                unix_mode = info.external_attr >> 16
                if stat.S_ISLNK(unix_mode):
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    link_target = zf.read(info).decode("utf-8", errors="replace")
                    if target_path.exists() or target_path.is_symlink():
                        target_path.unlink()
                    target_path.symlink_to(link_target)
                else:
                    zf.extract(info, extract_dir)
                    if unix_mode and target_path.is_file():
                        target_path.chmod(unix_mode & 0o777)

    def _process_extracted_app_root(self, app_root: Path, is_appimage: bool = False):
        """Common logic for processing extracted AppImage or Archive directory trees."""
        desktop_exec_hint = None

        # 1. Check for Electron app.asar
        asar_path = app_root / "resources" / "app.asar"
        if asar_path.exists():
            if not getattr(self.args, "no_desktop", False):
                self.is_gui = True
            try:
                asar = AsarArchive(asar_path)
                pkg_json = json.loads(asar.read_file("package.json").decode("utf-8"))
                print("      Parsed embedded package.json from app.asar")
                if not self.args.name and not self.recipe_data.get("name") and pkg_json.get("name"):
                    self.pkg_name = sanitize_package_name(pkg_json["name"])
                if not self.desktop_name and pkg_json.get("productName"):
                    self.desktop_name = pkg_json["productName"]
                if not self.args.version and not detect_version_from_filename(self.source.name) and pkg_json.get("version"):
                    self.version = sanitize_version(pkg_json["version"])
                if not self.args.description and not self.recipe_data.get("description") and pkg_json.get("description"):
                    self.summary = pkg_json["description"]
                if not self.args.homepage and not self.recipe_data.get("homepage") and pkg_json.get("homepage"):
                    self.homepage = pkg_json["homepage"]

                if not self.icon_path:
                    icon_in_asar = asar.find_file("icon.png") or asar.find_file("trayTemplate@2x.png")
                    if icon_in_asar:
                        icon_bytes = asar.read_file(icon_in_asar)
                        temp_icon = self.work_dir / f"{self.pkg_name}.png"
                        temp_icon.write_bytes(icon_bytes)
                        self.icon_path = temp_icon
            except Exception as e:
                print(f"      Note: Could not parse app.asar: {e}")

        # 2. Check for embedded .desktop files
        desktops = list(app_root.glob("*.desktop")) or list(app_root.glob("usr/share/applications/*.desktop"))
        if desktops:
            if not getattr(self.args, "no_desktop", False):
                self.is_gui = True
            try:
                dt = desktops[0].read_text(encoding="utf-8", errors="replace")
                m_name = re.search(r"^Name=(.+)$", dt, re.MULTILINE)
                if m_name and not self.desktop_name:
                    self.desktop_name = m_name.group(1).strip()
                m_comment = re.search(r"^Comment=(.+)$", dt, re.MULTILINE)
                if m_comment and not self.args.description and not self.recipe_data.get("description"):
                    self.summary = m_comment.group(1).strip()
                m_cat = re.search(r"^Categories=(.+)$", dt, re.MULTILINE)
                if m_cat and not self.args.category and not self.recipe_data.get("category"):
                    self.desktop_category = m_cat.group(1).strip()
                    if not self.desktop_category.endswith(";"):
                        self.desktop_category += ";"
                m_ver = re.search(r"^(?:X-AppImage-Version|Version)=(.+)$", dt, re.MULTILINE)
                if m_ver and not self.args.version and self.version == "1.0.0":
                    ver_cand = m_ver.group(1).strip()
                    if "X-AppImage-Version=" in dt or ver_cand != "1.0":
                        self.version = sanitize_version(ver_cand)
                m_exec = re.search(r"^Exec=([^\s]+)", dt, re.MULTILINE)
                if m_exec:
                    desktop_exec_hint = Path(m_exec.group(1).strip('"')).name
                m_icon = re.search(r"^Icon=(.+)$", dt, re.MULTILINE)
                if m_icon and not self.icon_path:
                    icon_stem = m_icon.group(1).strip()
                    for cand in list(app_root.glob(f"{icon_stem}.*")) + list(app_root.glob(f"**/{icon_stem}.*")):
                        if cand.is_file() and cand.suffix.lower() in [".png", ".svg"]:
                            self.icon_path = cand
                            break
            except Exception as e:
                print(f"      Note: Could not parse .desktop: {e}")

        # 3. Locate icon (.DirIcon, *.png, *.svg) if not yet found
        if not self.icon_path:
            dir_icon = app_root / ".DirIcon"
            if dir_icon.exists() and dir_icon.resolve().is_file():
                self.icon_path = dir_icon.resolve()
            else:
                icons = [f for f in (list(app_root.glob("*.png")) + list(app_root.glob("*.svg"))) if f.is_file()]
                if not icons:
                    icons = [f for f in app_root.glob("usr/share/icons/**/*.*") if f.is_file() and f.suffix.lower() in (".png", ".svg")]
                if icons:
                    self.icon_path = icons[0]

        # 4. Copy payload to /opt/<pkg_name>
        opt_dir = self.staging_dir / "opt" / self.pkg_name
        opt_dir.mkdir(parents=True, exist_ok=True)

        print(f"      Installing application tree into /opt/{self.pkg_name} ...")
        for item in app_root.iterdir():
            dest = opt_dir / item.name
            if item.is_symlink():
                dest.symlink_to(os.readlink(item))
            elif item.is_dir():
                shutil.copytree(item, dest, symlinks=True)
            else:
                shutil.copy2(item, dest)

        # 5. Locate main executable (Ensuring candidate is a file, not a directory!)
        exec_cand = None
        candidates = []
        if self.entrypoint:
            candidates.append(opt_dir / self.entrypoint)
        if is_appimage:
            candidates.append(opt_dir / "AppRun")
        if desktop_exec_hint:
            candidates.append(opt_dir / desktop_exec_hint)
            candidates.append(opt_dir / "usr" / "bin" / desktop_exec_hint)
        candidates.extend([
            opt_dir / self.pkg_name,
            opt_dir / "AppRun",
            opt_dir / "usr" / "bin" / self.pkg_name,
        ])

        for cand in candidates:
            if cand.is_file():
                exec_cand = cand
                break

        if not exec_cand:
            execs = [
                f for f in opt_dir.iterdir()
                if f.is_file() and os.access(f, os.X_OK) and not f.name.endswith(".so") and ".so." not in f.name
            ]
            if not execs and (opt_dir / "usr" / "bin").is_dir():
                execs = [f for f in (opt_dir / "usr" / "bin").iterdir() if f.is_file() and os.access(f, os.X_OK)]
            exec_cand = execs[0] if execs else (opt_dir / "AppRun")

        if exec_cand.is_file():
            exec_cand.chmod(0o755)
        rel_entrypoint = exec_cand.relative_to(opt_dir)
        self.entrypoint = str(rel_entrypoint)

        if self.arch == "auto":
            detected_arch = detect_elf_arch(exec_cand)
            if detected_arch == "all":
                for elf_cand in list(opt_dir.iterdir()) + list(opt_dir.glob("usr/bin/*")) + list(opt_dir.rglob("*.so*")):
                    if is_elf_file(elf_cand):
                        detected_arch = detect_elf_arch(elf_cand)
                        if detected_arch != "all":
                            break
            self.arch = detected_arch if detected_arch != "all" else "amd64"

        # 6. Create symlink in /usr/bin/<pkg_name>
        bin_dir = self.staging_dir / "usr" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / self.pkg_name).symlink_to(f"/opt/{self.pkg_name}/{rel_entrypoint}")

        # 7. Check chrome-sandbox / Electron requirements
        if (opt_dir / "chrome-sandbox").exists():
            self.has_chrome_sandbox = True
        if self.has_chrome_sandbox or self.apparmor_needed or asar_path.exists():
            self.apparmor_needed = True

        # 8. Determine dependencies
        if self.is_gui or is_appimage or asar_path.exists():
            self.default_depends = [
                "libgtk-3-0 | libgtk-3-0t64 | libgtk-4-1",
                "libnotify4",
                "libnss3",
                "xdg-utils",
                "libatspi2.0-0 | libatspi2.0-0t64",
                "libdrm2",
                "libgbm1",
                "libasound2 | libasound2t64",
                "libc6 (>= 2.31)",
            ]
        else:
            bundled_libs = {f.name for f in opt_dir.rglob("*.so*")}
            self.default_depends = detect_elf_needed_deps(exec_cand, bundled_libs=bundled_libs)

    # -----------------------------------------------------------------------
    # Systemd, Desktop, Icon, and AppArmor Handlers
    # -----------------------------------------------------------------------
    def _handle_systemd_service(self):
        if not self.systemd_service_path:
            return
        systemd_dir = self.staging_dir / "lib" / "systemd" / "system"
        systemd_dir.mkdir(parents=True, exist_ok=True)
        target_unit = systemd_dir / f"{self.pkg_name}.service"
        shutil.copy2(self.systemd_service_path, target_unit)
        target_unit.chmod(0o644)
        print(f"      Installed systemd service unit: /lib/systemd/system/{self.pkg_name}.service")

    def _handle_desktop_and_icon(self):
        if self.is_gui:
            display_name = self.desktop_name or self.pkg_name.replace("-", " ").title()
            apps_dir = self.staging_dir / "usr" / "share" / "applications"
            apps_dir.mkdir(parents=True, exist_ok=True)

            single_line_comment = (self.summary or "").splitlines()[0].strip() if self.summary else display_name
            desktop_file = apps_dir / f"{self.pkg_name}.desktop"
            content = f"""[Desktop Entry]
Name={display_name}
Comment={single_line_comment}
Exec=/usr/bin/{self.pkg_name} %U
Icon={self.pkg_name}
Terminal=false
Type=Application
Categories={self.desktop_category if self.desktop_category.endswith(';') else self.desktop_category + ';'}
StartupNotify=true
StartupWMClass={self.pkg_name}
"""
            desktop_file.write_text(content, encoding="utf-8")

            if self.icon_path and self.icon_path.exists():
                ext = detect_icon_extension(self.icon_path)
                try:
                    icon_data = self.icon_path.resolve().read_bytes()

                    pixmaps_dir = self.staging_dir / "usr" / "share" / "pixmaps"
                    pixmaps_dir.mkdir(parents=True, exist_ok=True)
                    (pixmaps_dir / f"{self.pkg_name}{ext}").write_bytes(icon_data)

                    if ext == ".svg":
                        theme_dir = self.staging_dir / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps"
                    else:
                        theme_dir = self.staging_dir / "usr" / "share" / "icons" / "hicolor" / "512x512" / "apps"
                    theme_dir.mkdir(parents=True, exist_ok=True)
                    (theme_dir / f"{self.pkg_name}{ext}").write_bytes(icon_data)
                except Exception as e:
                    print(f"      Note: Could not copy icon file: {e}")

        if self.apparmor_needed:
            apparmor_dir = self.staging_dir / "etc" / "apparmor.d"
            apparmor_dir.mkdir(parents=True, exist_ok=True)
            aa_profile = apparmor_dir / self.pkg_name
            aa_content = f"""abi <abi/4.0>,
include <tunables/global>

profile {self.pkg_name} /opt/{self.pkg_name}/** flags=(unconfined) {{
  userns,
  include if exists <local/{self.pkg_name}>
}}
"""
            aa_profile.write_text(aa_content, encoding="utf-8")

    # -----------------------------------------------------------------------
    # Maintainer Scripts & DEBIAN/conffiles
    # -----------------------------------------------------------------------
    def _write_conffiles(self):
        etc_dir = self.staging_dir / "etc"
        if not etc_dir.is_dir():
            return
        conffiles = [
            "/" + str(f.relative_to(self.staging_dir))
            for f in sorted(etc_dir.rglob("*"))
            if f.is_file() and not f.is_symlink()
        ]
        if conffiles:
            debian_dir = self.staging_dir / "DEBIAN"
            debian_dir.mkdir(parents=True, exist_ok=True)
            (debian_dir / "conffiles").write_text("\n".join(conffiles) + "\n", encoding="utf-8")

    def _write_maintainer_scripts(self):
        needs_hooks = (
            self.is_gui
            or self.apparmor_needed
            or self.has_chrome_sandbox
            or bool(self.systemd_service_path)
        )
        if not needs_hooks:
            return

        debian_dir = self.staging_dir / "DEBIAN"
        debian_dir.mkdir(parents=True, exist_ok=True)

        # 0. preinst (smooth upgrade migration from legacy /opt/** AppArmor profiles)
        if self.apparmor_needed:
            preinst_lines = [
                "#!/bin/sh",
                "set -e",
                "case \"$1\" in",
                "    install|upgrade)",
                f"        if [ -f \"/etc/apparmor.d/{self.pkg_name}\" ] && grep -q \"/opt/\\*\\*\" \"/etc/apparmor.d/{self.pkg_name}\" 2>/dev/null; then",
                "            if command -v aa-enabled >/dev/null 2>&1 && aa-enabled --quiet 2>/dev/null; then",
                f"                apparmor_parser -R \"/etc/apparmor.d/{self.pkg_name}\" 2>/dev/null || true",
                "            fi",
                f"            rm -f \"/etc/apparmor.d/{self.pkg_name}\"",
                "        fi",
                "        ;;",
                "esac",
                "exit 0",
            ]
            (debian_dir / "preinst").write_text("\n".join(preinst_lines) + "\n", encoding="utf-8")
            (debian_dir / "preinst").chmod(0o755)

        # 1. postinst
        postinst_lines = [
            "#!/bin/sh",
            "set -e",
            "case \"$1\" in",
            "    configure)",
        ]

        if self.apparmor_needed:
            postinst_lines.extend([
                f"        if [ -f \"/etc/apparmor.d/{self.pkg_name}\" ] && command -v aa-enabled >/dev/null 2>&1 && aa-enabled --quiet 2>/dev/null; then",
                f"            apparmor_parser -r -W -T \"/etc/apparmor.d/{self.pkg_name}\" 2>/dev/null || true",
                "        fi",
            ])

        if self.has_chrome_sandbox:
            postinst_lines.extend([
                f"        if [ -f \"/opt/{self.pkg_name}/chrome-sandbox\" ]; then",
                f"            chown root:root \"/opt/{self.pkg_name}/chrome-sandbox\" 2>/dev/null || true",
                f"            chmod 4755 \"/opt/{self.pkg_name}/chrome-sandbox\" 2>/dev/null || true",
                "        fi",
            ])

        if self.is_gui:
            postinst_lines.extend([
                "        if command -v update-desktop-database >/dev/null 2>&1; then",
                "            update-desktop-database -q /usr/share/applications || true",
                "        fi",
                "        if command -v gtk-update-icon-cache >/dev/null 2>&1; then",
                "            gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true",
                "        fi",
            ])

        if self.systemd_service_path:
            postinst_lines.extend([
                "        if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then",
                "            systemctl daemon-reload >/dev/null 2>&1 || true",
                f"            systemctl enable --now {self.pkg_name}.service >/dev/null 2>&1 || true",
                "        fi",
            ])

        postinst_lines.extend([
            "        ;;",
            "esac",
            "exit 0",
        ])
        (debian_dir / "postinst").write_text("\n".join(postinst_lines) + "\n", encoding="utf-8")
        (debian_dir / "postinst").chmod(0o755)

        # 2. prerm
        if self.apparmor_needed or self.systemd_service_path:
            prerm_lines = [
                "#!/bin/sh",
                "set -e",
                "case \"$1\" in",
                "    remove|purge|deconfigure)",
            ]
            if self.systemd_service_path:
                prerm_lines.extend([
                    "        if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then",
                    f"            systemctl stop {self.pkg_name}.service >/dev/null 2>&1 || true",
                    f"            systemctl disable {self.pkg_name}.service >/dev/null 2>&1 || true",
                    "        fi",
                ])
            if self.apparmor_needed:
                prerm_lines.extend([
                    f"        if [ -f \"/etc/apparmor.d/{self.pkg_name}\" ] && command -v aa-enabled >/dev/null 2>&1 && aa-enabled --quiet 2>/dev/null; then",
                    f"            apparmor_parser -R \"/etc/apparmor.d/{self.pkg_name}\" 2>/dev/null || true",
                    "        fi",
                ])
            prerm_lines.extend([
                "        ;;",
                "esac",
                "exit 0",
            ])
            (debian_dir / "prerm").write_text("\n".join(prerm_lines) + "\n", encoding="utf-8")
            (debian_dir / "prerm").chmod(0o755)

        # 3. postrm
        if self.is_gui or self.systemd_service_path:
            postrm_lines = [
                "#!/bin/sh",
                "set -e",
                "case \"$1\" in",
                "    remove|purge)",
            ]
            if self.is_gui:
                postrm_lines.extend([
                    "        if command -v update-desktop-database >/dev/null 2>&1; then",
                    "            update-desktop-database -q /usr/share/applications || true",
                    "        fi",
                    "        if command -v gtk-update-icon-cache >/dev/null 2>&1; then",
                    "            gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true",
                    "        fi",
                ])
            if self.systemd_service_path:
                postrm_lines.extend([
                    "        if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then",
                    "            systemctl daemon-reload >/dev/null 2>&1 || true",
                    "        fi",
                ])
            postrm_lines.extend([
                "        ;;",
                "esac",
                "exit 0",
            ])
            (debian_dir / "postrm").write_text("\n".join(postrm_lines) + "\n", encoding="utf-8")
            (debian_dir / "postrm").chmod(0o755)

    # -----------------------------------------------------------------------
    # DEBIAN/control, Permissions & Verification
    # -----------------------------------------------------------------------
    def _write_control(self):
        debian_dir = self.staging_dir / "DEBIAN"
        debian_dir.mkdir(parents=True, exist_ok=True)

        merged_deps = list(self.default_depends)
        for cd in self.custom_depends:
            if cd not in merged_deps:
                merged_deps.append(cd)
        depends_str = ", ".join(merged_deps)

        total_kb = max(1, sum(f.stat().st_size for f in self.staging_dir.rglob("*") if f.is_file() and not f.is_symlink()) // 1024)
        formatted_desc = format_control_description(self.summary, self.pkg_name)

        control_lines = [
            f"Package: {self.pkg_name}",
            f"Version: {self.version}",
            f"Section: {self.section}",
            f"Priority: {self.priority}",
            f"Architecture: {self.arch}",
            f"Installed-Size: {total_kb}",
            f"Maintainer: {self.maintainer}",
            f"Homepage: {self.homepage}",
        ]
        if depends_str:
            control_lines.append(f"Depends: {depends_str}")
        control_lines.append(f"Description: {formatted_desc}")

        (debian_dir / "control").write_text("\n".join(control_lines) + "\n", encoding="utf-8")

    def _fix_permissions(self):
        for root, dirs, files in os.walk(self.staging_dir):
            for d in dirs:
                p = Path(root) / d
                if not p.is_symlink():
                    try:
                        p.chmod(0o755)
                    except Exception:
                        pass
            for f in files:
                p = Path(root) / f
                if p.is_symlink():
                    continue
                parent_name = p.parent.name
                if parent_name == "DEBIAN":
                    p.chmod(0o755 if p.name in ("postinst", "prerm", "postrm", "preinst") else 0o644)
                elif parent_name == "bin" or p.name.endswith(".sh") or p.name == "AppRun":
                    p.chmod(0o755)
                else:
                    p.chmod(0o755 if (p.stat().st_mode & 0o111) else 0o644)

    def _verify_staging_symlinks(self):
        bin_dir = self.staging_dir / "usr" / "bin"
        if not bin_dir.is_dir():
            return
        for item in bin_dir.iterdir():
            if item.is_symlink():
                target = os.readlink(item)
                staged_target = (self.staging_dir / target.lstrip("/")) if target.startswith("/") else (item.parent / target).resolve()
                if not staged_target.exists():
                    print(f"[!] Warning: Symlink {item.name} -> {target} does not resolve inside staging root ({staged_target})")

    # -----------------------------------------------------------------------
    # Recipe & Reusable Builder Generation
    # -----------------------------------------------------------------------
    def _save_recipe(self):
        """Save discovered metadata AND runtime hooks into a reusable recipe JSON."""
        recipe_target = getattr(self.args, "save_recipe", None)
        if not recipe_target or isinstance(recipe_target, bool):
            recipe_target = self.output_dir / f"{self.pkg_name}.recipe.json"
        else:
            recipe_target = Path(recipe_target).resolve()

        recipe_target.parent.mkdir(parents=True, exist_ok=True)

        saved_icon_path = None
        if self.icon_path and self.icon_path.exists():
            try:
                resolved_icon = self.icon_path.resolve()
                if self.work_dir and str(resolved_icon).startswith(str(self.work_dir.resolve())):
                    ext = detect_icon_extension(resolved_icon)
                    persistent_icon = recipe_target.parent / f"{self.pkg_name}.icon{ext}"
                    persistent_icon.write_bytes(resolved_icon.read_bytes())
                    saved_icon_path = str(persistent_icon)
                else:
                    saved_icon_path = str(resolved_icon)
            except Exception:
                saved_icon_path = None

        recipe_data = {
            "recipe_version": "1.2",
            "name": self.pkg_name,
            "type": self.pkg_type,
            "arch": self.arch,
            "section": self.section,
            "maintainer": self.maintainer,
            "homepage": self.homepage,
            "description": self.summary,
            "is_gui": self.is_gui,
            "desktop_name": self.desktop_name,
            "category": self.desktop_category,
            "depends": self.custom_depends or self.default_depends,
            "prepare_cmd": self.prepare_cmd,
            "runtime_cmd": self.runtime_cmd,
            "entrypoint": self.entrypoint,
            "env_vars": self.env_vars,
            "apparmor": self.apparmor_needed,
            "systemd_service": str(self.systemd_service_path) if self.systemd_service_path else None,
            "icon_path": saved_icon_path,
            "last_built_version": self.version,
        }
        recipe_target.write_text(json.dumps(recipe_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[✓] Saved reusable packaging recipe: {recipe_target}")

    def _generate_builder_script(self):
        """Generate a standalone executable python builder script for this package."""
        target_script = Path(self.args.generate_builder).resolve()
        embedded_recipe = {
            "name": self.pkg_name,
            "type": self.pkg_type,
            "arch": self.arch,
            "section": self.section,
            "maintainer": self.maintainer,
            "homepage": self.homepage,
            "description": self.summary,
            "is_gui": self.is_gui,
            "desktop_name": self.desktop_name,
            "category": self.desktop_category,
            "depends": self.custom_depends or self.default_depends,
            "prepare_cmd": self.prepare_cmd,
            "runtime_cmd": self.runtime_cmd,
            "entrypoint": self.entrypoint,
            "env_vars": self.env_vars,
            "apparmor": self.apparmor_needed,
            "systemd_service": str(self.systemd_service_path) if self.systemd_service_path else None,
        }
        script_content = f"""#!/usr/bin/env python3
\"\"\"
Dedicated Debian (.deb) Package Builder for {self.pkg_name}
Auto-generated by deb-packager. Reuses discovered recipe settings and runtime hooks.
\"\"\"
import subprocess
import sys
from pathlib import Path

RECIPE = {json.dumps(embedded_recipe, indent=4, ensure_ascii=False)}


def main():
    if len(sys.argv) < 2:
        print("Usage: ./build_{self.pkg_name}_deb.py <path/to/new_source> [output_dir]")
        sys.exit(1)

    new_source = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "."

    make_deb_script = Path("{Path(__file__).resolve()}")
    if not make_deb_script.exists():
        make_deb_script = Path.home() / ".agents" / "skills" / "deb-packager" / "scripts" / "make_deb.py"

    cmd = [
        sys.executable, str(make_deb_script),
        "--source", new_source,
        "--name", RECIPE["name"],
        "--type", RECIPE["type"],
        "--arch", RECIPE["arch"],
        "--output-dir", out_dir,
    ]
    for flag, key in [
        ("--section", "section"),
        ("--maintainer", "maintainer"),
        ("--homepage", "homepage"),
        ("--description", "description"),
        ("--desktop-name", "desktop_name"),
        ("--category", "category"),
        ("--prepare-cmd", "prepare_cmd"),
        ("--runtime-cmd", "runtime_cmd"),
        ("--entrypoint", "entrypoint"),
        ("--systemd-service", "systemd_service"),
    ]:
        if RECIPE.get(key):
            cmd.extend([flag, str(RECIPE[key])])

    for env_pair in RECIPE.get("env_vars") or []:
        cmd.extend(["--env", env_pair])

    if RECIPE.get("depends"):
        cmd.extend(["--depends", ", ".join(RECIPE["depends"])])
    if RECIPE.get("is_gui"):
        cmd.append("--gui")
    else:
        cmd.append("--no-desktop")
    if RECIPE.get("apparmor"):
        cmd.append("--apparmor")

    print(f"Executing: {{' '.join(cmd)}}")
    subprocess.check_call(cmd)


if __name__ == "__main__":
    main()
"""
        target_script.parent.mkdir(parents=True, exist_ok=True)
        target_script.write_text(script_content, encoding="utf-8")
        target_script.chmod(0o755)
        print(f"[✓] Generated dedicated builder script: {target_script}")


def parse_arguments():
    parser = argparse.ArgumentParser(description="Universal Debian (.deb) Package Builder")
    parser.add_argument("--source", "-s", required=True, help="Path to executable, script, AppImage, directory, or archive")
    parser.add_argument("--name", "-n", default=None, help="Debian package name (defaults to inferred name)")
    parser.add_argument("--version", "-v", default=None, help="Package version (inferred from filename or --version probe if omitted)")
    parser.add_argument(
        "--type", "-t",
        choices=["auto", "appimage", "archive", "binary", "shell", "runtime", "python", "java", "nodejs"],
        default="auto",
        help="Package category: appimage, archive, binary, shell, or runtime (python/java/nodejs alias to runtime)",
    )
    parser.add_argument("--arch", "-a", default=None, help="Architecture (amd64, arm64, all, etc. Default: auto)")
    parser.add_argument("--description", "-d", default=None, help="Package short description")
    parser.add_argument("--maintainer", "-m", default=None, help="Package maintainer (Name <email>)")
    parser.add_argument("--depends", help="Comma-separated runtime dependencies")
    parser.add_argument("--output-dir", "-o", default=".", help="Output directory for generated .deb file")
    parser.add_argument("--temp-dir", default=None, help="Base directory for temporary build files")
    parser.add_argument("--section", default=None, help="Debian section (utils, devel, net, etc.)")
    parser.add_argument("--homepage", default=None, help="Project homepage URL")
    parser.add_argument("--gui", action="store_true", help="Force GUI mode (.desktop entry and icon cache integration)")
    parser.add_argument("--no-desktop", action="store_true", help="Disable .desktop entry generation (CLI-only package)")
    parser.add_argument("--desktop-name", help="Display name for Desktop entry (implies --gui)")
    parser.add_argument("--icon", help="Path to .png or .svg icon file (implies --gui)")
    parser.add_argument("--category", help="XDG Desktop Categories (e.g., Development;IDE;)")
    # Unified runtime options
    parser.add_argument("--prepare-cmd", default=None, help="Shell command run inside staged /opt/<name> to build/bundle isolated runtime deps (e.g. venv/pip, npm ci)")
    parser.add_argument("--runtime-cmd", default=None, help="Interpreter/VM command prefix for /usr/bin/<name> wrapper (e.g. 'python3', 'java -Xmx512m -jar', 'node')")
    parser.add_argument("--entrypoint", default=None, help="Relative entrypoint path inside /opt/<name> (e.g. 'main.py', 'app.jar', 'dist/index.js')")
    parser.add_argument("--env", action="append", default=None, help="Environment variable KEY=VALUE to export in launcher (can be specified multiple times)")
    # Legacy aliases kept for backward CLI compatibility
    parser.add_argument("--python-mode", choices=["venv", "system"], default=None, help=argparse.SUPPRESS)
    parser.add_argument("--java-opts", default=None, help=argparse.SUPPRESS)
    # System integration & recipe caching
    parser.add_argument("--systemd-service", default=None, help="Path to systemd .service unit file to bundle and enable")
    parser.add_argument("--apparmor", action="store_true", help="Generate AppArmor sandbox profile for Electron/Chromium")
    parser.add_argument("--keep-build-dir", action="store_true", help="Keep temporary build staging directory")
    parser.add_argument("--recipe", "-r", help="Path to recipe JSON to reuse configuration")
    parser.add_argument("--save-recipe", help="Path to save the generated recipe JSON")
    parser.add_argument("--no-save-recipe", action="store_true", help="Do not write a .recipe.json file automatically")
    parser.add_argument("--generate-builder", help="Path to generate a dedicated standalone builder script")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    builder = DebPackageBuilder(args)
    builder.build()
