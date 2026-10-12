# ==============================================================================
# Capability Preset [input]: Input Devices, Game Controllers, udev & Fast Kernel Sync
# ==============================================================================
bwrap_setup_input() {
  [[ "${ENABLE_INPUT:-true}" != "true" ]] && return 0

  bwrap_dev_bind_try /dev/input /dev/input
  bwrap_dev_bind_try /dev/uinput /dev/uinput
  bwrap_dev_bind_try /dev/hidraw /dev/hidraw
  for hid_node in /dev/hidraw*; do
    [[ -e "$hid_node" ]] && bwrap_dev_bind_try "$hid_node" "$hid_node"
  done

  bwrap_ro_bind_try /run/udev /run/udev
  bwrap_dev_bind_try /dev/ntsync /dev/ntsync
}
