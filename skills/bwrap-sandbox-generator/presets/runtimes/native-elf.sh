# ==============================================================================
# Runtime Preset [native-elf]: Native Linux ELF Executables
# ==============================================================================

bwrap_configure_runtime() {
  if [[ $# -eq 0 ]]; then
    echo "Error: No native executable provided." >&2
    return 1
  fi

  TARGET_EXEC_ARGS=("$@")
  bwrap_init_app_context "$1"
}
