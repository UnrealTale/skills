# ==============================================================================
# Capability Preset [optical_storage]: Optical Drives & CD/DVD/BD Media Devices
# ==============================================================================
bwrap_setup_optical_storage() {
  [[ "${ENABLE_OPTICAL:-true}" != "true" ]] && return 0

  for node in /dev/sr* /dev/sg*; do
    [[ -e "$node" ]] && bwrap_dev_bind_try "$node" "$node"
  done
  bwrap_ro_bind_try /run/udev /run/udev
}
