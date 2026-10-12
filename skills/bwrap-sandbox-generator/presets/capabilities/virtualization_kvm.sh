# ==============================================================================
# Capability Preset [virtualization_kvm]: KVM Hardware Virtualization & vhost Devices
# ==============================================================================
bwrap_setup_kvm() {
  [[ "${ENABLE_KVM:-true}" != "true" ]] && return 0

  bwrap_dev_bind_try /dev/kvm /dev/kvm
  bwrap_dev_bind_try /dev/vhost-net /dev/vhost-net
  bwrap_dev_bind_try /dev/vhost-vsock /dev/vhost-vsock
}
