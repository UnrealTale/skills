# ==============================================================================
# Capability Preset [printing]: CUPS Printing Service Socket & Configuration
# ==============================================================================
bwrap_setup_printing() {
  [[ "${ENABLE_PRINTING:-true}" != "true" ]] && return 0

  bwrap_ro_bind_try /run/cups/cups.sock /run/cups/cups.sock
  bwrap_ro_bind_try /etc/cups /etc/cups
}
