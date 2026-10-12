# ==============================================================================
# Capability Preset [hud]: Gaming Performance Overlays & Optimizers (GameMode/MangoHud/vkBasalt)
# ==============================================================================
bwrap_setup_hud() {
  [[ "${ENABLE_HUD:-true}" != "true" ]] && return 0

  if [[ -n "${XDG_RUNTIME_DIR:-}" ]]; then
    bwrap_bind_try "${XDG_RUNTIME_DIR}/gamemode" "${XDG_RUNTIME_DIR}/gamemode"
  fi
  bwrap_ro_bind_try "${HOME}/.config/MangoHud" "${HOME}/.config/MangoHud"
  bwrap_ro_bind_try "${HOME}/.config/vkBasalt" "${HOME}/.config/vkBasalt"
}
