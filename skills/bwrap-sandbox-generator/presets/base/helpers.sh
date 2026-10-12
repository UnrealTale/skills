# ==============================================================================
# Preset [base/helpers.sh]: Basic Mount & Environment Variable Helper Functions
# ==============================================================================
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
