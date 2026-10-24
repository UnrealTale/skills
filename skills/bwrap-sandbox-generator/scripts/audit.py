#!/usr/bin/env python3
"""
audit.py: Comprehensive Security Red-Line, System Integrity & Portability Auditor
for bwrap-sandbox-generator.

Audits a generated (or handwritten) bwrap Bash script against:
1. Bash syntax validity (`bash -n`).
2. Core namespace & lifecycle isolation (`--unshare-all`, `--die-with-parent`).
3. Real $HOME isolation (forbids direct host $HOME mount; requires `--tmpfs "$HOME"` or isolated `sandbox_home`).
4. System Integrity Protection (forbids read-write mounts on `/`, `/usr`, `/etc`, `/boot`,
   `/bin`, `/sbin`, `/lib*`, `/opt`, `/var`, `/root`, `/proc`, `/sys`; forbids full `/dev`
   passthrough, raw block devices `/dev/sd*`, `/dev/nvme*`, `/dev/mem`, and EFI vars).
5. Persistence & Host Execution Hijack Protection (forbids mounting `~/.bashrc`, `~/.zshrc`,
   `~/.profile`, `~/.config/autostart`, `~/.config/systemd`).
6. Container & Hypervisor Socket Protection (forbids `docker.sock`, `podman.sock`,
   `containerd.sock`, `libvirt-sock`, `lxd/incus` sockets, and dangerous `--cap-add`).
7. User Credential & Keyring Leakage Protection (forbids `~/.ssh`, `~/.gnupg`, `SSH_AUTH_SOCK`,
   GNOME Keyring / KWallet / `pass`, cloud tokens `~/.aws`, `~/.kube`, `~/.config/gcloud`,
   `~/.azure`, `~/.config/gh`, `~/.git-credentials`, `~/.netrc`, `~/.npmrc`, `~/.pypirc`,
   `~/.cargo/credentials*`, `rclone.conf`, and host browser profiles).
8. Topological `/etc/shadow` Masking Check (when `/etc` is ro-bound, verifies `/dev/null` masks `/etc/shadow` and `/etc/gshadow` afterwards).
9. Cross-environment portability tokens defined per capability in `catalog.json`.
10. Explicit warnings (`WARN`) for any non-preset extra binds or user data folders (`~/Documents`, `~/Downloads`, etc.).
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG_PATH = SKILL_ROOT / "catalog.json"

# Category A: Credential, Keyring & Secret Leakage Patterns (MUST BLOCK -> FAIL)
FORBIDDEN_CREDENTIAL_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"['\"/]\.ssh(['\"/\s]|$)"), "Exposes SSH keys/config (~/.ssh)"),
    (re.compile(r"['\"/]\.gnupg(['\"/\s]|$)"), "Exposes GPG keys (~/.gnupg)"),
    (re.compile(r"SSH_AUTH_SOCK|ssh-agent|/gnupg/S\."), "Exposes SSH/GPG agent socket"),
    (re.compile(r"['\"/]\.aws(['\"/\s]|$)"), "Exposes AWS credentials (~/.aws)"),
    (re.compile(r"['\"/]\.kube(['\"/\s]|$)"), "Exposes Kubernetes config (~/.kube)"),
    (re.compile(r"['\"/]\.config/gcloud(['\"/\s]|$)"), "Exposes Google Cloud credentials (~/.config/gcloud)"),
    (re.compile(r"['\"/]\.azure(['\"/\s]|$)"), "Exposes Azure CLI credentials (~/.azure)"),
    (re.compile(r"['\"/]\.config/gh(['\"/\s]|$)"), "Exposes GitHub CLI token (~/.config/gh)"),
    (re.compile(r"['\"/]\.(?:git-credentials|netrc)(['\"/\s]|$)"), "Exposes plaintext Git/network credentials (~/.git-credentials or ~/.netrc)"),
    (re.compile(r"['\"/]\.(?:npmrc|pypirc)(['\"/\s]|$)"), "Exposes package registry publishing token (~/.npmrc or ~/.pypirc)"),
    (re.compile(r"['\"/]\.cargo/credentials"), "Exposes Rust Cargo registry token (~/.cargo/credentials)"),
    (re.compile(r"['\"/]\.docker/config\.json"), "Exposes Docker registry auth (~/.docker/config.json)"),
    (re.compile(r"['\"/]\.config/containers/auth\.json"), "Exposes container registry auth (~/.config/containers/auth.json)"),
    (re.compile(r"['\"/]\.config/rclone"), "Exposes rclone cloud storage secrets (~/.config/rclone)"),
    (re.compile(r"['\"/]\.(?:vault-token|terraform\.d)(['\"/\s]|$)"), "Exposes HashiCorp Vault/Terraform credentials"),
    (re.compile(r"['\"/]\.password-store(['\"/\s]|$)"), "Exposes pass GPG password store (~/.password-store)"),
    (re.compile(r"['\"/]\.local/share/(?:keyrings|kwalletd)(['\"/\s]|$)"), "Exposes desktop password keyring storage (keyrings/kwalletd)"),
    (re.compile(r"['\"/]keyring(['\"/\s]|$)"), "Exposes GNOME Keyring daemon socket"),
    (
        re.compile(r"['\"/]\.(?:mozilla|config/google-chrome|config/chromium|config/BraveSoftware|config/vivaldi|config/microsoft-edge)(['\"/\s]|$)"),
        "Exposes host browser profile cookies and saved passwords",
    ),
    (re.compile(r"['\"/]/etc/sudoers"), "Exposes /etc/sudoers configuration"),
]

# Category B: System Destruction, Persistence Hijack & Container Escape Patterns (MUST BLOCK -> FAIL)
FORBIDDEN_SYSTEM_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"(?:docker\.sock|podman\.sock|containerd\.sock|crio\.sock|libvirt-sock|lxd/unix\.socket|incus/unix\.socket)"),
        "Exposes container/hypervisor daemon socket (trivial host root escape)",
    ),
    (
        re.compile(r"['\"/]\.(?:bashrc|bash_profile|bash_login|bash_logout|zshrc|zprofile|zshenv|profile|bash_history|zsh_history)(['\"/\s]|$)"),
        "Exposes host shell startup/history file (host persistence hijack risk)",
    ),
    (
        re.compile(r"['\"/]\.(?:config/autostart|config/systemd|local/share/systemd)(['\"/\s]|$)"),
        "Exposes XDG autostart or systemd user services (host persistence hijack risk)",
    ),
    (
        re.compile(r"/dev/(?:sd[a-z]|nvme\d|vd[a-z]|mmcblk\d|loop\d|dm-\d|md\d|mapper/|mem\b|kmem\b|port\b|tpm)"),
        "Exposes raw disk block device, physical memory, or TPM node (system destruction risk)",
    ),
    (
        re.compile(r"/sys/firmware/efi/efivars"),
        "Exposes UEFI NVRAM variables (/sys/firmware/efi/efivars)",
    ),
    (
        re.compile(r"(?:--(?:dev-)?bind(?:-try)?|bwrap_(?:dev_)?bind(?:_try)?)\s+['\"]?/dev['\"]?\s+['\"]?/dev['\"]?"),
        "Mounts entire host /dev instead of virtual `--dev /dev`",
    ),
    (
        re.compile(r"(?:--cap-add[\s'\"]+ALL\b|\b(?:CAP_SYS_ADMIN|CAP_SYS_PTRACE|CAP_SYS_MODULE|CAP_SYS_RAWIO|CAP_DAC_OVERRIDE|CAP_DAC_READ_SEARCH|CAP_SETUID|CAP_SETGID)\b)", re.I),
        "Grants dangerous Linux capability (--cap-add) allowing sandbox escape",
    ),
]

# Read-Write bind of critical system root directories (MUST BLOCK -> FAIL)
RW_SYSTEM_DIR_RE = re.compile(
    r"(?:--(?:dev-)?bind(?:-try)?|bwrap_(?:dev_)?bind(?:_try)?)\s+['\"]?(/(?:usr|etc|boot|bin|sbin|lib|lib64|lib32|opt|var|root|proc|sys)?/?)['\"]?\s+"
)

SYSTEM_ROOT_PATH_RE = re.compile(
    r"^/(?:(?:usr|etc|boot|bin|sbin|lib|lib64|lib32|opt|var|root|proc|sys)(?:/.*)?|/?)$"
)


def extract_rw_binds(content: str) -> List[str]:
    binds: List[str] = []
    # 1. Match entries declared inside RW_BINDS=( ... )
    m = re.search(r"\bRW_BINDS=\(\s*([\s\S]*?)\s*\)", content)
    if m:
        for line in m.group(1).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            item = line.strip("\"'")
            if item:
                binds.append(item)
    # 2. Match bwrap_mount_spec "bind" / 'bind' calls
    for m in re.finditer(r'bwrap_mount_spec\s+["\']?bind["\']?\s+["\']?([^"\'\s]+)["\']?', content):
        binds.append(m.group(1))
    return binds

# High-value personal user directories (Requires explicit user approval -> WARN)
USER_PERSONAL_DATA_RE = re.compile(
    r"/(?:Documents|Downloads|Desktop|Pictures|Videos|Music|Work|Projects|workspace)(['\"/\s]|$)"
)


def check_bash_syntax(script_path: Path) -> List[str]:
    proc = subprocess.run(
        ["bash", "-n", str(script_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return [f"Bash syntax error: {proc.stderr.strip()}"]
    return []


def audit_script(script_path: Path, catalog_path: Path) -> Dict[str, Any]:
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    content = script_path.read_text(encoding="utf-8", errors="ignore")
    non_comment_lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    active_code = "\n".join(non_comment_lines)

    errors: List[str] = []
    warnings: List[str] = []
    checks_passed: List[str] = []

    # 1. Bash syntax check
    syntax_errs = check_bash_syntax(script_path)
    if syntax_errs:
        errors.extend(syntax_errs)
    else:
        checks_passed.append("bash_syntax_valid")

    # 2. Core namespace flags
    if "--unshare-all" not in active_code:
        errors.append("Missing mandatory `--unshare-all` namespace isolation flag.")
    else:
        checks_passed.append("has_unshare_all")

    if "--die-with-parent" not in active_code:
        errors.append("Missing mandatory `--die-with-parent` lifecycle safety flag.")
    else:
        checks_passed.append("has_die_with_parent")

    # 3. Direct real $HOME bind check
    direct_home_bind = re.search(
        r"(?:--(?:ro-)?bind(?:-try)?|bwrap_(?:ro_)?bind(?:_try)?)\s+['\"]?(?:\$HOME|\$\{HOME\}|~)['\"]?\s+['\"]?(?:\$HOME|\$\{HOME\}|~)['\"]?",
        active_code,
    )
    if direct_home_bind:
        errors.append(
            'Direct mount of host real $HOME to sandbox $HOME detected! Must use `--tmpfs "$HOME"` or an isolated `$sandbox_home` directory.'
        )
    elif '--tmpfs "$HOME"' in active_code or '--bind "$sandbox_home" "$HOME"' in active_code:
        checks_passed.append("home_isolated")
    else:
        warnings.append('Could not explicitly verify `--tmpfs "$HOME"` or `$sandbox_home` isolation.')

    # 4. Read-write system directory protection
    for line in non_comment_lines:
        m_rw = RW_SYSTEM_DIR_RE.search(line)
        if m_rw:
            sys_target = m_rw.group(1)
            errors.append(
                f"Destructive read-write mount of system directory '{sys_target}' detected in line: `{line}`. System paths must be mounted read-only (`--ro-bind`)."
            )

    rw_bind_items = extract_rw_binds(content)
    for item in rw_bind_items:
        src = item.split(":", 1)[0]
        dst = item.split(":", 1)[1] if ":" in item else item
        if SYSTEM_ROOT_PATH_RE.match(src) or SYSTEM_ROOT_PATH_RE.match(dst):
            errors.append(
                f"Destructive read-write mount of system directory detected in RW_BINDS: '{item}'. System paths must be mounted read-only (`--ro-bind`)."
            )

    if not any("Destructive read-write mount" in e for e in errors):
        checks_passed.append("system_dirs_read_only_protected")

    # 5. /etc/shadow & /etc/gshadow masking check when /etc is mounted
    if "bwrap_ro_bind /etc /etc" in active_code or "--ro-bind /etc /etc" in active_code:
        if "/dev/null /etc/shadow" not in active_code or "/dev/null /etc/gshadow" not in active_code:
            errors.append(
                "Full `/etc` is read-only mounted without masking `/etc/shadow` and `/etc/gshadow` via `/dev/null`!"
            )
        else:
            checks_passed.append("etc_shadow_masked")

    # 6. Forbidden credential & system destruction patterns
    for pattern, msg in FORBIDDEN_CREDENTIAL_PATTERNS + FORBIDDEN_SYSTEM_PATTERNS:
        for line in non_comment_lines:
            if pattern.search(line):
                errors.append(f"{msg} in line: `{line}`")

    if not any(e for e in errors if "Exposes " in e or "Grants " in e):
        checks_passed.append("no_forbidden_credentials_or_escape_vectors")

    # 7. Unconditional $PWD bind check
    if re.search(r"(?:--bind|bwrap_bind)\s+['\"]?\$PWD['\"]?\s+['\"]?\$PWD['\"]?", active_code):
        if '$PWD" != "$HOME"' not in active_code and "${PWD:-}" not in active_code:
            errors.append(
                'Unconditional `--bind "$PWD" "$PWD"` detected without `$PWD != "$HOME"` safety guard.'
            )

    # 8. Flag user personal directories (~/Documents, ~/Downloads, etc.) as explicit WARN
    for line in non_comment_lines:
        if USER_PERSONAL_DATA_RE.search(line):
            warnings.append(
                f"User personal data directory mounted (`{line}`). Ensure the user explicitly reviewed and approved this risk."
            )

    # 9. Dynamic Capability Portability Audit driven by catalog.json
    for cap_id, cap_meta in catalog.get("capabilities", {}).items():
        func_def = f'{cap_meta["function"]}()'
        if func_def in active_code:
            missing_tokens = [
                tok
                for tok in cap_meta.get("required_audit_tokens", [])
                if tok not in active_code
            ]
            if missing_tokens:
                errors.append(
                    f"Capability '{cap_id}' ({func_def}) is missing required portable tokens: {missing_tokens}"
                )
            else:
                checks_passed.append(f"cap_{cap_id}_portable")

    # 10. Anti-nesting check
    if "_BWRAP_SANDBOX_ACTIVE" in active_code:
        checks_passed.append("anti_nesting_guard")
    else:
        warnings.append("Missing `_BWRAP_SANDBOX_ACTIVE` anti-nesting guard.")

    status = "FAIL" if errors else ("WARN" if warnings else "PASS")
    return {
        "status": status,
        "script": str(script_path.resolve()),
        "checks_passed": checks_passed,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Catalog-driven Security, System Integrity & Portability Auditor for bwrap scripts"
    )
    parser.add_argument("script", help="Path to generated bwrap Bash script")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG_PATH), help="Path to catalog.json")
    args = parser.parse_args()

    result = audit_script(Path(args.script), Path(args.catalog))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["status"] == "FAIL":
        sys.exit(1)


if __name__ == "__main__":
    main()
