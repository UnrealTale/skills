# ==============================================================================
# Capability Preset [audio]: Cross-Backend Audio Input (Mic) & Output (Speakers)
# (Supports PipeWire, PulseAudio, and ALSA simultaneously)
# ==============================================================================
bwrap_setup_audio() {
  [[ "${ENABLE_AUDIO:-true}" != "true" ]] && return 0

  if [[ -n "${XDG_RUNTIME_DIR:-}" ]]; then
    bwrap_bind_try "${XDG_RUNTIME_DIR}/pipewire-0" "${XDG_RUNTIME_DIR}/pipewire-0"
    bwrap_bind_try "${XDG_RUNTIME_DIR}/pulse" "${XDG_RUNTIME_DIR}/pulse"
    bwrap_ro_bind_try "${HOME}/.config/pulse" "${HOME}/.config/pulse"
    bwrap_setenv XDG_RUNTIME_DIR "${XDG_RUNTIME_DIR}"
  fi
  bwrap_dev_bind_try /dev/snd /dev/snd
  bwrap_ro_bind_try /usr/share/alsa /usr/share/alsa
  bwrap_ro_bind_try /etc/alsa /etc/alsa
}
