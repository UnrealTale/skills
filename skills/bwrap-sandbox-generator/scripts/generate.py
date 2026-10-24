#!/usr/bin/env python3
"""
generate.py — Configuration-Driven Bubblewrap (bwrap) Sandbox Assembler.

Architecture Principles:
  1. Zero hardcoded software categories or shell functions inside this script.
  2. Reads all runtime definitions, software categories, and capability mappings from `catalog.json`.
  3. Dynamically loads and splices standalone minimal-privilege shell preset files from `presets/`.
  4. Supports user-selectable policy choices (HOME_MODE, CWD_MODE, APP_DIR_MODE, ALLOW_NET, ETC_MODE)
     as well as fallback/custom mounts and raw bwrap primitives.
  5. Automatically runs `audit.py` on every generated script before granting executable permissions.
  6. Outputs structured `briefing_data` JSON and references `presets/base/report-template.md` so the
     Agent can render the final Sandbox Security Briefing in the exact language used by the user.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(os.path.abspath(__file__)).parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_CATALOG_PATH = SKILL_ROOT / "catalog.json"

sys.path.insert(0, str(SCRIPT_DIR))
from audit import audit_script  # noqa: E402


def load_catalog(catalog_path: Path) -> Dict[str, Any]:
    if not catalog_path.exists():
        raise FileNotFoundError(f"Catalog configuration file not found: {catalog_path}")
    return json.loads(catalog_path.read_text(encoding="utf-8"))


def read_preset_file(rel_path: str) -> str:
    full_path = SKILL_ROOT / rel_path
    if not full_path.exists():
        raise FileNotFoundError(f"Missing shell preset file: {full_path}")
    return full_path.read_text(encoding="utf-8").rstrip()


def parse_symlink_pairs(items: List[str]) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for item in items:
        if ":" not in item:
            raise ValueError(f"Invalid --symlink format '{item}'. Expected 'TARGET:LINK_PATH'.")
        src, dst = item.split(":", 1)
        pairs.append((src, dst))
    return pairs


def format_bash_array(var_name: str, items: Optional[List[str]], comment_example: str) -> str:
    lines = [f"{var_name}=("]
    if items:
        for item in items:
            lines.append(f'  "{item}"')
    else:
        lines.append(f'  # "{comment_example}"')
    lines.append(")")
    return "\n".join(lines)


def assemble_script(
    catalog: Dict[str, Any],
    app_id: str,
    runtime_id: str,
    category_id: str,
    capabilities: List[str],
    default_target: Optional[List[str]] = None,
    default_net: bool = False,
    etc_mode: str = "compat",
    new_session: bool = True,
    home_mode: str = "isolated",
    home_dir: str = "",
    cwd_mode: str = "none",
    app_dir_mode: str = "ro",
    sandbox_base_dir: str = "${HOME}/.local/share/bwrap-sandbox",
    app_dir_home_name: str = ".sandbox-home",
    wine_prefix: str = "",
    open_files_limit: int = 524288,
    extra_ro_binds: Optional[List[str]] = None,
    extra_rw_binds: Optional[List[str]] = None,
    extra_dev_binds: Optional[List[str]] = None,
    extra_tmpfs_dirs: Optional[List[str]] = None,
    extra_empty_dirs: Optional[List[str]] = None,
    extra_symlinks: Optional[List[Tuple[str, str]]] = None,
    extra_env: Optional[Dict[str, str]] = None,
    extra_unsetenv: Optional[List[str]] = None,
    extra_bwrap_args: Optional[List[str]] = None,
) -> str:
    runtimes_cfg = catalog["runtimes"]
    caps_cfg = catalog["capabilities"]
    cats_cfg = catalog["categories"]
    base_cfg = catalog["base_presets"]

    if runtime_id not in runtimes_cfg:
        raise ValueError(
            f"Unknown runtime '{runtime_id}'. Available in catalog.json: {list(runtimes_cfg.keys())}"
        )

    for cap in capabilities:
        if cap not in caps_cfg:
            raise ValueError(
                f"Unknown capability '{cap}'. Available in catalog.json: {list(caps_cfg.keys())}"
            )

    runtime_meta = runtimes_cfg[runtime_id]
    cat_meta = cats_cfg.get(category_id, {"description": "Custom combination"})

    default_cmd_str = "DEFAULT_TARGET_CMD=()"
    if default_target:
        quoted = " ".join(f'"{arg}"' for arg in default_target)
        default_cmd_str = f"DEFAULT_TARGET_CMD=({quoted})"

    rw_binds_block = format_bash_array("RW_BINDS", extra_rw_binds, "/host/path:/sandbox/path")
    ro_binds_block = format_bash_array("RO_BINDS", extra_ro_binds, "/host/docs:/sandbox/docs")
    dev_binds_block = format_bash_array("DEV_BINDS", extra_dev_binds, "/dev/video0")

    # 1. Header & Configuration
    sections: List[str] = [
        "#!/usr/bin/env bash",
        "# ==============================================================================",
        f"# Bubblewrap (bwrap) Least-Privilege Portable Sandbox Launcher — [{app_id}]",
        f"# Layer 1 Runtime  : {runtime_id} ({runtime_meta['description']})",
        f"# Layer 2 Category : {category_id} ({cat_meta['description']})",
        f"# Capabilities     : {', '.join(capabilities) if capabilities else 'core-only'}",
        f"# Policies         : home={home_mode}, cwd={cwd_mode}, app_dir={app_dir_mode}, net={default_net}, etc={etc_mode}",
        "# ==============================================================================",
        "set -euo pipefail",
        f"OPEN_FILES_LIMIT={open_files_limit}",
        'ulimit -n "$OPEN_FILES_LIMIT" 2>/dev/null || true',
        "",
        "declare -a BWRAP_CMD=(bwrap)",
        "",
        "# ==============================================================================",
        "# Sandbox Configuration (Directly Editable)",
        "# ==============================================================================",
        f'DEFAULT_APP_ID="{app_id}"',
        default_cmd_str,
        "",
        "# Storage & Directory Locations",
        f'SANDBOX_BASE_DIR="{sandbox_base_dir}" # Base directory for isolated HOME (~/.local/share/bwrap-sandbox/<app-id>)',
        f'APP_DIR_HOME_NAME="{app_dir_home_name}"                     # Subdirectory name inside app folder when HOME_MODE="app-dir"',
    ]

    if runtime_id == "wine":
        sections.extend(
            [
                "",
                "# Wine Environment Configuration",
                f'WINE_PREFIX="{wine_prefix}"                                        # Custom WINEPREFIX host path (leave empty for isolated $HOME/.wine)',
            ]
        )

    sections.extend(
        [
            "",
            "# Network & Isolation Policies",
            f'ALLOW_NET={"true" if default_net else "false"}',
            f'HOME_MODE="{home_mode}"            # isolated | cwd | app-dir | custom | ephemeral',
            f'CUSTOM_HOME="{home_dir}"',
            f'CWD_MODE="{cwd_mode}"              # none | ro | rw',
            f'APP_DIR_MODE="{app_dir_mode}"          # ro | rw | none',
            f'ETC_MODE="{etc_mode}"              # compat | minimal',
            f'NEW_SESSION={"true" if new_session else "false"}',
            "VERBOSE=false",
            "",
            '# Custom Mounts: "HOST_PATH[:CONTAINER_PATH]" (Omit container path for same-name mount)',
            rw_binds_block,
            "",
            ro_binds_block,
            "",
            dev_binds_block,
            "",
            'if [[ -n "${_BWRAP_SANDBOX_ACTIVE:-}" ]]; then',
            "  _BWRAP_IS_NESTED=true",
            "else",
            "  _BWRAP_IS_NESTED=false",
            "fi",
            "",
            read_preset_file(base_cfg["helpers"]),
            "",
            read_preset_file(base_cfg["core"]),
            "",
            read_preset_file(caps_cfg["network"]["file"]),
        ]
    )

    # 2. Load selected capability preset .sh files
    for cap_id in capabilities:
        if cap_id == "network":
            continue
        sections.append("")
        sections.append(read_preset_file(caps_cfg[cap_id]["file"]))

    # 3. Load selected runtime preset .sh file & CLI entrypoint preset
    sections.append("")
    sections.append(read_preset_file(runtime_meta["file"]))
    sections.append("")
    sections.append(read_preset_file(base_cfg["entrypoint"]))

    # 4. Execution Pipeline Invocation
    # Note: /tmp, /dev/shm, and runtime $HOME must be mounted BEFORE capability
    # presets so capability submounts (e.g. /tmp/.X11-unix, $HOME/.Xauthority,
    # $HOME/.local/share/fonts, $HOME/.config/MangoHud) are mounted on top of them.
    call_lines: List[str] = [
        "",
        "# ==============================================================================",
        "# Main Sandbox Assembly Pipeline",
        "# ==============================================================================",
        'bwrap_parse_cli_args "$@"',
        "bwrap_init_base",
        "bwrap_setup_root_fs",
        "BWRAP_CMD+=(--tmpfs /tmp --tmpfs /dev/shm)",
        f'{runtime_meta["function"]} "${{REMAINING_ARGS[@]}}"',
        caps_cfg["network"]["function"],
    ]

    for cap_id in capabilities:
        if cap_id == "network":
            continue
        call_lines.append(caps_cfg[cap_id]["function"])

    has_other_extras = any(
        [
            extra_tmpfs_dirs,
            extra_empty_dirs,
            extra_symlinks,
            extra_env,
            extra_unsetenv,
            extra_bwrap_args,
        ]
    )
    if has_other_extras:
        call_lines.append("# Application-specific static extra mounts, primitives, and environment variables")
        for tmp_p in extra_tmpfs_dirs or []:
            call_lines.append(f'BWRAP_CMD+=(--tmpfs "{tmp_p}")')
        for dir_p in extra_empty_dirs or []:
            call_lines.append(f'BWRAP_CMD+=(--dir "{dir_p}")')
        for src, dst in extra_symlinks or []:
            call_lines.append(f'BWRAP_CMD+=(--symlink "{src}" "{dst}")')
        for k, v in (extra_env or {}).items():
            call_lines.append(f'bwrap_setenv "{k}" "{v}"')
        for u_var in extra_unsetenv or []:
            call_lines.append(f'BWRAP_CMD+=(--unsetenv "{u_var}")')
        for raw_arg in extra_bwrap_args or []:
            tokens = " ".join(f'"{t}"' for t in raw_arg.split())
            if tokens:
                call_lines.append(f"BWRAP_CMD+=({tokens})")

    call_lines.extend(
        [
            "bwrap_apply_custom_mounts",
            'bwrap_exec "${TARGET_EXEC_ARGS[@]}"',
            "",
        ]
    )

    sections.extend(call_lines)
    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Configuration-driven bwrap sandbox assembler reading catalog.json and presets/*.sh"
    )
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG_PATH), help="Path to catalog.json")
    parser.add_argument("--list", action="store_true", help="List all runtimes, categories, and capabilities from catalog.json")
    parser.add_argument("--config-json", help="Path to JSON build configuration")
    parser.add_argument(
        "--app-id",
        default="auto",
        help="Application identifier ('auto' dynamically derives <app-id> from the runtime target binary/folder; specify a fixed string for dedicated single-app wrappers)",
    )
    parser.add_argument("--runtime", help="Layer 1 Runtime ID defined in catalog.json")
    parser.add_argument("--category", help="Layer 2 Software Category ID defined in catalog.json")
    parser.add_argument("--caps", default=None, help="Explicit comma-separated capability IDs override")
    parser.add_argument("--add-cap", action="append", default=[], help="Add capability ID on top of category preset")
    parser.add_argument("--drop-cap", action="append", default=[], help="Remove capability ID from category preset")
    parser.add_argument("--target", nargs="*", help="Optional default target command embedded into script")
    parser.add_argument("--default-net", action="store_true", default=None, help="Force enable network by default")
    parser.add_argument("--no-default-net", action="store_true", help="Force disable network by default")
    parser.add_argument("--etc-mode", choices=("compat", "minimal"), default="compat", help="/etc mount mode")
    parser.add_argument(
        "--home-mode",
        choices=("isolated", "cwd", "app-dir", "custom", "ephemeral"),
        default=None,
        help="Sandbox $HOME mapping policy: isolated (~/.local/share/bwrap-sandbox/<app-id>), cwd ($PWD), app-dir (<app_dir>/.sandbox-home), custom (--home-dir), or ephemeral (tmpfs, unmapped)",
    )
    parser.add_argument("--home-dir", default="", help="Custom host directory path for sandbox $HOME when --home-mode=custom")
    parser.add_argument(
        "--cwd-mode",
        choices=("none", "ro", "rw"),
        default=None,
        help="Current working directory ($PWD) mount policy: none, ro (read-only), or rw (read-write)",
    )
    parser.add_argument(
        "--app-dir-mode",
        choices=("ro", "rw", "none"),
        default="ro",
        help="Application binary parent directory mount policy (when outside system paths): ro (default), rw (portable app self-write), or none",
    )
    parser.add_argument("--mount-cwd", action="store_true", default=None, help="Legacy alias for --cwd-mode rw")
    parser.add_argument("--ephemeral", action="store_true", default=None, help="Legacy alias for --home-mode ephemeral")
    parser.add_argument("--ro-bind", action="append", default=[], help="Extra read-only bind path or SRC[:DEST] (User-Approved)")
    parser.add_argument("--bind", action="append", default=[], help="Extra read-write bind path or SRC[:DEST] (User-Approved)")
    parser.add_argument("--dev-bind", action="append", default=[], help="Extra device node bind path or SRC[:DEST] (User-Approved)")
    parser.add_argument("--tmpfs-dir", action="append", default=[], help="Extra tmpfs mount path inside sandbox")
    parser.add_argument("--empty-dir", action="append", default=[], help="Extra empty directory path to create inside sandbox")
    parser.add_argument("--symlink", action="append", default=[], help="Extra symlink in TARGET:LINK_PATH format")
    parser.add_argument("--setenv", action="append", default=[], help="Extra env var KEY=VALUE")
    parser.add_argument("--unsetenv", action="append", default=[], help="Unset environment variable inside sandbox")
    parser.add_argument("--bwrap-arg", action="append", default=[], help="Extra raw bwrap flag/argument")
    parser.add_argument(
        "--sandbox-base-dir",
        default="${HOME}/.local/share/bwrap-sandbox",
        help="Base host directory for per-app isolated HOME subdirectories (defaults to '${HOME}/.local/share/bwrap-sandbox')",
    )
    parser.add_argument(
        "--app-dir-home-name",
        default=".sandbox-home",
        help="Subdirectory name inside application folder when --home-mode=app-dir (defaults to '.sandbox-home')",
    )
    parser.add_argument(
        "--wine-prefix",
        default="",
        help="Custom WINEPREFIX host path when runtime is wine (defaults to empty string, which isolates in $HOME/.wine)",
    )
    parser.add_argument(
        "--open-files-limit",
        type=int,
        default=524288,
        help="ulimit -n open file descriptor limit configured in wrapper script (defaults to 524288)",
    )
    parser.add_argument("-o", "--output", help="Output Bash script path")
    parser.add_argument("--report", help="Target file path where the Agent must write the localized Markdown Sandbox Security Briefing (defaults to <output-stem>-briefing.md)")

    args = parser.parse_args()
    catalog_path = Path(args.catalog)
    catalog = load_catalog(catalog_path)

    if args.list:
        summary = {
            "runtimes": {k: v["description"] for k, v in catalog["runtimes"].items()},
            "categories": {
                k: {
                    "freedesktop_categories": v["freedesktop_categories"],
                    "capabilities": v["capabilities"],
                    "default_net": v["default_net"],
                    "description": v["description"],
                }
                for k, v in catalog["categories"].items()
            },
            "capabilities": {k: v["description"] for k, v in catalog["capabilities"].items()},
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return

    added_caps: List[str] = []
    dropped_caps: List[str] = []

    if args.config_json:
        cfg = json.loads(Path(args.config_json).read_text(encoding="utf-8"))
        app_id = cfg.get("app_id", args.app_id)
        runtime_id = cfg["runtime"]
        category_id = cfg["category"]
        caps = cfg.get("capabilities", list(catalog["categories"][category_id]["capabilities"]))
        default_target = cfg.get("default_target", args.target)
        default_net = cfg.get("default_net", None)
        etc_mode = cfg.get("etc_mode", args.etc_mode)
        home_mode = cfg.get("home_mode", args.home_mode)
        home_dir = cfg.get("home_dir", args.home_dir)
        cwd_mode = cfg.get("cwd_mode", args.cwd_mode)
        app_dir_mode = cfg.get("app_dir_mode", args.app_dir_mode)
        mount_cwd = cfg.get("mount_cwd", None)
        ephemeral_default = cfg.get("ephemeral", None)
        extra_ro_binds = cfg.get("extra_ro_binds", args.ro_bind)
        extra_rw_binds = cfg.get("extra_rw_binds", args.bind)
        extra_dev_binds = cfg.get("extra_dev_binds", args.dev_bind)
        extra_tmpfs_dirs = cfg.get("extra_tmpfs_dirs", args.tmpfs_dir)
        extra_empty_dirs = cfg.get("extra_empty_dirs", args.empty_dir)
        extra_symlinks = parse_symlink_pairs(cfg.get("extra_symlinks", args.symlink))
        extra_env = cfg.get("extra_env", {})
        extra_unsetenv = cfg.get("extra_unsetenv", args.unsetenv)
        extra_bwrap_args = cfg.get("extra_bwrap_args", args.bwrap_arg)
        output_path = cfg.get("output", args.output)
        report_path = cfg.get("report", args.report)
        sandbox_base_dir = cfg.get("sandbox_base_dir", args.sandbox_base_dir)
        app_dir_home_name = cfg.get("app_dir_home_name", args.app_dir_home_name)
        wine_prefix = cfg.get("wine_prefix", args.wine_prefix)
        open_files_limit = int(cfg.get("open_files_limit", args.open_files_limit))
    else:
        if not args.runtime or not args.category or not args.output:
            parser.error("--runtime, --category, and -o/--output are required (or use --list / --config-json).")
        app_id = args.app_id
        runtime_id = args.runtime
        category_id = args.category
        if category_id not in catalog["categories"]:
            parser.error(f"Unknown --category '{category_id}'. Run with --list to see valid categories.")
        if args.caps is not None:
            caps = [c.strip() for c in args.caps.split(",") if c.strip()]
        else:
            caps = list(catalog["categories"][category_id]["capabilities"])
        added_caps = list(args.add_cap)
        dropped_caps = list(args.drop_cap)
        for c in added_caps:
            if c not in caps:
                caps.append(c)
        caps = [c for c in caps if c not in set(dropped_caps)]
        default_target = args.target
        default_net = False if args.no_default_net else (True if args.default_net else None)
        etc_mode = args.etc_mode
        home_mode = args.home_mode
        home_dir = args.home_dir
        cwd_mode = args.cwd_mode
        app_dir_mode = args.app_dir_mode
        mount_cwd = args.mount_cwd
        ephemeral_default = args.ephemeral
        extra_ro_binds = args.ro_bind
        extra_rw_binds = args.bind
        extra_dev_binds = args.dev_bind
        extra_tmpfs_dirs = args.tmpfs_dir
        extra_empty_dirs = args.empty_dir
        extra_symlinks = parse_symlink_pairs(args.symlink)
        extra_env = {}
        for item in args.setenv:
            if "=" in item:
                k, v = item.split("=", 1)
                extra_env[k] = v
        extra_unsetenv = args.unsetenv
        extra_bwrap_args = args.bwrap_arg
        output_path = args.output
        report_path = args.report
        sandbox_base_dir = args.sandbox_base_dir
        app_dir_home_name = args.app_dir_home_name
        wine_prefix = args.wine_prefix
        open_files_limit = args.open_files_limit

    cat_meta = catalog["categories"][category_id]
    resolved_net = bool(cat_meta.get("default_net", False)) or ("network" in caps) if default_net is None else default_net

    # Resolve HOME_MODE
    if home_mode is not None:
        resolved_home_mode = home_mode
    elif ephemeral_default is True:
        resolved_home_mode = "ephemeral"
    elif home_dir:
        resolved_home_mode = "custom"
    elif category_id.startswith("cli-"):
        resolved_home_mode = "ephemeral"
    else:
        resolved_home_mode = "isolated"

    if resolved_home_mode == "custom" and not home_dir:
        parser.error("--home-dir <PATH> is required when --home-mode=custom.")

    # Resolve CWD_MODE
    if cwd_mode is not None:
        resolved_cwd_mode = cwd_mode
    elif mount_cwd is True:
        resolved_cwd_mode = "rw"
    elif mount_cwd is False:
        resolved_cwd_mode = "none"
    elif bool(cat_meta.get("default_cwd", False)):
        resolved_cwd_mode = "rw"
    else:
        resolved_cwd_mode = "none"

    resolved_new_session = bool(cat_meta.get("new_session", True))

    script_content = assemble_script(
        catalog=catalog,
        app_id=app_id,
        runtime_id=runtime_id,
        category_id=category_id,
        capabilities=caps,
        default_target=default_target,
        default_net=resolved_net,
        etc_mode=etc_mode,
        new_session=resolved_new_session,
        home_mode=resolved_home_mode,
        home_dir=home_dir,
        cwd_mode=resolved_cwd_mode,
        app_dir_mode=app_dir_mode,
        sandbox_base_dir=sandbox_base_dir,
        app_dir_home_name=app_dir_home_name,
        wine_prefix=wine_prefix,
        open_files_limit=open_files_limit,
        extra_ro_binds=extra_ro_binds,
        extra_rw_binds=extra_rw_binds,
        extra_dev_binds=extra_dev_binds,
        extra_tmpfs_dirs=extra_tmpfs_dirs,
        extra_empty_dirs=extra_empty_dirs,
        extra_symlinks=extra_symlinks,
        extra_env=extra_env,
        extra_unsetenv=extra_unsetenv,
        extra_bwrap_args=extra_bwrap_args,
    )

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(script_content, encoding="utf-8")

    # Mandatory Built-in Audit Gatekeeper
    audit_res = audit_script(out_file, catalog_path)
    if audit_res["status"] == "FAIL":
        os.chmod(out_file, 0o600)
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": "Generated script failed mandatory security/portability audit! Executable bit revoked.",
                    "audit": audit_res,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    os.chmod(out_file, 0o755)

    template_rel_path = catalog["base_presets"].get("report_template", "presets/base/report-template.md")
    expected_report = Path(report_path) if report_path else out_file.with_name(f"{out_file.stem}-briefing.md")
    print(
        json.dumps(
            {
                "status": "ok",
                "output_script": os.path.abspath(out_file),
                "expected_report_file": os.path.abspath(expected_report),
                "report_template_path": os.path.abspath(SKILL_ROOT / template_rel_path),
                "localization_notice": (
                    "MANDATORY ACTION REQUIRED: (1) Read `report_template_path`, (2) render the complete "
                    "Sandbox Security Briefing in the EXACT language used by the user in their prompt "
                    "(e.g., Simplified Chinese if the user asked in Chinese; English if the user asked in English), "
                    "AND (3) WRITE the localized Markdown report to disk at `expected_report_file` before finishing!"
                ),
                "briefing_data": {
                    "app_id": app_id,
                    "output_script": os.path.abspath(out_file),
                    "expected_report_file": os.path.abspath(expected_report),
                    "default_target": default_target or [],
                    "layer1_runtime": {
                        "id": runtime_id,
                        "description": catalog["runtimes"][runtime_id]["description"],
                    },
                    "user_policies": {
                        "app_id_mode": "dynamic-runtime (auto)" if app_id == "auto" else f"fixed ({app_id})",
                        "home_mode": resolved_home_mode,
                        "home_dir": home_dir if resolved_home_mode == "custom" else (
                            f"{sandbox_base_dir}/{app_id if app_id != 'auto' else '<app-id>'}" if resolved_home_mode == "isolated" else (
                                "$PWD" if resolved_home_mode == "cwd" else (
                                    f"<app_dir>/{app_dir_home_name}" if resolved_home_mode == "app-dir" else "tmpfs (unmapped in-memory)"
                                )
                            )
                        ),
                        "cwd_mode": resolved_cwd_mode,
                        "app_dir_mode": app_dir_mode,
                        "default_net": resolved_net,
                        "etc_mode": etc_mode,
                    },
                    "layer2_category": {
                        "id": category_id,
                        "freedesktop_categories": cat_meta.get("freedesktop_categories", []),
                        "description": cat_meta.get("description", ""),
                        "enabled_capabilities": [
                            {
                                "id": c,
                                "description": catalog["capabilities"][c]["description"],
                            }
                            for c in caps
                        ],
                        "added_capabilities": added_caps,
                        "dropped_capabilities": dropped_caps,
                    },
                    "non_preset_additions": {
                        "ro_binds": extra_ro_binds,
                        "rw_binds": extra_rw_binds,
                        "dev_binds": extra_dev_binds,
                        "tmpfs_dirs": extra_tmpfs_dirs,
                        "empty_dirs": extra_empty_dirs,
                        "symlinks": [f"{s}:{d}" for s, d in extra_symlinks],
                        "setenv": extra_env,
                        "unsetenv": extra_unsetenv,
                        "bwrap_args": extra_bwrap_args,
                    },
                    "audit": audit_res,
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
