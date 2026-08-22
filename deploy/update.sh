#!/usr/bin/env bash
set -euo pipefail

original_arguments=("$@")
if [[ -n ${AUTOCHANGER_BOOTSTRAP_SCRIPT:-} ]]; then
  rm -f "${AUTOCHANGER_BOOTSTRAP_SCRIPT}"
  unset AUTOCHANGER_BOOTSTRAP_SCRIPT
fi
[[ ${EUID} -eq 0 ]] || { echo "Run this updater with sudo." >&2; exit 1; }
[[ -f deploy/project.conf ]] || { echo "Missing deploy/project.conf." >&2; exit 1; }
# shellcheck source=/dev/null
source deploy/project.conf
[[ -f ${REPOSITORY_MARKER} && -f deploy/update_plan.py ]] || {
  echo "Run from the configured application repository root." >&2; exit 1;
}
[[ -f ${ENVIRONMENT_FILE} ]] || { echo "Run deploy/install.sh first." >&2; exit 1; }

repository=$(pwd -P)
git_owner=${SUDO_USER:-root}
plan_only=false
target_name='@{upstream}'
replay_commit=''
while [[ $# -gt 0 ]]; do
  case "$1" in
    --plan-only) plan_only=true; shift ;;
    --target) target_name=${2:?--target requires a ref}; shift 2 ;;
    --replay-commit) replay_commit=${2:?--replay-commit requires a ref}; shift 2 ;;
    *) echo "Usage: sudo bash deploy/update.sh [--plan-only] [--target REF]" >&2
       echo "       sudo bash deploy/update.sh --replay-commit REF [--plan-only]" >&2
       exit 1 ;;
  esac
done
run_git() {
  if [[ ${git_owner} == root ]]; then git -C "${repository}" "$@"
  else sudo -u "${git_owner}" git -C "${repository}" "$@"; fi
}
[[ -z $(run_git status --porcelain) ]] || {
  echo "Repository has uncommitted changes; commit or stash them." >&2; exit 1;
}
run_git fetch --prune
target_revision=$(run_git rev-parse "${target_name}")
[[ -f ${STATE_FILE} ]] || { echo "Missing deployed revision; run install.sh once." >&2; exit 1; }
current_revision=$(<"${STATE_FILE}")
source_revision=$(run_git rev-parse HEAD)
if [[ -z ${replay_commit} && ${source_revision} != "${target_revision}" \
  && ${AUTOCHANGER_UPDATE_REEXEC:-} != "${target_revision}" ]]; then
  bootstrap_script=$(mktemp)
  run_git show "${target_revision}:deploy/update.sh" > "${bootstrap_script}"
  chmod 0700 "${bootstrap_script}"
  AUTOCHANGER_BOOTSTRAP_SCRIPT=${bootstrap_script} \
    AUTOCHANGER_UPDATE_REEXEC=${target_revision} \
    exec bash "${bootstrap_script}" "${original_arguments[@]}"
fi
if [[ -n ${replay_commit} ]]; then
  replay_revision=$(run_git rev-parse "${replay_commit}^{commit}")
  plan_from=$(run_git rev-parse "${replay_revision}^")
  plan_to=${replay_revision}
  target_revision=${current_revision}
else
  plan_from=${current_revision}; plan_to=${target_revision}
fi
if [[ -z ${replay_commit} && ${current_revision} == "${target_revision}" ]]; then
  echo "${APP_NAME} is already up to date at ${target_revision:0:12}."; exit 0
fi
if [[ -z ${replay_commit} ]] && \
  ! run_git merge-base --is-ancestor "${current_revision}" "${target_revision}"; then
  echo "Remote update is not a fast-forward from deployed revision." >&2; exit 1
fi

work=$(mktemp -d)
service_stopped=false
cleanup() {
  code=$?
  rm -rf "${work}"
  if [[ ${code} -ne 0 && ${service_stopped} == true ]]; then
    echo "Update failed; restarting existing service." >&2
    systemctl start "${SERVICE_NAME}" || true
  fi
  exit "${code}"
}
trap cleanup EXIT
if [[ -n ${replay_commit} ]]; then
  cp deploy/update_plan.py "${work}/update_plan.py"
  cp deploy/update_policy.json "${work}/update_policy.json"
else
  run_git show "${plan_to}:deploy/update_plan.py" > "${work}/update_plan.py"
  run_git show "${plan_to}:deploy/update_policy.json" > "${work}/update_policy.json"
fi
plan=(python3 "${work}/update_plan.py" "${repository}" "${plan_from}" "${plan_to}"
  --policy "${work}/update_policy.json")
for field in automatic_modules summaries user_actions reprocess add_env; do
  "${plan[@]}" --field "${field}" > "${work}/${field}"
