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
    bwrap_ro_bind_try /etc/ld.so.cache /etc/ld.so.cache
    bwrap_ro_bind_try /etc/ld.so.conf /etc/ld.so.conf
    bwrap_ro_bind_try /etc/ld.so.conf.d /etc/ld.so.conf.d
    bwrap_ro_bind_try /etc/localtime /etc/localtime
    bwrap_ro_bind_try /etc/locale.conf /etc/locale.conf
    bwrap_ro_bind_try /etc/alternatives /etc/alternatives
  else
    bwrap_ro_bind /etc /etc
    bwrap_ro_bind_try /dev/null /etc/shadow
    bwrap_ro_bind_try /dev/null /etc/gshadow
  fi

  # Handle both UsrMerge distros (/lib -> usr/lib) and split-root distros
  if [[ -L /bin || ! -d /bin ]]; then
    BWRAP_CMD+=(--symlink usr/bin /bin)
  else
    bwrap_ro_bind_try /bin /bin
  fi
  if [[ -L /sbin || ! -d /sbin ]]; then
    BWRAP_CMD+=(--symlink usr/sbin /sbin)
  else
    bwrap_ro_bind_try /sbin /sbin
  fi
  if [[ -L /lib || ! -d /lib ]]; then
    BWRAP_CMD+=(--symlink usr/lib /lib)
  else
    bwrap_ro_bind_try /lib /lib
  fi
  if [[ -L /lib64 ]]; then
    BWRAP_CMD+=(--symlink usr/lib64 /lib64)
  elif [[ -d /lib64 ]]; then
    bwrap_ro_bind_try /lib64 /lib64
  elif [[ -d /usr/lib64 ]]; then
    BWRAP_CMD+=(--symlink usr/lib64 /lib64)
  fi
  if [[ -L /lib32 ]]; then
    BWRAP_CMD+=(--symlink usr/lib32 /lib32)
  elif [[ -d /lib32 ]]; then
    bwrap_ro_bind_try /lib32 /lib32
  elif [[ -d /usr/lib32 ]]; then
    BWRAP_CMD+=(--symlink usr/lib32 /lib32)
  fi

  BWRAP_CMD+=(
    --proc /proc
    --dev /dev
  )

  bwrap_ro_bind_try /opt /opt
}

# Dynamically resolve the application identifier at runtime.
# Supports both dedicated single-app wrappers (fixed DEFAULT_APP_ID) and generic
# category wrappers (DEFAULT_APP_ID="auto", deriving app_id from runtime target).
bwrap_resolve_app_id() {
  local target_cmd="${1:-}"
  local app_dir="${2:-}"
  local raw_id=""

  if [[ -n "${CUSTOM_APP_ID:-}" ]]; then
    raw_id="$CUSTOM_APP_ID"
  elif [[ -n "${BWRAP_APP_ID:-}" ]]; then
    raw_id="$BWRAP_APP_ID"
  elif [[ -n "${DEFAULT_APP_ID:-}" && "${DEFAULT_APP_ID}" != "auto" ]]; then
    raw_id="$DEFAULT_APP_ID"
  elif [[ -n "${LUTRIS_GAME_SLUG:-}" ]]; then
    raw_id="$LUTRIS_GAME_SLUG"
  elif [[ -n "${UMU_ID:-}" ]]; then
    raw_id="$UMU_ID"
  elif [[ -n "${STEAM_COMPAT_APP_ID:-}" ]]; then
    raw_id="steam-${STEAM_COMPAT_APP_ID}"
  else
    local base_name
    base_name="$(basename "${target_cmd:-sandbox-app}")"
    base_name="$(sed -E 's/\.(exe|EXE|msi|MSI|AppImage|appimage|sh|py|jar|x86_64|x86|bin|run)$//' <<< "$base_name")"

    # If the binary name is a generic entry script/runner, use the parent application folder name
    if [[ "$base_name" =~ ^(start|launch|launcher|run|game|play|AppRun|wine|wine64|umu-run|python|python3|java|bash|sh)$ ]] && \
       [[ -n "$app_dir" && "$app_dir" != "/" && "$app_dir" != "$HOME" && "$app_dir" != "/usr"* && "$app_dir" != "/bin"* && "$app_dir" != "/opt"* ]]; then
      raw_id="$(basename "$app_dir")"
    else
      raw_id="$base_name"
    fi
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

  # Runtime environment / CLI overrides
  if [[ "${EPHEMERAL:-false}" == "true" || "${BWRAP_EPHEMERAL:-0}" == "1" ]]; then
    home_mode="ephemeral"
  elif [[ -n "${CUSTOM_HOME:-}" || -n "${BWRAP_SANDBOX_HOME:-}" ]]; then
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
        sandbox_home="${app_dir}/.sandbox-home"
      else
        sandbox_home="${HOME}/.local/share/bwrap-sandbox/${app_id}"
      fi
      ;;
    custom)
      sandbox_home="${CUSTOM_HOME:-${BWRAP_SANDBOX_HOME:-${DEFAULT_CUSTOM_HOME:-}}}"
      sandbox_home="${sandbox_home/#\~/$HOME}"
      if [[ -z "$sandbox_home" || "$sandbox_home" == "$HOME" || "$sandbox_home" == "/" ]]; then
        echo "Error: Invalid or unsafe custom sandbox HOME directory: '${sandbox_home}'." >&2
        exit 1
      fi
      ;;
    isolated|*)
      sandbox_home="${HOME}/.local/share/bwrap-sandbox/${app_id}"
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

  if [[ "${MOUNT_CWD:-false}" == "true" && "$cwd_mode" == "none" ]]; then
    cwd_mode="rw"
  fi

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

bwrap_apply_custom_whitelists() {
  if [[ -n "${BWRAP_BINDS:-}" ]]; then
    local IFS=',:'
    for path in $BWRAP_BINDS; do
      [[ -z "$path" ]] && continue
      [[ -e "$path" ]] && bwrap_bind_try "$path" "$path"
    done
  fi

  if [[ -n "${BWRAP_RO_BINDS:-}" ]]; then
    local IFS=',:'
    for path in $BWRAP_RO_BINDS; do
      [[ -z "$path" ]] && continue
      [[ -e "$path" ]] && bwrap_ro_bind_try "$path" "$path"
    done
  fi

  if [[ -n "${BWRAP_DEV_BINDS:-}" ]]; then
    local IFS=',:'
    for path in $BWRAP_DEV_BINDS; do
      [[ -z "$path" ]] && continue
      [[ -e "$path" ]] && bwrap_dev_bind_try "$path" "$path"
    done
  fi
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
