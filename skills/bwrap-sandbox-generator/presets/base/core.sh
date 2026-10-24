# ==============================================================================
# Preset [base/core.sh]: Namespace Isolation, Read-Only RootFS, Configurable HOME/CWD/AppDir & Safe Workdir
# ==============================================================================
declare -a TARGET_EXEC_ARGS=()

bwrap_init_base() {
  BWRAP_CMD=(
    bwrap
    --unshare-all      # Isolate mount, uts, ipc, pid, net, user namespaces
    --die-with-parent  # Terminate sandbox when parent process exits
    --uid "$(id -u)"
    --gid "$(id -g)"
  )
  if [[ "${NEW_SESSION:-true}" == "true" ]]; then
    BWRAP_CMD+=(--new-session)
  fi
}

bwrap_setup_root_fs() {
  bwrap_ro_bind /usr /usr

  if [[ "${ETC_MODE:-compat}" == "minimal" ]]; then
    BWRAP_CMD+=(--dir /etc)
    bwrap_ro_bind_try /etc/ld.so.cache
    bwrap_ro_bind_try /etc/ld.so.conf
    bwrap_ro_bind_try /etc/ld.so.conf.d
    bwrap_ro_bind_try /etc/localtime
    bwrap_ro_bind_try /etc/locale.conf
    bwrap_ro_bind_try /etc/alternatives
  else
    bwrap_ro_bind /etc /etc
    bwrap_ro_bind_try /dev/null /etc/shadow
    bwrap_ro_bind_try /dev/null /etc/gshadow
  fi

  # Handle both UsrMerge distros (/lib -> usr/lib) and split-root distros
  if [[ -L /bin || ! -d /bin ]]; then
    BWRAP_CMD+=(--symlink usr/bin /bin)
  else
    bwrap_ro_bind_try /bin
  fi

  if [[ -L /sbin || ! -d /sbin ]]; then
    BWRAP_CMD+=(--symlink usr/sbin /sbin)
  else
    bwrap_ro_bind_try /sbin
  fi

  if [[ -L /lib || ! -d /lib ]]; then
    BWRAP_CMD+=(--symlink usr/lib /lib)
  else
    bwrap_ro_bind_try /lib
  fi

  if [[ -L /lib64 ]]; then
    BWRAP_CMD+=(--symlink usr/lib64 /lib64)
  elif [[ -d /lib64 ]]; then
    bwrap_ro_bind_try /lib64
  elif [[ -d /usr/lib64 ]]; then
    BWRAP_CMD+=(--symlink usr/lib64 /lib64)
  fi

  if [[ -L /lib32 ]]; then
    BWRAP_CMD+=(--symlink usr/lib32 /lib32)
  elif [[ -d /lib32 ]]; then
    bwrap_ro_bind_try /lib32
  elif [[ -d /usr/lib32 ]]; then
    BWRAP_CMD+=(--symlink usr/lib32 /lib32)
  fi

  BWRAP_CMD+=(
    --proc /proc
    --dev /dev
  )

  bwrap_ro_bind_try /opt
}

