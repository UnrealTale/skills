# ==============================================================================
# Capability Preset [bluetooth]: Bluetooth Controller State & BlueZ System Bus
# ==============================================================================
bwrap_setup_bluetooth() {
  [[ "${ENABLE_BLUETOOTH:-true}" != "true" ]] && return 0

  bwrap_dev_bind_try /dev/rfkill /dev/rfkill
  bwrap_ro_bind_try /sys/class/bluetooth /sys/class/bluetooth
  bwrap_ro_bind_try /run/dbus/system_bus_socket /run/dbus/system_bus_socket
}
