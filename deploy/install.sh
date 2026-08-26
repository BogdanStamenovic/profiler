#!/usr/bin/env bash
set -euo pipefail

[[ ${EUID} -eq 0 ]] || { echo "Run this installer with sudo." >&2; exit 1; }
[[ -f deploy/project.conf ]] || {
  echo "Copy deploy/project.conf.example to deploy/project.conf and customize it." >&2
  exit 1
}
# shellcheck source=/dev/null
source deploy/project.conf
[[ -f ${REPOSITORY_MARKER} && -f deploy/update.sh ]] || {
  echo "Run from the configured application repository root." >&2; exit 1;
}

if ! getent group "${SERVICE_GROUP}" >/dev/null; then
  groupadd --system "${SERVICE_GROUP}"
fi
if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --gid "${SERVICE_GROUP}" --home-dir "${INSTALL_DIR}" \
    --shell /usr/sbin/nologin "${SERVICE_USER}"
fi
install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" "${INSTALL_DIR}" "${DATA_DIR}"
# The unit lists BACKUP_ROOT in ReadWritePaths without a leading "-", so systemd
# refuses to build the mount namespace until it exists. Updates create it too, but
# an installation that is never updated would never start. 0700 matches update.sh.
install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0700 "${BACKUP_ROOT}"
cp -a . "${INSTALL_DIR}/"
python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install "${INSTALL_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INSTALL_DIR}" "${DATA_DIR}"
install -m 0644 "${SERVICE_SOURCE}" "${SERVICE_DESTINATION}"
if [[ ! -f ${ENVIRONMENT_FILE} ]]; then
  install -m 0600 /dev/null "${ENVIRONMENT_FILE}"
  echo "Created ${ENVIRONMENT_FILE}; add the application's initial settings."
fi
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
if revision=$(git rev-parse HEAD 2>/dev/null); then
  printf '%s\n' "${revision}" > "${STATE_FILE}"
  chown "${SERVICE_USER}:${SERVICE_GROUP}" "${STATE_FILE}"
fi
echo "Installed. Configure ${ENVIRONMENT_FILE}, then start ${SERVICE_NAME}."

