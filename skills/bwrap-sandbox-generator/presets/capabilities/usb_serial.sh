# ==============================================================================
# Capability Preset [usb_serial]: Raw USB Bus, Serial Ports (ttyUSB/ttyACM) & HID
# ==============================================================================
bwrap_setup_usb_serial() {
  [[ "${ENABLE_USB_SERIAL:-true}" != "true" ]] && return 0

  bwrap_dev_bind_try /dev/bus/usb /dev/bus/usb
  local node
  for node in /dev/ttyUSB* /dev/ttyACM* /dev/hidraw*; do
    [[ -e "$node" ]] && bwrap_dev_bind_try "$node" "$node"
  done
  bwrap_ro_bind_try /run/udev /run/udev
}
