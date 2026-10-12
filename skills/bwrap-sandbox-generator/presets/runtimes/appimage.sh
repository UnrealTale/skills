# ==============================================================================
# Runtime Preset [appimage]: AppImage Single-File Bundles (FUSE-less Extraction)
# ==============================================================================
declare -a TARGET_EXEC_ARGS=()

bwrap_configure_runtime() {
  if [[ $# -eq 0 ]]; then
    echo "Error: No AppImage file provided." >&2
    return 1
  fi

  TARGET_EXEC_ARGS=("$@")
  local target_cmd="$1"
  local target_realpath=""
  local app_dir=""

  if [[ -e "$target_cmd" ]]; then
    target_realpath="$(realpath "$target_cmd")"
    app_dir="$(dirname "$target_realpath")"
  fi

  local app_id
  app_id="$(bwrap_resolve_app_id "${target_realpath:-$target_cmd}" "$app_dir")"

  bwrap_setup_isolated_home "$app_id" "$app_dir"

  bwrap_setenv APPIMAGE_EXTRACT_AND_RUN 1
  [[ -n "$target_realpath" ]] && bwrap_ro_bind_try "$target_realpath" "$target_realpath"

  bwrap_mount_app_directory "$app_dir"
  bwrap_set_safe_workdir "$app_dir"
}