bwrap_apply_custom_mounts() {
  local spec

  # 1. Mount from RW_BINDS array (read-write)
  if [[ -n "${RW_BINDS+x}" ]]; then
    for spec in "${RW_BINDS[@]}"; do
      bwrap_mount_spec "bind" "$spec"
    done
  fi

  # 2. Mount from RO_BINDS array (read-only)
  if [[ -n "${RO_BINDS+x}" ]]; then
    for spec in "${RO_BINDS[@]}"; do
      bwrap_mount_spec "ro-bind" "$spec"
    done
  fi

  # 3. Mount from DEV_BINDS array (device nodes)
  if [[ -n "${DEV_BINDS+x}" ]]; then
    for spec in "${DEV_BINDS[@]}"; do
      bwrap_mount_spec "dev-bind" "$spec"
    done
  fi

  # 4. External environment variable overrides (space or comma separated)
  local extra_rw="${EXTRA_RW_BINDS:-${BWRAP_BINDS:-}}"
  if [[ -n "$extra_rw" ]]; then
    for spec in ${extra_rw//,/ }; do
      bwrap_mount_spec "bind" "$spec"
    done
  fi

  local extra_ro="${EXTRA_RO_BINDS:-${BWRAP_RO_BINDS:-}}"
  if [[ -n "$extra_ro" ]]; then
    for spec in ${extra_ro//,/ }; do
      bwrap_mount_spec "ro-bind" "$spec"
    done
  fi

  local extra_dev="${EXTRA_DEV_BINDS:-${BWRAP_DEV_BINDS:-}}"
  if [[ -n "$extra_dev" ]]; then
    for spec in ${extra_dev//,/ }; do
      bwrap_mount_spec "dev-bind" "$spec"
    done
  fi
}

# Initialize complete application lifecycle context:
#   1. Resolves canonical executable/file path
#   2. Resolves application root directory (honoring APP_DIR or target path)
#   3. Resolves application identifier (CUSTOM_APP_ID -> DEFAULT_APP_ID -> sandbox-app)
#   4. Initializes persistent or isolated sandbox HOME (HOME_MODE)
#   5. Mounts application directory (ro/rw/none) or single target executable
#   6. Configures container working directory and mounts CWD (CWD_MODE)
bwrap_init_app_context() {
  local app_target="${1:-}"

  # 1. Resolve canonical executable/file path
  local app_exe=""
  if [[ -n "$app_target" ]]; then
    if [[ -e "$app_target" || -L "$app_target" ]]; then
      app_exe="$(realpath -s "$app_target")"
    elif [[ "$app_target" != -* ]] && command -v -- "$app_target" >/dev/null 2>&1; then
      app_exe="$(realpath "$(command -v -- "$app_target")")"
    else
      app_exe="$app_target"
    fi
  fi

  # 2. Resolve application root directory
  local app_dir=""
  local manual_app_dir="${APP_DIR:-}"
  if [[ -n "$manual_app_dir" ]]; then
    manual_app_dir="${manual_app_dir/#\~/$HOME}"
    app_dir="$(realpath -m "$manual_app_dir")"
  elif [[ -n "$app_exe" && ( -e "$app_exe" || -L "$app_exe" ) ]]; then
    if [[ -d "$app_exe" ]]; then
      app_dir="$app_exe"
    else
      app_dir="$(dirname "$app_exe")"
    fi
  fi

  # 3. Resolve application identifier
  local app_id="${CUSTOM_APP_ID:-}"
  if [[ -z "$app_id" ]]; then
    app_id="${DEFAULT_APP_ID:-sandbox-app}"
    [[ "$app_id" == "auto" ]] && app_id="sandbox-app"
  fi
  app_id="${app_id//[^a-zA-Z0-9._-]/_}"
  app_id="${app_id:-sandbox-app}"

  # 4. Initialize sandbox HOME
  local sandbox_home=""
  local home_mode="${HOME_MODE:-isolated}"
  local base_dir="${SANDBOX_BASE_DIR:-${HOME}/.local/share/bwrap-sandbox}"
  base_dir="${base_dir/#\~/$HOME}"
  local app_dir_home="${APP_DIR_HOME_NAME:-.sandbox-home}"

  if [[ "${EPHEMERAL:-false}" == "true" ]]; then
    home_mode="ephemeral"
  elif [[ -n "${CUSTOM_HOME:-}" ]]; then
    home_mode="custom"
  fi

  case "$home_mode" in
    ephemeral)
      sandbox_home=""
      ;;
    cwd)
      sandbox_home="${PWD:-}"
      ;;
    app-dir)
      if [[ -n "$app_dir" && -d "$app_dir" ]]; then
        sandbox_home="${app_dir}/${app_dir_home}"
      else
        sandbox_home="${base_dir}/${app_id}"
      fi
      ;;
    custom)
      sandbox_home="${CUSTOM_HOME:-}"
      sandbox_home="${sandbox_home/#\~/$HOME}"
      if [[ -z "$sandbox_home" ]]; then
        echo "Error: CUSTOM_HOME is empty." >&2
        exit 1
      fi
      ;;
    isolated|*)
      sandbox_home="${base_dir}/${app_id}"
      ;;
  esac

  if [[ -n "$sandbox_home" ]]; then
    mkdir -p "${sandbox_home}/.config" "${sandbox_home}/.local/share" "${sandbox_home}/.cache" 2>/dev/null || true
    BWRAP_CMD+=(--bind "$sandbox_home" "$HOME")
  else
    BWRAP_CMD+=(--tmpfs "$HOME")
  fi
  BWRAP_CMD+=(
    --setenv HOME "$HOME"
    --setenv USER "${USER:-$(id -un)}"
  )

  # 5. Mount application directory or standalone executable
  local app_dir_mode="${APP_DIR_MODE:-ro}"
  if [[ "$app_dir_mode" != "none" && -n "$app_dir" && -d "$app_dir" && "$app_dir" != "$HOME" && "$app_dir" != "/" && "$app_dir" != "/usr"* && "$app_dir" != "/bin"* && "$app_dir" != "/sbin"* && "$app_dir" != "/lib"* && "$app_dir" != "/opt"* ]]; then
    if [[ "$app_dir_mode" == "rw" ]]; then
      bwrap_bind_try "$app_dir" "$app_dir"
    elif [[ "$app_dir_mode" == "ro" ]]; then
      bwrap_ro_bind_try "$app_dir" "$app_dir"
    fi
  elif [[ -n "$app_exe" && ( -f "$app_exe" || -L "$app_exe" ) ]]; then
    bwrap_ro_bind_try "$app_exe" "$app_exe"
  fi

  # 6. Working directory and CWD mounting policy
  local cwd_mode="${CWD_MODE:-none}"
  [[ "${MOUNT_CWD:-false}" == "true" && "$cwd_mode" == "none" ]] && cwd_mode="rw"

  if [[ "${HOME_MODE:-isolated}" == "cwd" ]]; then
    BWRAP_CMD+=(--chdir "$HOME")
  elif [[ "$cwd_mode" == "rw" ]]; then
    bwrap_bind_try "$PWD" "$PWD"
    BWRAP_CMD+=(--chdir "$PWD")
  elif [[ "$cwd_mode" == "ro" ]]; then
    bwrap_ro_bind_try "$PWD" "$PWD"
    BWRAP_CMD+=(--chdir "$PWD")
  elif [[ -n "$app_dir" && -d "$app_dir" && "$app_dir_mode" != "none" ]]; then
    BWRAP_CMD+=(--chdir "$app_dir")
  else
    BWRAP_CMD+=(--chdir "$HOME")
  fi
}

