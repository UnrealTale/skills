#!/usr/bin/env bash
# ==============================================================================
# Bubblewrap (bwrap) Least-Privilege Portable Sandbox Launcher — [{{APP_ID}}]
# Layer 1 Runtime  : {{RUNTIME_ID}} ({{RUNTIME_DESC}})
# Layer 2 Category : {{CATEGORY_ID}} ({{CATEGORY_DESC}})
# Capabilities     : {{CAPABILITIES_STR}}
# Policies         : home={{HOME_MODE}}, cwd={{CWD_MODE}}, app_dir={{APP_DIR_MODE}}, net={{ALLOW_NET}}, etc={{ETC_MODE}}
# ==============================================================================
set -Eeuo pipefail
OPEN_FILES_LIMIT={{OPEN_FILES_LIMIT}}
ulimit -n "$OPEN_FILES_LIMIT" 2>/dev/null || true

declare -a BWRAP_CMD=(bwrap)

# ==============================================================================
# Sandbox Configuration (Directly Editable)
# ==============================================================================
DEFAULT_APP_ID="{{APP_ID}}"
{{DEFAULT_TARGET_CMD}}

# Storage & Directory Locations
SANDBOX_BASE_DIR="{{SANDBOX_BASE_DIR}}" # Base directory for isolated HOME (~/.local/share/bwrap-sandbox/<app-id>)
APP_DIR_HOME_NAME="{{APP_DIR_HOME_NAME}}"                     # Subdirectory name inside app folder when HOME_MODE="app-dir"
APP_DIR="${APP_DIR:-{{APP_DIR}}}"                                       # Explicit application root directory (leave empty to auto-derive from target binary)
{{WINE_CONFIG_BLOCK}}
# Network & Isolation Policies
ALLOW_NET={{ALLOW_NET}}
HOME_MODE="{{HOME_MODE}}"            # isolated | cwd | app-dir | custom | ephemeral
CUSTOM_HOME="{{CUSTOM_HOME}}"
CWD_MODE="{{CWD_MODE}}"              # none | ro | rw
APP_DIR_MODE="{{APP_DIR_MODE}}"          # ro | rw | none
ETC_MODE="{{ETC_MODE}}"              # compat | minimal
NEW_SESSION={{NEW_SESSION}}
VERBOSE=false

# Custom Mounts: "HOST_PATH[:CONTAINER_PATH]" (Omit container path for same-name mount)
declare -a RW_BINDS=(
{{RW_BINDS}}
)

declare -a RO_BINDS=(
{{RO_BINDS}}
)

declare -a DEV_BINDS=(
{{DEV_BINDS}}
)

if [[ -n "${_BWRAP_SANDBOX_ACTIVE:-}" ]]; then
  _BWRAP_IS_NESTED=true
else
  _BWRAP_IS_NESTED=false
fi

{{PRESET_HELPERS}}

{{PRESET_CORE}}

{{PRESET_NETWORK}}

{{PRESET_CAPABILITIES}}

{{PRESET_RUNTIME}}

{{PRESET_ENTRYPOINT}}

# ==============================================================================
# Main Sandbox Assembly Pipeline
# ==============================================================================
bwrap_parse_cli_args "$@"
bwrap_init_base
bwrap_setup_root_fs
BWRAP_CMD+=(--tmpfs /tmp --tmpfs /dev/shm)
{{RUNTIME_CALL}}
{{CAPABILITY_CALLS}}
{{EXTRA_PRIMITIVES}}
bwrap_apply_custom_mounts
bwrap_exec "${TARGET_EXEC_ARGS[@]}"