done
mapfile -t automatic_modules < "${work}/automatic_modules"
mapfile -t summaries < "${work}/summaries"
mapfile -t user_actions < "${work}/user_actions"
mapfile -t reprocess_jobs < "${work}/reprocess"
mapfile -t add_env_entries < "${work}/add_env"
echo "Updating ${current_revision:0:12} -> ${target_revision:0:12}"
echo "Automatic modules: ${automatic_modules[*]}"
if [[ ${#summaries[@]} -gt 0 ]]; then printf 'Update: %s\n' "${summaries[@]}"; fi
if [[ ${#reprocess_jobs[@]} -gt 0 ]]; then printf 'Reprocess: %s\n' "${reprocess_jobs[@]}"; fi
if [[ ${#add_env_entries[@]} -gt 0 ]]; then
  echo "Environment entries to confirm:"
  for item in "${add_env_entries[@]}"; do echo "  - ${item%%=*}"; done
fi
if ${plan_only}; then
  if [[ ${#user_actions[@]} -gt 0 ]]; then printf 'User action: %s\n' "${user_actions[@]}"
  else echo "No user actions declared."; fi
  exit 0
fi
[[ -n ${replay_commit} ]] || run_git merge --ff-only "${target_revision}"

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir=${BACKUP_ROOT}/${timestamp}-${current_revision:0:12}
install -d -m 0700 "${backup_dir}/data"
cp -a "${ENVIRONMENT_FILE}" "${backup_dir}/environment"
installed_dotenv=false
if [[ -f ${INSTALL_DIR}/.env ]]; then
  cp -a "${INSTALL_DIR}/.env" "${backup_dir}/installed.env"; installed_dotenv=true
fi
env_pattern=$(python3 -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["environment_key_pattern"])' \
  "${work}/update_policy.json")
for declaration in "${add_env_entries[@]}"; do
  key=${declaration%%=*}; default=${declaration#*=}; current=''; has_current=false
  if current=$(python3 deploy/update_env.py get "${ENVIRONMENT_FILE}" "${key}" \
    --key-pattern "${env_pattern}"); then has_current=true; fi
  sensitive=false
  [[ ${key} =~ (KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL) ]] && sensitive=true
  if ${has_current}; then
    if ${sensitive}; then read -r -s -p "${key} is set; replacement or Enter to keep: " value </dev/tty; echo >/dev/tty
    else read -r -p "${key} [${current}]: " value </dev/tty; fi
    value=${value:-${current}}
  elif [[ ${default} == '$input' ]]; then
    value=''
    while [[ -z ${value} ]]; do
      if ${sensitive}; then read -r -s -p "Enter ${key}: " value </dev/tty; echo >/dev/tty
      else read -r -p "Enter ${key}: " value </dev/tty; fi
    done
  else
    read -r -p "${key} [${default}]: " value </dev/tty; value=${value:-${default}}
  fi
  python3 deploy/update_env.py set "${ENVIRONMENT_FILE}" "${key}" "${value}" \
    --key-pattern "${env_pattern}"
done

systemctl stop "${SERVICE_NAME}"; service_stopped=true
cp -a "${DATA_DIR}/." "${backup_dir}/data/"
environment_checksum=$(sha256sum "${ENVIRONMENT_FILE}" | cut -d ' ' -f 1)
if [[ -z ${replay_commit} ]]; then
  cp -a "${repository}/." "${INSTALL_DIR}/"
  ${installed_dotenv} && cp -a "${backup_dir}/installed.env" "${INSTALL_DIR}/.env"
  "${VENV_DIR}/bin/pip" install "${INSTALL_DIR}"
  chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${INSTALL_DIR}" "${DATA_DIR}"
  # shellcheck source=/dev/null
  source deploy/modules.sh
  for module in "${automatic_modules[@]}"; do run_auto_module "${module}"; done
else
  # shellcheck source=/dev/null
  source deploy/modules.sh
fi
for job in "${reprocess_jobs[@]}"; do
  read -r -a tokens <<< "${job}"
  run_reprocess_module "${tokens[@]}"
done
if [[ ${environment_checksum} != "$(sha256sum "${ENVIRONMENT_FILE}" | cut -d ' ' -f 1)" ]]; then
  cp -a "${backup_dir}/environment" "${ENVIRONMENT_FILE}"
  echo "Environment changed unexpectedly and was restored." >&2; exit 1
fi
if [[ -z ${replay_commit} ]]; then
  printf '%s\n' "${target_revision}" > "${STATE_FILE}"
  chown "${SERVICE_USER}:${SERVICE_GROUP}" "${STATE_FILE}"
fi
systemctl restart "${SERVICE_NAME}"; service_stopped=false
systemctl --no-pager --full status "${SERVICE_NAME}"
echo "Backup: ${backup_dir}"
if [[ ${#user_actions[@]} -gt 0 ]]; then printf 'Required user action: %s\n' "${user_actions[@]}"
else echo "No user actions required."; fi
