# ==============================================================================
# Runtime Preset [interpreted]: Interpreted & VM Environments (Python/Java/Shell/Node/Love2D)
# ==============================================================================

bwrap_configure_runtime() {
  if [[ $# -eq 0 ]]; then
    printf "Error: No interpreter or script command provided.\n" >&2
    return 1
  fi

  TARGET_EXEC_ARGS=("$@")
  local target_cmd="$1"
  local real_script_file=""

  case "$(basename "$target_cmd")" in
    python|python3|python3.*|pypy*|bash|sh|zsh|node|deno|bun)
      [[ $# -ge 2 && -e "$2" ]] && real_script_file="$2"
      ;;
    java)
      local -i i=0
      local -i next_idx=0
      for ((i=2; i<=$#; i++)); do
        if [[ "${!i}" == "-jar" ]]; then
          next_idx=$((i+1))
          if [[ $next_idx -le $# && -f "${!next_idx}" ]]; then
            real_script_file="${!next_idx}"
            break
          fi
        fi
      done
      ;;
    love)
      [[ $# -ge 2 && -e "$2" ]] && real_script_file="$2"
      ;;
    *)
      [[ -e "$target_cmd" ]] && real_script_file="$target_cmd"
      ;;
  esac

  bwrap_init_app_context "${real_script_file:-$target_cmd}"
}
