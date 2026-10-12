#!/usr/bin/env python3
"""
probe.py: Fallback-Only Dynamic Permission & Missing Path Probe for bwrap-sandbox-generator.

Responsibilities:
- Contains ZERO software category definitions or preset mappings (those live exclusively
  in `catalog.json` and are selected by the Agent/LLM).
- Used strictly as a fallback when an application fails to run under the standard
  Layer 1 (Runtime) + Layer 2 (Category) presets due to custom/private paths:
  1. `trace-analyze`: Denoise `strace -f -e trace=%file,%net` logs from a sandboxed run
     to extract true blocking missing paths (`ENOENT` / `EACCES`), classify their security
     risk, and enforce mandatory user review before binding.
  2. `ldd-nonstd`: Check an ELF binary's dynamic libraries via `ldd` and return only
     non-standard library directories outside `/usr`, `/lib*`, `/opt`.
"""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Set

from audit import (
    FORBIDDEN_CREDENTIAL_PATTERNS,
    FORBIDDEN_SYSTEM_PATTERNS,
    USER_PERSONAL_DATA_RE,
)

STANDARD_LIB_PREFIXES = (
    "/usr/",
    "/lib/",
    "/lib64/",
    "/lib32/",
    "/opt/",
    "/etc/ld.so",
    "linux-vdso.so",
    "/dev/",
    "/proc/",
    "/sys/",
)


def classify_path_risk(path: str) -> Dict[str, str]:
    """Classify a probed path's risk level so the Agent can present it to the user."""
    for pattern, reason in FORBIDDEN_CREDENTIAL_PATTERNS + FORBIDDEN_SYSTEM_PATTERNS:
        if pattern.search(path):
            return {
                "risk_level": "CRITICAL_FORBIDDEN",
                "policy": "NEVER_BIND",
                "reason": f"Blocked by security red-line: {reason}",
            }
    if USER_PERSONAL_DATA_RE.search(path):
        return {
            "risk_level": "HIGH_USER_DATA",
            "policy": "REQUIRES_EXPLICIT_USER_APPROVAL",
            "reason": "Personal user data directory (data deletion/modification or exfiltration risk if mounted read-write).",
        }
    return {
        "risk_level": "NON_PRESET_CUSTOM",
        "policy": "REQUIRES_EXPLICIT_USER_APPROVAL",
        "reason": "Non-preset path discovered via dynamic probe; must be reviewed and approved by the user before binding.",
    }


def inspect_nonstd_ldd(binary_path: Path) -> Dict[str, Any]:
    if not binary_path.exists():
        raise FileNotFoundError(f"Binary not found: {binary_path}")

    proc = subprocess.run(
        ["ldd", str(binary_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    non_std_dirs: Set[str] = set()
    missing_libs: List[str] = []

    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            if "not found" in line:
                missing_libs.append(line.split("=>")[0].strip())
            elif "=>" in line:
                rest = line.split("=>", 1)[1].strip()
                if rest.startswith("/"):
                    resolved_path = rest.split()[0]
                    if not any(resolved_path.startswith(p) for p in STANDARD_LIB_PREFIXES):
                        non_std_dirs.add(str(Path(resolved_path).parent))

    return {
        "user_approval_required": True,
        "approval_notice": "MANDATORY: Present any non_standard_lib_dirs to the user and obtain explicit approval before passing them to generate.py.",
        "binary": str(binary_path.resolve()),
        "non_standard_lib_dirs": [
            {"directory": d, **classify_path_risk(d)} for d in sorted(non_std_dirs)
        ],
        "unresolved_libraries": missing_libs,
    }


def analyze_strace_log(log_path: Path) -> Dict[str, Any]:
    if not log_path.exists():
        raise FileNotFoundError(f"Strace log not found: {log_path}")

    succeeded_basenames: Set[str] = set()
    succeeded_paths: Set[str] = set()
    failed_entries: Dict[str, str] = {}

    syscall_re = re.compile(
        r'^(?:\[pid\s+\d+\]\s+|\d+\s+)?(\w+)\((?:[^"]*"([^"]+)")?[^)]*\)\s*=\s*(-?\d+)(?:\s+([A-Z0-9_]+))?'
    )

    noise_substrings = (
        "/tls/x86_64/",
        "/tls/i686/",
        "/glibc-hwcaps/",
        "/haswell/",
        "/x86_64/v2/",
        "/x86_64/v3/",
        "/x86_64/v4/",
        "ld.so.preload",
        "/usr/share/locale/",
        "/usr/lib/locale/",
    )

    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = syscall_re.search(line)
        if not m:
            continue
        _syscall, path, ret_str, err_code = m.groups()
        if not path or not path.startswith("/"):
            continue
        if any(ns in path for ns in noise_substrings):
            continue

        ret_val = int(ret_str)
        base = os.path.basename(path)
        if ret_val >= 0:
            succeeded_paths.add(path)
            if ".so" in base:
                succeeded_basenames.add(base)
        elif err_code in ("ENOENT", "EACCES", "EPERM", "ECONNREFUSED"):
            failed_entries[path] = err_code

    filtered_failures: Dict[str, str] = {}
    for path, err in failed_entries.items():
        if path in succeeded_paths:
            continue
        base = os.path.basename(path)
        if ".so" in base and base in succeeded_basenames:
            continue
        filtered_failures[path] = err

    by_directory: Dict[str, Dict[str, Any]] = {}
    for path, err in sorted(filtered_failures.items()):
        parent = str(Path(path).parent)
        if parent not in by_directory:
            by_directory[parent] = {
                **classify_path_risk(parent),
                "files": [],
            }
        by_directory[parent]["files"].append(
            {"path": path, "error": err, **classify_path_risk(path)}
        )

    return {
        "user_approval_required": True,
        "approval_notice": (
            "MANDATORY: Do NOT autonomously bind any probed path below! "
            "Paths marked CRITICAL_FORBIDDEN must NEVER be bound. "
            "All other paths must be presented to the user with their risk_level and access mode (ro vs rw) for explicit selection."
        ),
        "total_unique_blocked_paths": len(filtered_failures),
        "blocked_by_directory": by_directory,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fallback-Only Dynamic Probe (strace denoiser & non-standard ldd inspector)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_trace = subparsers.add_parser(
        "trace-analyze",
        help="Denoise strace log when standard presets fail due to private/custom paths",
    )
    p_trace.add_argument("log_file", help="Path to strace output log file")

    p_ldd = subparsers.add_parser(
        "ldd-nonstd",
        help="Check an ELF binary for non-standard library paths outside /usr, /lib*, /opt",
    )
    p_ldd.add_argument("binary", help="Path to ELF binary")

    args = parser.parse_args()

    if args.command == "trace-analyze":
        result = analyze_strace_log(Path(args.log_file))
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "ldd-nonstd":
        result = inspect_nonstd_ldd(Path(args.binary))
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
