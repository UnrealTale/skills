#!/usr/bin/env python3
"""generate.py — Pure Configuration-Driven Bubblewrap (bwrap) Sandbox Assembler."""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(os.path.abspath(__file__)).parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_CATALOG_PATH = SKILL_ROOT / "catalog.json"
CONFIG_TEMPLATE_PATH = SKILL_ROOT / "presets" / "base" / "config-template.json"

sys.path.insert(0, str(SCRIPT_DIR))
from audit import audit_script  # noqa: E402


def strip_json_comments(text: str) -> str:
    """Strips //, /* */, and # comments from JSON while strictly preserving strings."""
    pattern = r'("(?:\\.|[^"\\])*")|(/\*.*?\*/|//[^\r\n]*|#[^\r\n]*)'
    return re.sub(pattern, lambda m: m.group(1) if m.group(1) else "", text, flags=re.DOTALL)


def parse_json_config(content: str) -> Dict[str, Any]:
    """Parses JSON or JSONC (JSON with comments) text into a dictionary."""
    cleaned = strip_json_comments(content).strip()
    return json.loads(cleaned) if cleaned else {}


def load_catalog(catalog_path: Path) -> Dict[str, Any]:
    return json.loads(catalog_path.read_text(encoding="utf-8"))


def load_config_template() -> Dict[str, Any]:
    return parse_json_config(CONFIG_TEMPLATE_PATH.read_text(encoding="utf-8")) if CONFIG_TEMPLATE_PATH.exists() else {}


def read_preset(rel_path: str) -> str:
    return (SKILL_ROOT / rel_path).read_text(encoding="utf-8").rstrip()


def format_array(items: Optional[List[str]], example: str) -> str:
    return "\n".join(f'  "{x}"' for x in items) if items else f'  # "{example}"'


def resolve_config(cfg: Dict[str, Any], catalog: Dict[str, Any]) -> Dict[str, Any]:
    """Resolves and normalizes configuration defaults, aliases, and category fallbacks."""
    cfg["app_id"] = "sandbox-app" if cfg.get("app_id") in (None, "", "auto") else cfg["app_id"]
    runtime_id = cfg.get("runtime_id") or cfg.get("runtime")
    category_id = cfg.get("category_id") or cfg.get("category")
    if not runtime_id or not category_id:
        raise ValueError("Both 'runtime' and 'category' are required in configuration.")
    cfg["runtime"], cfg["category"] = runtime_id, category_id

    cat_meta = catalog["categories"][category_id]

    # Capabilities resolution
    caps = cfg.get("capabilities") or cfg.get("caps")
    if caps is None:
        caps = list(cat_meta.get("capabilities", []))
    for c in cfg.get("add_caps", []):
        if c not in caps:
            caps.append(c)
    cfg["capabilities"] = [c for c in caps if c not in set(cfg.get("drop_caps", []))]

    # Network policy resolution
    if cfg.get("default_net") is None:
        cfg["default_net"] = bool(cat_meta.get("default_net", False)) or ("network" in cfg["capabilities"])
    else:
        cfg["default_net"] = bool(cfg["default_net"])

    # Home mode resolution
    if not cfg.get("home_mode"):
        if cfg.get("ephemeral") is True or category_id.startswith("cli-"):
            cfg["home_mode"] = "ephemeral"
        elif cfg.get("home_dir"):
            cfg["home_mode"] = "custom"
        else:
            cfg["home_mode"] = "isolated"

    # CWD mode resolution
    if not cfg.get("cwd_mode"):
        if cfg.get("mount_cwd") is True or bool(cat_meta.get("default_cwd", False)):
            cfg["cwd_mode"] = "rw"
        else:
            cfg["cwd_mode"] = "none"

    # Normalize list/array aliases (prefer explicit overrides if passed)
    cfg["target"] = cfg.get("default_target") or cfg.get("target") or []
    cfg["rw_binds"] = cfg.get("extra_rw_binds") or cfg.get("rw_binds") or []
    cfg["ro_binds"] = cfg.get("extra_ro_binds") or cfg.get("ro_binds") or []
    cfg["dev_binds"] = cfg.get("extra_dev_binds") or cfg.get("dev_binds") or []
    return cfg


