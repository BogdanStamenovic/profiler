#!/usr/bin/env bash
# Remove the systemd deployment. State, backups and the environment file survive
# unless --purge is given.
set -euo pipefail

purge=false
keep_blocks=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge) purge=true; shift ;;
    --keep-blocks) keep_blocks=true; shift ;;
    *) echo "Usage: sudo bash deploy/uninstall.sh [--purge] [--keep-blocks]" >&2; exit 1 ;;
  esac
done

[[ ${EUID} -eq 0 ]] || { echo "Run this with sudo." >&2; exit 1; }
[[ -f deploy/project.conf ]] || { echo "Missing deploy/project.conf." >&2; exit 1; }
# shellcheck source=/dev/null
source deploy/project.conf

require_safe_path() {
  local label=$1 value=$2
  case "${value}" in
    ''|'/'|'/usr'|'/etc'|'/var'|'/opt'|'/home')
      echo "Refusing to remove ${label}=${value}." >&2; exit 1 ;;
  esac
}
require_safe_path INSTALL_DIR "${INSTALL_DIR}"
require_safe_path DATA_DIR "${DATA_DIR}"
require_safe_path BACKUP_ROOT "${BACKUP_ROOT}"

# Take the managed block back out of every profile before the application goes away;
# afterwards there would be nothing left that knows how to find them.
if ! ${keep_blocks} && [[ -x ${VENV_DIR}/bin/profiler && -f ${ENVIRONMENT_FILE} ]]; then
  "${VENV_DIR}/bin/profiler" --env-file "${ENVIRONMENT_FILE}" cleanup ||
    echo "Managed blocks were left in place; remove them with 'profiler cleanup'." >&2
fi

systemctl disable --now "${SERVICE_NAME}" 2>/dev/null || true
rm -f "${SERVICE_DESTINATION}"
systemctl daemon-reload
rm -rf "${INSTALL_DIR}"

if ${purge}; then
  rm -rf "${DATA_DIR}" "${BACKUP_ROOT}"
  rm -f "${ENVIRONMENT_FILE}"
  echo "Removed ${APP_NAME} along with its state, its backups and ${ENVIRONMENT_FILE}."
else
  echo "Removed ${APP_NAME}. Kept ${DATA_DIR}, ${BACKUP_ROOT} and ${ENVIRONMENT_FILE}."
  echo "Pass --purge to remove those as well."
fi
