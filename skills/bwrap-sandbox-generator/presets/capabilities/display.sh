# ==============================================================================
# Capability Preset [display]: Video Display Output Passthrough (Wayland & X11)
# ==============================================================================
bwrap_setup_display() {
  [[ "${ENABLE_DISPLAY:-true}" != "true" ]] && return 0

  if [[ -n "${WAYLAND_DISPLAY:-}" && -S "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/${WAYLAND_DISPLAY}" ]]; then
    bwrap_bind "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}" "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}"
    bwrap_setenv WAYLAND_DISPLAY "$WAYLAND_DISPLAY"
  fi

  if [[ "${ALLOW_X11:-true}" == "true" && -n "${DISPLAY:-}" ]]; then
    local x11_num="${DISPLAY#*:}"
    x11_num="${x11_num%.*}"
    local x11_socket="/tmp/.X11-unix/X${x11_num}"
    if [[ -S "$x11_socket" ]]; then
      bwrap_bind_try "$x11_socket" "$x11_socket"
      bwrap_setenv DISPLAY "$DISPLAY"
    fi
    if [[ -n "${XAUTHORITY:-}" && -f "$XAUTHORITY" ]]; then
      bwrap_ro_bind_try "$XAUTHORITY" "$XAUTHORITY"
      bwrap_setenv XAUTHORITY "$XAUTHORITY"
    fi
  fi
}
