# ==============================================================================
# Preset [base/core.sh]: Namespace Isolation, Read-Only RootFS, Configurable HOME/CWD/AppDir & Safe Workdir
# ==============================================================================
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

# Dynamically resolve the application identifier at runtime.
# Priority:
#   1. Explicit -i/--id (CUSTOM_APP_ID)
#   2. Derived from target command binary or application directory name
#   3. Fallback to DEFAULT_APP_ID (if defined) or "sandbox-app"
bwrap_resolve_app_id() {
  local target_cmd="${1:-}"
  local app_dir="${2:-}"
  local raw_id=""

  if [[ -n "${CUSTOM_APP_ID:-}" ]]; then
    raw_id="$CUSTOM_APP_ID"
  elif [[ -n "${target_cmd:-}" && "$target_cmd" != "sandbox-app" ]]; then
    local base_name
    base_name="$(basename -- "$target_cmd")"
    base_name="$(sed -E 's/\.(exe|EXE|msi|MSI|AppImage|appimage|sh|py|jar|x86_64|x86|bin|run)$//' <<< "$base_name")"

    # If the binary name is a generic runner, use the parent application folder name
    if [[ "$base_name" =~ ^(start|launch|launcher|run|game|play|AppRun|wine|wine64|umu-run|python|python3|java|bash|sh)$ ]] && \
       [[ -n "$app_dir" && "$app_dir" != "/" && "$app_dir" != "$HOME" && "$app_dir" != "/usr" && "$app_dir" != "/bin" && "$app_dir" != "/opt" && "$app_dir" != "/sbin" ]]; then
      raw_id="$(basename -- "$app_dir")"
    else
      raw_id="$base_name"
    fi
  elif [[ -n "${DEFAULT_APP_ID:-}" && "${DEFAULT_APP_ID}" != "auto" ]]; then
    raw_id="$DEFAULT_APP_ID"
  else
    raw_id="sandbox-app"
  fi

  raw_id="${raw_id//[^a-zA-Z0-9._-]/_}"
  [[ -z "$raw_id" ]] && raw_id="sandbox-app"
  printf '%s\n' "$raw_id"
}

bwrap_setup_isolated_home() {
  local app_id="$1"
  local app_dir="${2:-}"
  local sandbox_home=""
  local home_mode="${HOME_MODE:-isolated}"
  local base_dir="${SANDBOX_BASE_DIR:-${HOME}/.local/share/bwrap-sandbox}"
  base_dir="${base_dir/#\~/$HOME}"
  local app_dir_home="${APP_DIR_HOME_NAME:-.sandbox-home}"

  # Runtime environment overrides
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
      if [[ -n "${PWD:-}" && "$PWD" != "$HOME" && "$PWD" != "/" ]]; then
        sandbox_home="$PWD"
      else
        echo "Warning: Cannot map sandbox HOME to \$PWD when \$PWD is host \$HOME or /; falling back to ephemeral tmpfs." >&2
        sandbox_home=""
      fi
      ;;
    app-dir)
      if [[ -n "$app_dir" && -d "$app_dir" && "$app_dir" != "$HOME" && "$app_dir" != "/" && "$app_dir" != "/usr"* && "$app_dir" != "/bin"* && "$app_dir" != "/opt"* ]]; then
        sandbox_home="${app_dir}/${app_dir_home}"
      else
        sandbox_home="${base_dir}/${app_id}"
      fi
      ;;
    custom)
      sandbox_home="${CUSTOM_HOME:-${DEFAULT_CUSTOM_HOME:-}}"
      sandbox_home="${sandbox_home/#\~/$HOME}"
      if [[ -z "$sandbox_home" || "$sandbox_home" == "$HOME" || "$sandbox_home" == "/" ]]; then
        echo "Error: Invalid or unsafe custom sandbox HOME directory: '${sandbox_home}'." >&2
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
}

