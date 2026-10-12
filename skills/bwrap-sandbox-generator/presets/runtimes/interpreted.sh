# ==============================================================================
# Runtime Preset [interpreted]: Interpreted & VM Environments (Python/Java/Shell/Node/Love2D)
# ==============================================================================
declare -a TARGET_EXEC_ARGS=()

bwrap_configure_runtime() {
  if [[ $# -eq 0 ]]; then
    echo "Error: No interpreter or script command provided." >&2
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
      for ((i=2; i<=$#; i++)); do
        if [[ "${!i}" == "-jar" ]]; then
          local next_idx=$((i+1))
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

  local target_realpath=""
  local app_dir=""
  if [[ -n "$real_script_file" && -e "$real_script_file" ]]; then
    target_realpath="$(realpath "$real_script_file")"
    if [[ -d "$target_realpath" ]]; then
      app_dir="$target_realpath"
    else
      app_dir="$(dirname "$target_realpath")"
    fi
  fi

  local app_id
  app_id="$(bwrap_resolve_app_id "${target_realpath:-$target_cmd}" "$app_dir")"

  bwrap_setup_isolated_home "$app_id" "$app_dir"
  [[ -n "$target_realpath" && -f "$target_realpath" && "${APP_DIR_MODE:-ro}" == "none" ]] && bwrap_ro_bind_try "$target_realpath" "$target_realpath"
  bwrap_mount_app_directory "$app_dir"
  bwrap_set_safe_workdir "$app_dir"
}
