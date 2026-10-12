# ==============================================================================
# Capability Preset [network]: Network Namespace, DNS Resolution & Cross-Distro CA Certificates
# ==============================================================================
bwrap_setup_network() {
  if [[ "$ALLOW_NET" == "true" ]]; then
    BWRAP_CMD+=(--share-net)
    bwrap_ro_bind_try /run/systemd/resolve /run/systemd/resolve
    bwrap_ro_bind_try /run/NetworkManager /run/NetworkManager
    bwrap_ro_bind_try /etc/resolv.conf /etc/resolv.conf
    bwrap_ro_bind_try /etc/hosts /etc/hosts
    bwrap_ro_bind_try /etc/nsswitch.conf /etc/nsswitch.conf
    bwrap_ro_bind_try /etc/ssl /etc/ssl
    bwrap_ro_bind_try /etc/ca-certificates /etc/ca-certificates
    bwrap_ro_bind_try /etc/pki /etc/pki
    bwrap_ro_bind_try /run/dbus/system_bus_socket /run/dbus/system_bus_socket
  fi
}
