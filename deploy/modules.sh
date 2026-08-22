#!/usr/bin/env bash
# Trusted implementations for names allowed by update_policy.json.

run_auto_module() {
  local module=$1
  case "${module}" in
    application)
      # The updater always copies and installs the application before this hook.
      ;;
    python-environment)
      "${VENV_DIR}/bin/pip" install --upgrade pip
      "${VENV_DIR}/bin/pip" install "${INSTALL_DIR}"
      ;;
    systemd)
      install -m 0644 "${repository}/${SERVICE_SOURCE}" "${SERVICE_DESTINATION}"
      systemctl daemon-reload
      ;;
    *)
      echo "Refusing unknown automatic module: ${module}" >&2
      return 1
      ;;
  esac
}

run_reprocess_module() {
  local module=$1
  shift
  case "${module}" in
    profiles)
      local mode
      case "${1:-}" in
        --mode=sync) mode=sync ;;
        --mode=adopt) mode=adopt ;;
        --mode=reseed) mode=reseed ;;
        *) echo "Refusing unknown profiles flag: ${1:-}" >&2; return 1 ;;
      esac
      "${VENV_DIR}/bin/profiler" --env-file "${ENVIRONMENT_FILE}" "${mode}"
      ;;
    *)
      echo "Refusing unknown reprocess module: ${module}" >&2
      return 1
      ;;
  esac
}
