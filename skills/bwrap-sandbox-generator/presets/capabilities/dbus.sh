# ==============================================================================
# Capability Preset [dbus]: Desktop D-Bus Session Bus (Notifications, Portals, Screen Sharing)
# ==============================================================================
bwrap_setup_dbus() {
  [[ "${ENABLE_DBUS:-true}" != "true" ]] && return 0

  if [[ -n "${XDG_RUNTIME_DIR:-}" && -S "${XDG_RUNTIME_DIR}/bus" ]]; then
    bwrap_bind_try "${XDG_RUNTIME_DIR}/bus" "${XDG_RUNTIME_DIR}/bus"
    if [[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
      bwrap_setenv DBUS_SESSION_BUS_ADDRESS "${DBUS_SESSION_BUS_ADDRESS}"
    fi
  fi
}
