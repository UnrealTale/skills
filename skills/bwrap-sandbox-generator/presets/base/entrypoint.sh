# ==============================================================================
# Preset [base/entrypoint.sh]: CLI Argument Parser & Runtime Extra Binds
# ==============================================================================
usage_sandbox() {
  cat <<EOF
Usage: $(basename "$0") [SANDBOX_OPTIONS] [COMMAND / ARGS...]

Options:
  -n, --net                    Enable network access (default: ${ALLOW_NET})
  --no-net                     Force disable network access
  -i, --id <ID>                Specify sandbox application ID (used for isolated persistent HOME)
  --home-mode <MODE>           Sandbox HOME mapping mode: isolated|cwd|app-dir|custom|ephemeral (default: ${HOME_MODE:-isolated})
  --home <DIR>                 Map sandbox HOME to custom directory <DIR> (sets --home-mode custom)
  --home-cwd                   Map sandbox HOME to current working directory \$PWD
  --home-app-dir               Map sandbox HOME to <app_dir>/.sandbox-home (portable mode)
  --ephemeral                  Ephemeral tmpfs mode: do not map sandbox HOME to disk (discard writes on exit)
  -p, --prefix <DIR>           Specify WINEPREFIX directory (effective in wine runtime)
  -w, --cwd, --cwd-rw          Allow read-write mounting of current working directory (\$PWD)
  --cwd-ro                     Allow read-only mounting of current working directory (\$PWD)
  --no-cwd                     Disable mounting of current working directory (\$PWD)
  --app-dir-ro                 Mount application directory read-only (default: ${APP_DIR_MODE:-ro})
  --app-dir-rw                 Mount application directory read-write (portable app self-write mode)
  --no-app-dir                 Do not auto-mount the application's parent directory
  -b, --bind <PATH>            Extra read-write bind mount (can be specified multiple times)
  -ro, --ro-bind <PATH>        Extra read-only bind mount (can be specified multiple times)
  -d, --dev-bind <PATH>        Extra device node bind mount (can be specified multiple times)
  --bwrap-arg <ARG>            Append a raw bwrap argument at runtime
  --trace <LOG_FILE>           Record file/network syscalls via strace inside sandbox for fallback debugging
  -v, --verbose                Print full bwrap command line for debugging
  -h, --help                   Show this help message
EOF
  exit "${1:-0}"
}

bwrap_parse_cli_args() {
  CUSTOM_APP_ID="${BWRAP_APP_ID:-}"
  CUSTOM_HOME="${BWRAP_SANDBOX_HOME:-}"
  CLI_PREFIX=""
  TRACE_LOG="${BWRAP_TRACE_LOG:-}"
  EXTRA_BINDS=()
  EXTRA_RO_BINDS=()
  EXTRA_DEV_BINDS=()
  EXTRA_RAW_ARGS=()
  REMAINING_ARGS=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -n|--net)              ALLOW_NET=true; shift ;;
      --no-net)              ALLOW_NET=false; shift ;;
      -i|--id)               CUSTOM_APP_ID="$2"; shift 2 ;;
      --home-mode)           HOME_MODE="$2"; shift 2 ;;
      --home)                HOME_MODE="custom"; CUSTOM_HOME="$2"; shift 2 ;;
      --home-cwd)            HOME_MODE="cwd"; shift ;;
      --home-app-dir)        HOME_MODE="app-dir"; shift ;;
      --ephemeral)           HOME_MODE="ephemeral"; EPHEMERAL=true; shift ;;
      -p|--prefix)           CLI_PREFIX="$2"; shift 2 ;;
      -w|--cwd|--cwd-rw)     CWD_MODE="rw"; MOUNT_CWD=true; shift ;;
      --cwd-ro)              CWD_MODE="ro"; shift ;;
      --no-cwd)              CWD_MODE="none"; MOUNT_CWD=false; shift ;;
      --app-dir-ro)          APP_DIR_MODE="ro"; shift ;;
      --app-dir-rw)          APP_DIR_MODE="rw"; shift ;;
      --no-app-dir)          APP_DIR_MODE="none"; shift ;;
      -b|--bind)             EXTRA_BINDS+=("$2"); shift 2 ;;
      -ro|--ro-bind)         EXTRA_RO_BINDS+=("$2"); shift 2 ;;
      -d|--dev-bind)         EXTRA_DEV_BINDS+=("$2"); shift 2 ;;
      --bwrap-arg)           EXTRA_RAW_ARGS+=("$2"); shift 2 ;;
      --trace)               TRACE_LOG="$2"; shift 2 ;;
      -v|--verbose)          VERBOSE=true; shift ;;
      -h|--help)             usage_sandbox 0 ;;
      --)                    shift; REMAINING_ARGS+=("$@"); break ;;
      *)                     REMAINING_ARGS+=("$@"); break ;;
    esac
  done

  if [[ ${#REMAINING_ARGS[@]} -eq 0 ]]; then
    if [[ ${#DEFAULT_TARGET_CMD[@]} -gt 0 ]]; then
      REMAINING_ARGS=("${DEFAULT_TARGET_CMD[@]}")
    else
      echo "Error: No target program or command provided." >&2
      usage_sandbox 1
    fi
  fi
}

bwrap_apply_runtime_extra_binds() {
  for p in "${EXTRA_BINDS[@]}"; do
    [[ -e "$p" ]] && bwrap_bind "$p" "$p"
  done
  for p in "${EXTRA_RO_BINDS[@]}"; do
    [[ -e "$p" ]] && bwrap_ro_bind "$p" "$p"
  done
  for p in "${EXTRA_DEV_BINDS[@]}"; do
    [[ -e "$p" ]] && bwrap_dev_bind_try "$p" "$p"
  done
  for raw_arg in "${EXTRA_RAW_ARGS[@]}"; do
    BWRAP_CMD+=("$raw_arg")
  done
  bwrap_apply_custom_whitelists
}