def assemble_script(catalog: Dict[str, Any], **kwargs: Any) -> str:
    """Assembles a runnable bwrap bash launcher by substituting values into launcher-template.sh."""
    cfg = load_config_template()
    cfg.update(kwargs)
    cfg = resolve_config(cfg, catalog)

    runtimes_cfg = catalog["runtimes"]
    caps_cfg = catalog["capabilities"]
    cats_cfg = catalog["categories"]
    base_cfg = catalog["base_presets"]

    runtime_meta = runtimes_cfg[cfg["runtime"]]
    cat_meta = cats_cfg[cfg["category"]]
    caps = cfg["capabilities"]

    target_cmd = f'DEFAULT_TARGET_CMD=({" ".join(f"\"{a}\"" for a in cfg["target"])})' if cfg["target"] else "DEFAULT_TARGET_CMD=()"
    wine_block = f'\n# Wine Environment Configuration\nWINE_PREFIX="{cfg.get("wine_prefix", "")}"\n' if cfg["runtime"] == "wine" else ""

    cap_presets = [read_preset(caps_cfg[c]["file"]) for c in caps if c != "network"]
    cap_calls = [caps_cfg["network"]["function"]] + [caps_cfg[c]["function"] for c in caps if c != "network"]

    # Extra primitives formatting
    extra_lines = [f'BWRAP_CMD+=(--tmpfs "{p}")' for p in cfg.get("tmpfs_dirs", [])]
    extra_lines += [f'BWRAP_CMD+=(--dir "{p}")' for p in cfg.get("empty_dirs", [])]
    for s in cfg.get("symlinks", []):
        src, dst = s if isinstance(s, (list, tuple)) else s.split(":", 1)
        extra_lines.append(f'BWRAP_CMD+=(--symlink "{src}" "{dst}")')
    for k, v in cfg.get("env", {}).items():
        extra_lines.append(f'bwrap_setenv "{k}" "{v}"')
    for u in cfg.get("unsetenv", []):
        extra_lines.append(f'BWRAP_CMD+=(--unsetenv "{u}")')
    for arg in cfg.get("bwrap_args", []):
        tokens = " ".join(f'"{t}"' for t in arg.split())
        if tokens:
            extra_lines.append(f"BWRAP_CMD+=({tokens})")
    extra_block = ("# Application-specific extra mounts, primitives, and environment variables\n" + "\n".join(extra_lines)) if extra_lines else ""

    replacements = {
        "APP_ID": cfg["app_id"],
        "RUNTIME_ID": cfg["runtime"],
        "RUNTIME_DESC": runtime_meta["description"],
        "CATEGORY_ID": cfg["category"],
        "CATEGORY_DESC": cat_meta.get("description", "Custom combination"),
        "CAPABILITIES_STR": ", ".join(caps) if caps else "core-only",
        "ALLOW_NET": "true" if cfg["default_net"] else "false",
        "HOME_MODE": cfg["home_mode"],
        "CUSTOM_HOME": cfg.get("home_dir", ""),
        "CWD_MODE": cfg["cwd_mode"],
        "APP_DIR_MODE": cfg.get("app_dir_mode", "ro"),
        "ETC_MODE": cfg.get("etc_mode", "compat"),
        "NEW_SESSION": "true" if cfg.get("new_session", True) else "false",
        "OPEN_FILES_LIMIT": str(cfg.get("open_files_limit", 524288)),
        "DEFAULT_TARGET_CMD": target_cmd,
        "SANDBOX_BASE_DIR": cfg.get("sandbox_base_dir", "${HOME}/.local/share/bwrap-sandbox"),
        "APP_DIR_HOME_NAME": cfg.get("app_dir_home_name", ".sandbox-home"),
        "APP_DIR": cfg.get("app_dir", ""),
        "WINE_CONFIG_BLOCK": wine_block,
        "RW_BINDS": format_array(cfg["rw_binds"], "/host/path:/sandbox/path"),
        "RO_BINDS": format_array(cfg["ro_binds"], "/host/docs:/sandbox/docs"),
        "DEV_BINDS": format_array(cfg["dev_binds"], "/dev/video0"),
        "PRESET_HELPERS": read_preset(base_cfg["helpers"]),
        "PRESET_CORE": read_preset(base_cfg["core"]),
        "PRESET_NETWORK": read_preset(caps_cfg["network"]["file"]),
        "PRESET_CAPABILITIES": ("\n\n" + "\n\n".join(cap_presets)) if cap_presets else "",
        "PRESET_RUNTIME": read_preset(runtime_meta["file"]),
        "PRESET_ENTRYPOINT": read_preset(base_cfg["entrypoint"]),
        "RUNTIME_CALL": f'{runtime_meta["function"]} "${{REMAINING_ARGS[@]}}"',
        "CAPABILITY_CALLS": "\n".join(cap_calls),
        "EXTRA_PRIMITIVES": ("\n" + extra_block) if extra_block else "",
    }

    template = read_preset(base_cfg.get("launcher_template", "presets/base/launcher-template.sh"))
    for k, v in replacements.items():
        template = template.replace(f"{{{{{k}}}}}", v)
    return template


