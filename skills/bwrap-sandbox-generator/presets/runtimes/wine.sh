# ==============================================================================
# Runtime Preset [wine]: Wine / Wine-GE / Proton / UMU Windows Translation Layer
# ==============================================================================

bwrap_configure_runtime() {
  if [[ $# -eq 0 ]]; then
    echo "Error: No Wine command or .exe executable provided." >&2
    return 1
  fi

  if [[ "$1" =~ \.[eE][xX][eE]$ ]] || ( [[ -f "$1" ]] && file "$1" 2>/dev/null | grep -qi "PE32" ); then
    TARGET_EXEC_ARGS=(wine "$@")
  else
    TARGET_EXEC_ARGS=("$@")
  fi

  local exe_file=""
  for arg in "${TARGET_EXEC_ARGS[@]}"; do
    if [[ "$arg" =~ \.[eE][xX][eE]$ ]] || ( [[ -f "$arg" ]] && file "$arg" 2>/dev/null | grep -qi "PE32" ); then
      exe_file="$arg"
      break
    fi
  done

  # Initialize application directory, isolated HOME, and safe workdir
  bwrap_init_app_context "${exe_file:-$1}"

  # Resolve WINEPREFIX:
  # - If explicitly specified via WINE_PREFIX in header or CLI_PREFIX / BWRAP_WINE_PREFIX / WINEPREFIX env var, mount that prefix.
  # - Otherwise, use ${HOME}/.wine inside the per-app isolated sandbox HOME so each Wine app/game
  #   automatically gets its own isolated prefix (e.g. ~/.local/share/bwrap-sandbox/<app_id>/.wine).
  local explicit_wineprefix=""
  if [[ -n "${WINE_PREFIX:-}" ]]; then
    explicit_wineprefix="$WINE_PREFIX"
  elif [[ -n "${CLI_PREFIX:-}" ]]; then
    explicit_wineprefix="$CLI_PREFIX"
  elif [[ -n "${BWRAP_WINE_PREFIX:-}" ]]; then
    explicit_wineprefix="$BWRAP_WINE_PREFIX"
  elif [[ -n "${WINEPREFIX:-}" ]]; then
    explicit_wineprefix="$WINEPREFIX"
  fi

  if [[ -n "$explicit_wineprefix" ]]; then
    explicit_wineprefix="${explicit_wineprefix/#\~/$HOME}"
    mkdir -p "$explicit_wineprefix" 2>/dev/null || true
    local real_wineprefix
    real_wineprefix="$(realpath -m "$explicit_wineprefix")"
    bwrap_bind "$real_wineprefix" "$real_wineprefix"
    bwrap_setenv WINEPREFIX "$real_wineprefix"
  else
    bwrap_setenv WINEPREFIX "${HOME}/.wine"
  fi

  bwrap_setenv UMU_NO_RUNTIME 1
  bwrap_setenv PRESSURE_VESSEL_SHARE_HOME 1

  if [[ -n "${STEAM_COMPAT_DATA_PATH:-}" ]]; then
    mkdir -p "$STEAM_COMPAT_DATA_PATH" 2>/dev/null || true
    bwrap_bind "$STEAM_COMPAT_DATA_PATH" "$STEAM_COMPAT_DATA_PATH"
    bwrap_setenv STEAM_COMPAT_DATA_PATH "$STEAM_COMPAT_DATA_PATH"
  fi

  if [[ -n "${STEAM_COMPAT_CLIENT_INSTALL_PATH:-}" ]]; then
    bwrap_ro_bind_try "$STEAM_COMPAT_CLIENT_INSTALL_PATH" "$STEAM_COMPAT_CLIENT_INSTALL_PATH"
    bwrap_setenv STEAM_COMPAT_CLIENT_INSTALL_PATH "$STEAM_COMPAT_CLIENT_INSTALL_PATH"
  fi

  bwrap_bind_try "${HOME}/.local/share/wineprefixes" "${HOME}/.local/share/wineprefixes"
  bwrap_bind_try "${HOME}/.local/share/umu" "${HOME}/.local/share/umu"
  bwrap_bind_try "${HOME}/.cache/umu" "${HOME}/.cache/umu"
  bwrap_bind_try "${HOME}/.cache/umu-protonfixes" "${HOME}/.cache/umu-protonfixes"
  bwrap_bind_try "${HOME}/.local/share/Steam" "${HOME}/.local/share/Steam"
  bwrap_bind_try "${HOME}/.steam" "${HOME}/.steam"
}
