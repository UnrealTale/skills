# ==============================================================================
# Runtime Preset [native-elf]: Native Linux ELF Executables
# ==============================================================================
declare -a TARGET_EXEC_ARGS=()

bwrap_configure_runtime() {
  if [[ $# -eq 0 ]]; then
    echo "Error: No native executable provided." >&2
    return 1
  fi

  TARGET_EXEC_ARGS=("$@")
  local target_cmd="$1"
  local target_realpath=""
  local app_dir=""

  if [[ -e "$target_cmd" ]]; then
    target_realpath="$(realpath "$target_cmd")"
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
