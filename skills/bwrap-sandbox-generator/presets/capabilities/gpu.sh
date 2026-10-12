# ==============================================================================
# Capability Preset [gpu]: Cross-Vendor GPU Hardware Acceleration & Vulkan/OpenGL/OpenCL
# (Includes AMD, Intel, and NVIDIA device/driver paths via *-try for cross-host portability)
# ==============================================================================
bwrap_setup_gpu() {
  [[ "${ENABLE_GPU:-true}" != "true" ]] && return 0

  # 1. Generic Mesa / KMS / AMD (ROCm/AMDGPU) / Intel (i915/Xe)
  bwrap_dev_bind_try /dev/dri /dev/dri
  bwrap_dev_bind_try /dev/kfd /dev/kfd
  bwrap_ro_bind_try /sys/class/drm /sys/class/drm
  bwrap_ro_bind_try /sys/dev /sys/dev
  bwrap_ro_bind_try /sys/devices /sys/devices
  bwrap_ro_bind_try /sys/bus/pci /sys/bus/pci
  bwrap_ro_bind_try /sys/class/hwmon /sys/class/hwmon

  # 2. NVIDIA proprietary & open kernel module device nodes and multi-distro library paths
  bwrap_dev_bind_try /dev/nvidia0 /dev/nvidia0
  bwrap_dev_bind_try /dev/nvidia1 /dev/nvidia1
  bwrap_dev_bind_try /dev/nvidiactl /dev/nvidiactl
  bwrap_dev_bind_try /dev/nvidia-uvm /dev/nvidia-uvm
  bwrap_dev_bind_try /dev/nvidia-modeset /dev/nvidia-modeset
  bwrap_dev_bind_try /dev/nvidia-uvm-tools /dev/nvidia-uvm-tools
  bwrap_dev_bind_try /dev/nvidia-caps /dev/nvidia-caps
  bwrap_ro_bind_try /proc/driver/nvidia /proc/driver/nvidia
  bwrap_ro_bind_try /sys/module/nvidia /sys/module/nvidia
  bwrap_ro_bind_try /sys/module/nvidia_drm /sys/module/nvidia_drm
  bwrap_ro_bind_try /usr/share/glvnd /usr/share/glvnd
  bwrap_ro_bind_try /usr/share/nvidia /usr/share/nvidia
  bwrap_ro_bind_try /usr/lib/x86_64-linux-gnu/nvidia /usr/lib/x86_64-linux-gnu/nvidia
  bwrap_ro_bind_try /usr/lib/i386-linux-gnu/nvidia /usr/lib/i386-linux-gnu/nvidia
  bwrap_ro_bind_try /usr/lib/nvidia /usr/lib/nvidia
  bwrap_ro_bind_try /usr/lib32/nvidia /usr/lib32/nvidia

  # 3. Vulkan ICD / Layer & OpenCL / Mesa configuration directories
  bwrap_ro_bind_try /usr/share/vulkan /usr/share/vulkan
  bwrap_ro_bind_try /etc/vulkan /etc/vulkan
  bwrap_ro_bind_try /etc/OpenCL /etc/OpenCL
  bwrap_ro_bind_try /usr/share/drirc.d /usr/share/drirc.d
}
