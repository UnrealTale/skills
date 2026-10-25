# ==============================================================================
# Capability Preset [camera]: Webcams & Video Capture Input (V4L2 / Media Controller)
# ==============================================================================
bwrap_setup_camera() {
  [[ "${ENABLE_CAMERA:-true}" != "true" ]] && return 0

  local vid_node
  for vid_node in /dev/video* /dev/media* /dev/v4l*; do
    [[ -e "$vid_node" ]] && bwrap_dev_bind_try "$vid_node" "$vid_node"
  done
  bwrap_ro_bind_try /run/udev /run/udev
}
