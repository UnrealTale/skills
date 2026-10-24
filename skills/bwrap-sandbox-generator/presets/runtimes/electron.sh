# ==============================================================================
# Runtime Preset [electron]: Electron / Chromium / CEF / NW.js Applications
# ==============================================================================

bwrap_configure_runtime() {
  if [[ $# -eq 0 ]]; then
    echo "Error: No Electron/Chromium executable provided." >&2
    return 1
  fi

  TARGET_EXEC_ARGS=("$@")
  bwrap_setenv ELECTRON_DISABLE_SANDBOX 1
  if [[ "$1" =~ \.[aA]pp[iI]mage$ ]]; then
    bwrap_setenv APPIMAGE_EXTRACT_AND_RUN 1
  fi

  bwrap_init_app_context "$1"
}