bwrap_exec() {
  local -a exec_target=("$@")

  # Support interactive fallback tracing via --trace <FILE>
  if [[ -n "${TRACE_LOG:-}" ]]; then
    if ! command -v strace >/dev/null 2>&1; then
      echo "Error: --trace requires 'strace' to be installed on the system." >&2
      exit 1
    fi
    touch "$TRACE_LOG"
    local real_trace
    real_trace="$(realpath "$TRACE_LOG")"
    bwrap_bind "$real_trace" "$real_trace"
    exec_target=(strace -f -e trace=%file,%net -o "$real_trace" "${exec_target[@]}")
  fi

  if [[ "${_BWRAP_IS_NESTED:-false}" == "true" ]]; then
    if [[ "$VERBOSE" == "true" ]]; then
      echo ">>> [bwrap-sandbox] Already running inside a sandbox; skipping nested bwrap and executing directly:" >&2
      printf '%q ' "${exec_target[@]}" >&2
      echo >&2
    fi
    exec "${exec_target[@]}"
  fi

  BWRAP_CMD+=(--setenv _BWRAP_SANDBOX_ACTIVE 1)

  if [[ "$VERBOSE" == "true" ]]; then
    echo ">>> [bwrap-sandbox] Executing sandboxed command:" >&2
    printf '%q ' "${BWRAP_CMD[@]}" "${exec_target[@]}" >&2
    echo >&2
  fi

  exec "${BWRAP_CMD[@]}" "${exec_target[@]}"
}
