# ==============================================================================
# Runtime Preset [wine]: Wine / Wine-GE / Proton / UMU Windows Translation Layer
# ==============================================================================

_bwrap_is_pe_file() {
  local target="${1:-}"
  [[ "$target" =~ \.[eE][xX][eE]$ ]] && return 0
  if [[ -f "$target" ]] && command -v file >/dev/null 2>&1; then
    file "$target" 2>/dev/null | grep -qi "PE32" && return 0
  fi
  return 1
}

bwrap_configure_runtime() {
  if [[ $# -eq 0 ]]; then
    printf "Error: No Wine command or .exe executable provided.\n" >&2
    return 1
  fi

  if _bwrap_is_pe_file "$1"; then
    TARGET_EXEC_ARGS=(wine "$@")
  else
    TARGET_EXEC_ARGS=("$@")
  fi

  local exe_file=""
  for arg in "${TARGET_EXEC_ARGS[@]}"; do
    if _bwrap_is_pe_file "$arg"; then
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
  local explicit_wineprefix="${WINE_PREFIX:-${CLI_PREFIX:-${BWRAP_WINE_PREFIX:-${WINEPREFIX:-}}}}"

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

  local steam_data="${STEAM_COMPAT_DATA_PATH:-}"
  if [[ -n "$steam_data" ]]; then
    steam_data="${steam_data/#\~/$HOME}"
    mkdir -p "$steam_data" 2>/dev/null || true
    bwrap_bind "$steam_data" "$steam_data"
    bwrap_setenv STEAM_COMPAT_DATA_PATH "$steam_data"
  fi

  local steam_client="${STEAM_COMPAT_CLIENT_INSTALL_PATH:-}"
  if [[ -n "$steam_client" ]]; then
    steam_client="${steam_client/#\~/$HOME}"
    bwrap_ro_bind_try "$steam_client" "$steam_client"
    bwrap_setenv STEAM_COMPAT_CLIENT_INSTALL_PATH "$steam_client"
  fi

  bwrap_bind_try "${HOME}/.local/share/wineprefixes" "${HOME}/.local/share/wineprefixes"
  bwrap_bind_try "${HOME}/.local/share/umu" "${HOME}/.local/share/umu"
  bwrap_bind_try "${HOME}/.cache/umu" "${HOME}/.cache/umu"
  bwrap_bind_try "${HOME}/.cache/umu-protonfixes" "${HOME}/.cache/umu-protonfixes"
  bwrap_bind_try "${HOME}/.local/share/Steam" "${HOME}/.local/share/Steam"
  bwrap_bind_try "${HOME}/.steam" "${HOME}/.steam"
}
