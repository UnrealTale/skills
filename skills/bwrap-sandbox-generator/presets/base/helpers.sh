# ==============================================================================
# Preset [base/helpers.sh]: Basic Mount & Environment Variable Helper Functions
# ==============================================================================

# Universal mount specification handler:
# Parses "HOST_SRC[:CONTAINER_DEST]" or "PATH", expands '~',
# creates required parent/destination directory inside sandbox via --dir,
# gracefully skips non-existent source paths, and mounts to sandbox.
bwrap_mount_spec() {
  local mode="$1" # bind | ro-bind | dev-bind
  local spec="$2"
  local src="" dst=""

  [[ -z "$spec" ]] && return 0

  if [[ "$spec" == *":"* ]]; then
    src="${spec%%:*}"
    dst="${spec#*:}"
  else
    src="$spec"
    dst="$spec"
  fi

  # Expand leading tilde to current user's $HOME
  src="${src/#\~/$HOME}"
  dst="${dst/#\~/$HOME}"

  # Graceful degradation if source path does not exist on host
  if [[ ! -e "$src" ]]; then
    echo "[bwrap-sandbox] Warning: Mount source '${src}' does not exist on host; skipping." >&2
    return 0
  fi

  # Ensure destination mountpoint directory exists inside sandbox
  if [[ -d "$src" ]]; then
    BWRAP_CMD+=(--dir "$dst")
  else
    local dst_parent
    dst_parent="$(dirname "$dst")"
    [[ "$dst_parent" != "/" && -n "$dst_parent" ]] && BWRAP_CMD+=(--dir "$dst_parent")
  fi

  case "$mode" in
    bind)
      BWRAP_CMD+=(--bind "$src" "$dst")
      ;;
    ro-bind)
      BWRAP_CMD+=(--ro-bind "$src" "$dst")
      ;;
    dev-bind)
      BWRAP_CMD+=(--dev-bind-try "$src" "$dst")
      ;;
    *)
      echo "Error: Unknown mount mode '$mode' in bwrap_mount_spec." >&2
      return 1
      ;;
  esac
}

bwrap_bind() {
  local src="$1"
  local dst="${2:-$1}"
  BWRAP_CMD+=(--bind "$src" "$dst")
}

bwrap_ro_bind() {
  local src="$1"
  local dst="${2:-$1}"
  BWRAP_CMD+=(--ro-bind "$src" "$dst")
}

bwrap_bind_try() {
  local src="$1"
  local dst="${2:-$1}"
  if [[ -e "$src" ]]; then
    BWRAP_CMD+=(--bind-try "$src" "$dst")
  fi
}

bwrap_ro_bind_try() {
  local src="$1"
  local dst="${2:-$1}"
  if [[ -e "$src" ]]; then
    # When masking a file with /dev/null (e.g. /etc/shadow), only mount if target exists
    if [[ "$src" == "/dev/null" && ! -e "$dst" ]]; then
      return 0
    fi
    BWRAP_CMD+=(--ro-bind-try "$src" "$dst")
  fi
}

bwrap_dev_bind_try() {
  local src="$1"
  local dst="${2:-$1}"
  if [[ -e "$src" ]]; then
    BWRAP_CMD+=(--dev-bind-try "$src" "$dst")
  fi
}

bwrap_setenv() {
  local key="$1"
  local val="$2"
  BWRAP_CMD+=(--setenv "$key" "$val")
}