bwrap_mount_app_directory() {
  local app_dir="${1:-}"
  local app_dir_mode="${APP_DIR_MODE:-ro}"
  local cwd_mode="${CWD_MODE:-none}"

  # 1. Mount application directory (if outside standard read-only system paths)
  if [[ -n "$app_dir" && -d "$app_dir" && "$app_dir" != "$HOME" && "$app_dir" != "/" && "$app_dir" != "/usr"* && "$app_dir" != "/bin"* && "$app_dir" != "/sbin"* && "$app_dir" != "/lib"* && "$app_dir" != "/opt"* ]]; then
    case "$app_dir_mode" in
      rw)
        bwrap_bind_try "$app_dir" "$app_dir"
        ;;
      ro)
        bwrap_ro_bind_try "$app_dir" "$app_dir"
        ;;
      none)
        ;;
    esac
  fi

  # 2. Mount current working directory ($PWD) according to CWD_MODE policy
  if [[ "$cwd_mode" != "none" ]]; then
    if [[ -n "${PWD:-}" && "$PWD" != "$HOME" && "$PWD" != "/" ]]; then
      if [[ "$cwd_mode" == "rw" ]]; then
        bwrap_bind_try "$PWD" "$PWD"
      elif [[ "$cwd_mode" == "ro" ]]; then
        bwrap_ro_bind_try "$PWD" "$PWD"
      fi
    else
      echo "Warning: Current directory is \$HOME or /; refusing to mount \$PWD automatically for least-privilege safety." >&2
    fi
  fi
}

bwrap_apply_custom_mounts() {
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

  # 4. External environment variable overrides (space/comma separated)
  if [[ -n "${EXTRA_RW_BINDS:-}" ]]; then
    local spec
    for spec in ${EXTRA_RW_BINDS//,/ }; do
      bwrap_mount_spec "bind" "$spec"
    done
  fi
  if [[ -n "${EXTRA_RO_BINDS:-}" ]]; then
    local spec
    for spec in ${EXTRA_RO_BINDS//,/ }; do
      bwrap_mount_spec "ro-bind" "$spec"
    done
  fi
  if [[ -n "${EXTRA_DEV_BINDS:-}" ]]; then
    local spec
    for spec in ${EXTRA_DEV_BINDS//,/ }; do
      bwrap_mount_spec "dev-bind" "$spec"
    done
  fi

  # Legacy compatibility for BWRAP_BINDS / BWRAP_RO_BINDS / BWRAP_DEV_BINDS
  if [[ -n "${BWRAP_BINDS:-}" ]]; then
    local spec
    for spec in ${BWRAP_BINDS//,/ }; do
      bwrap_mount_spec "bind" "$spec"
    done
  fi
  if [[ -n "${BWRAP_RO_BINDS:-}" ]]; then
    local spec
    for spec in ${BWRAP_RO_BINDS//,/ }; do
      bwrap_mount_spec "ro-bind" "$spec"
    done
  fi
  if [[ -n "${BWRAP_DEV_BINDS:-}" ]]; then
    local spec
    for spec in ${BWRAP_DEV_BINDS//,/ }; do
      bwrap_mount_spec "dev-bind" "$spec"
    done
  fi
}

bwrap_apply_custom_whitelists() {
  bwrap_apply_custom_mounts
}

bwrap_set_safe_workdir() {
  local app_dir="${1:-}"
  local cwd_mode="${CWD_MODE:-none}"
  [[ "${MOUNT_CWD:-false}" == "true" && "$cwd_mode" == "none" ]] && cwd_mode="rw"

  if [[ "${HOME_MODE:-isolated}" == "cwd" ]]; then
    BWRAP_CMD+=(--chdir "$HOME")
    return 0
  fi

  if [[ -n "${PWD:-}" && "$PWD" != "$HOME" && "$PWD" != "/" ]]; then
    if [[ -n "$app_dir" && "$PWD" == "$app_dir"* && -d "$PWD" && "${APP_DIR_MODE:-ro}" != "none" ]]; then
      BWRAP_CMD+=(--chdir "$PWD")
      return 0
    fi
    if [[ "$cwd_mode" != "none" && -d "$PWD" ]]; then
      BWRAP_CMD+=(--chdir "$PWD")
      return 0
    fi
  fi

  if [[ -n "$app_dir" && -d "$app_dir" && "$app_dir" != "$HOME" && "$app_dir" != "/" && "${APP_DIR_MODE:-ro}" != "none" ]]; then
    BWRAP_CMD+=(--chdir "$app_dir")
    return 0
  fi

  BWRAP_CMD+=(--chdir "$HOME")
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
