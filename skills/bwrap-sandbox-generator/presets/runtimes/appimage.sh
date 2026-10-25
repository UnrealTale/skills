# ==============================================================================
# Runtime Preset [appimage]: AppImage Single-File Bundles (FUSE-less Extraction)
# ==============================================================================

bwrap_configure_runtime() {
  if [[ $# -eq 0 ]]; then
    printf "Error: No AppImage file provided.\n" >&2
    return 1
  fi

  TARGET_EXEC_ARGS=("$@")
  bwrap_setenv APPIMAGE_EXTRACT_AND_RUN 1
  bwrap_init_app_context "$1"
}
