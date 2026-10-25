# ==============================================================================
# Preset [base/entrypoint.sh]: Streamlined CLI Parser & Intelligent Dispatcher
# ==============================================================================
usage_sandbox() {
  cat <<EOF
Usage: $(basename "$0") [SANDBOX_OPTIONS] [--] [COMMAND / ARGS...]

Sandbox Options (High-Frequency Overrides):
  -i, --id <ID>                Specify application ID (used for isolated persistent HOME)
      --trace <LOG_FILE>       Record file/network syscalls via strace for troubleshooting
  -v, --verbose                Print assembled bwrap command line before executing
  -h, --help                   Show this help message

Notes:
  - Option parsing stops immediately upon encountering the first non-sandbox argument
    or '--'; all subsequent arguments are passed directly to the target program.
  - Mount paths, network access, and isolation modes can be configured directly
    in the variables section at the top of this script.
EOF
  exit "${1:-0}"
}

bwrap_parse_cli_args() {
  CUSTOM_APP_ID=""
  TRACE_LOG=""
  VERBOSE="${VERBOSE:-false}"
  declare -g -a REMAINING_ARGS=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -i|--id)
        if [[ $# -lt 2 ]]; then
          printf "Error: -i/--id requires an argument.\n" >&2
          usage_sandbox 1
        fi
        CUSTOM_APP_ID="$2"
        shift 2
        ;;
      --trace)
        if [[ $# -lt 2 ]]; then
          printf "Error: --trace requires a log file path.\n" >&2
          usage_sandbox 1
        fi
        TRACE_LOG="$2"
        shift 2
        ;;
      -v|--verbose)
        VERBOSE=true
        shift
        ;;
      -h|--help)
        usage_sandbox 0
        ;;
      --)
        shift
        REMAINING_ARGS+=("$@")
        break
        ;;
      *)
        REMAINING_ARGS+=("$@")
        break
        ;;
    esac
  done

  # Intelligent command dispatch
  if [[ ${#REMAINING_ARGS[@]} -eq 0 ]]; then
    if [[ ${#DEFAULT_TARGET_CMD[@]} -gt 0 ]]; then
      REMAINING_ARGS=("${DEFAULT_TARGET_CMD[@]}")
    else
      printf "Error: No target program or command provided.\n" >&2
      usage_sandbox 1
    fi
  elif [[ ${#DEFAULT_TARGET_CMD[@]} -gt 0 ]]; then
    local first_arg="${REMAINING_ARGS[0]}"
    local exp_first_arg="${first_arg/#\~/$HOME}"
    local is_executable=false

    # Arguments starting with '-' are option flags, never a new executable command
    if [[ "$first_arg" != -* ]]; then
      if [[ ( -x "$exp_first_arg" || -L "$exp_first_arg" ) && ! -d "$exp_first_arg" ]]; then
        is_executable=true
      elif [[ "$first_arg" != *"/"* ]] && command -v -- "$first_arg" >/dev/null 2>&1; then
        is_executable=true
      fi
    fi

    if [[ "$is_executable" == "false" ]]; then
      # Not an executable program; treat remaining args as arguments to DEFAULT_TARGET_CMD
      REMAINING_ARGS=("${DEFAULT_TARGET_CMD[@]}" "${REMAINING_ARGS[@]}")
    fi
  fi
}
