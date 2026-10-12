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
  BWRAP_CMD+=(--bind-try "$src" "$dst")
}

bwrap_ro_bind_try() {
  local src="$1"
  local dst="${2:-$1}"
  BWRAP_CMD+=(--ro-bind-try "$src" "$dst")
}

bwrap_dev_bind_try() {
  local src="$1"
  local dst="${2:-$1}"
  BWRAP_CMD+=(--dev-bind-try "$src" "$dst")
}

bwrap_setenv() {
  local key="$1"
  local val="$2"
  BWRAP_CMD+=(--setenv "$key" "$val")
}