def build_briefing_data(cfg: Dict[str, Any], catalog: Dict[str, Any], out_file: Path, audit_res: Dict[str, Any]) -> Dict[str, Any]:
    """Builds structured metadata consumed by presets/base/report-template.md."""
    app_id, r_id, c_id = cfg["app_id"], cfg["runtime"], cfg["category"]
    cat_meta = catalog["categories"][c_id]
    home = cfg["home_mode"]
    base = cfg.get("sandbox_base_dir", "${HOME}/.local/share/bwrap-sandbox")
    home_dir_map = {
        "custom": cfg.get("home_dir", ""),
        "isolated": f"{base}/{app_id}",
        "cwd": "$PWD",
        "app-dir": f"<app_dir>/{cfg.get('app_dir_home_name', '.sandbox-home')}",
        "ephemeral": "tmpfs (unmapped in-memory)",
    }

    return {
        "app_id": app_id,
        "output_script": os.path.abspath(out_file),
        "expected_report_file": os.path.abspath(out_file.with_name(f"{out_file.stem}-briefing.md")),
        "default_target": cfg.get("target", []),
        "layer1_runtime": {"id": r_id, "description": catalog["runtimes"][r_id]["description"]},
        "user_policies": {
            "app_id_mode": "fallback (sandbox-app)" if app_id == "sandbox-app" else f"fixed ({app_id})",
            "home_mode": home,
            "home_dir": home_dir_map.get(home, "tmpfs"),
            "cwd_mode": cfg["cwd_mode"],
            "app_dir_mode": cfg.get("app_dir_mode", "ro"),
            "app_dir": cfg.get("app_dir") or "auto-derive",
            "default_net": cfg["default_net"],
            "etc_mode": cfg.get("etc_mode", "compat"),
        },
        "layer2_category": {
            "id": c_id,
            "freedesktop_categories": cat_meta.get("freedesktop_categories", []),
            "description": cat_meta.get("description", ""),
            "enabled_capabilities": [{"id": c, "description": catalog["capabilities"][c]["description"]} for c in cfg["capabilities"]],
            "added_capabilities": cfg.get("add_caps", []),
            "dropped_capabilities": cfg.get("drop_caps", []),
        },
        "non_preset_additions": {
            "ro_binds": cfg.get("ro_binds", []),
            "rw_binds": cfg.get("rw_binds", []),
            "dev_binds": cfg.get("dev_binds", []),
            "tmpfs_dirs": cfg.get("tmpfs_dirs", []),
            "empty_dirs": cfg.get("empty_dirs", []),
            "symlinks": [f"{s[0]}:{s[1]}" if isinstance(s, (list, tuple)) else str(s) for s in cfg.get("symlinks", [])],
            "setenv": cfg.get("env", {}),
            "unsetenv": cfg.get("unsetenv", []),
            "bwrap_args": cfg.get("bwrap_args", []),
        },
        "audit": audit_res,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pure Configuration-Driven Bubblewrap (bwrap) Sandbox Assembler.",
        usage="%(prog)s [options] [CONFIG_FILE | -]",
    )
    parser.add_argument("config_file", nargs="?", default=None, help="JSON/JSONC config file path or '-' for stdin")
    parser.add_argument("-c", "--config", dest="config_path", help="Alias for config file path")
    parser.add_argument("-j", "--json", dest="config_json_str", help="Inline JSON configuration string")
    parser.add_argument("-o", "--output", help="Override output Bash script path")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG_PATH), help="Path to catalog.json")
    parser.add_argument("--print-template", "--print-config-template", dest="print_template", action="store_true", help="Print config template")
    parser.add_argument("--list", action="store_true", help="List available catalog presets")

    args = parser.parse_args()
    catalog_path = Path(args.catalog)
    catalog = load_catalog(catalog_path)

    if args.list:
        print(json.dumps({
            "runtimes": {k: v["description"] for k, v in catalog["runtimes"].items()},
            "categories": {k: {"capabilities": v["capabilities"], "default_net": v["default_net"], "description": v["description"]} for k, v in catalog["categories"].items()},
            "capabilities": {k: v["description"] for k, v in catalog["capabilities"].items()}
        }, indent=2, ensure_ascii=False))
        return

    if args.print_template:
        print(CONFIG_TEMPLATE_PATH.read_text(encoding="utf-8") if CONFIG_TEMPLATE_PATH.exists() else json.dumps(load_config_template(), indent=2, ensure_ascii=False))
        return

    cfg = load_config_template()
    src = args.config_file or args.config_path
    if src:
        cfg.update(parse_json_config(sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")))
    elif args.config_json_str:
        cfg.update(parse_json_config(args.config_json_str))
    else:
        parser.error("No configuration provided. Supply a CONFIG_FILE, '-' (stdin), or --json '<json>'. Use --print-template to see template.")

    if args.output:
        cfg["output"] = args.output

    out_path = cfg.get("output")
    if not (cfg.get("runtime") or cfg.get("runtime_id")) or not (cfg.get("category") or cfg.get("category_id")) or not out_path:
        parser.error("Configuration must specify 'runtime', 'category', and 'output'.")

    cfg = resolve_config(cfg, catalog)
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(assemble_script(catalog, **cfg), encoding="utf-8")

    # Mandatory security and portability audit gatekeeper
    audit_res = audit_script(out_file, catalog_path)
    if audit_res["status"] == "FAIL":
        os.chmod(out_file, 0o600)
        print(json.dumps({"status": "error", "message": "Script failed security audit!", "audit": audit_res}, indent=2, ensure_ascii=False))
        sys.exit(1)

    os.chmod(out_file, 0o755)
    rep_path = cfg.get("report")
    expected_rep = Path(rep_path) if rep_path else out_file.with_name(f"{out_file.stem}-briefing.md")
    briefing = build_briefing_data(cfg, catalog, out_file, audit_res)
    briefing["expected_report_file"] = os.path.abspath(expected_rep)

    tmpl_rel = catalog["base_presets"].get("report_template", "presets/base/report-template.md")
    print(json.dumps({
        "status": "ok",
        "output_script": os.path.abspath(out_file),
        "expected_report_file": os.path.abspath(expected_rep),
        "report_template_path": os.path.abspath(SKILL_ROOT / tmpl_rel),
        "localization_notice": (
            "MANDATORY ACTION REQUIRED: (1) Read `report_template_path`, (2) render the complete "
            "Sandbox Security Briefing in the EXACT language used by the user in their prompt "
            "(e.g., Simplified Chinese if the user asked in Chinese; English if the user asked in English), "
            "AND (3) WRITE the localized Markdown report to disk at `expected_report_file` before finishing!"
        ),
        "briefing_data": briefing,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
