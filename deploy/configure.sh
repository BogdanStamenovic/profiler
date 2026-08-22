#!/usr/bin/env bash
# Seed the environment file and start the service. Run after deploy/install.sh.
set -euo pipefail

[[ ${EUID} -eq 0 ]] || { echo "Run this with sudo." >&2; exit 1; }
[[ -f deploy/project.conf ]] || { echo "Missing deploy/project.conf." >&2; exit 1; }
# shellcheck source=/dev/null
source deploy/project.conf
[[ -f ${REPOSITORY_MARKER} ]] || {
  echo "Run from the configured application repository root." >&2; exit 1;
}
[[ -x ${VENV_DIR}/bin/profiler ]] || { echo "Run deploy/install.sh first." >&2; exit 1; }

operator=${SUDO_USER:-root}
operator_home=$(getent passwd "${operator}" | cut -d: -f6)
[[ -n ${operator_home} ]] || {
  echo "Cannot determine the home directory of ${operator}." >&2; exit 1;
}
key_pattern=$(python3 -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["environment_key_pattern"])' \
  deploy/update_policy.json)

if [[ ! -s ${ENVIRONMENT_FILE} ]]; then
  install -m 0600 deploy/profiler.env.example "${ENVIRONMENT_FILE}"
  "${VENV_DIR}/bin/python" deploy/update_env.py set "${ENVIRONMENT_FILE}" \
    PROFILER_HOMES "${operator_home}" --key-pattern "${key_pattern}"
  "${VENV_DIR}/bin/python" deploy/update_env.py set "${ENVIRONMENT_FILE}" \
    PROFILER_STATE_DIR "${DATA_DIR}" --key-pattern "${key_pattern}"
  echo "Wrote ${ENVIRONMENT_FILE} with PROFILER_HOMES=${operator_home}."
else
  echo "Keeping the existing ${ENVIRONMENT_FILE}."
fi

systemctl enable --now "${SERVICE_NAME}"
systemctl --no-pager --full status "${SERVICE_NAME}" || true
cat <<EOF

${APP_NAME} is watching the profiles in ${operator_home}.
Merge what both profiles already hold, once:
  sudo ${VENV_DIR}/bin/profiler --env-file ${ENVIRONMENT_FILE} adopt
Add more accounts by editing PROFILER_HOMES in ${ENVIRONMENT_FILE}.
EOF
