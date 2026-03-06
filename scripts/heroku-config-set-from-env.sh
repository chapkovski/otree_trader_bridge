#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
DRY_RUN=0
APP_NAME=""

usage() {
  echo "Usage: ./scripts/heroku-config-set-from-env.sh [--dry-run] [--app HEROKU_APP_NAME]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --app)
      APP_NAME="${2:-}"
      if [[ -z "${APP_NAME}" ]]; then
        echo "--app requires a value"
        exit 1
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}"
  exit 1
fi

if ! command -v heroku >/dev/null 2>&1; then
  echo "Heroku CLI is not installed or not on PATH."
  exit 1
fi

pairs=()
while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
  line="$(echo "${raw_line}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  if [[ -z "${line}" || "${line}" == \#* ]]; then
    continue
  fi
  if [[ "${line}" == export\ * ]]; then
    line="${line#export }"
  fi
  if [[ "${line}" != *=* ]]; then
    continue
  fi
  key="${line%%=*}"
  value="${line#*=}"
  key="$(echo "${key}" | sed 's/[[:space:]]//g')"
  if [[ -z "${key}" ]]; then
    continue
  fi
  if [[ "${value}" =~ ^\".*\"$ || "${value}" =~ ^\'.*\'$ ]]; then
    value="${value:1:${#value}-2}"
  fi
  pairs+=("${key}=${value}")
done < "${ENV_FILE}"

if [[ "${#pairs[@]}" -eq 0 ]]; then
  echo "No KEY=VALUE entries found in ${ENV_FILE}"
  exit 1
fi

cmd=(heroku config:set)
if [[ -n "${APP_NAME}" ]]; then
  cmd+=(--app "${APP_NAME}")
fi
cmd+=("${pairs[@]}")

if [[ "${DRY_RUN}" -eq 1 ]]; then
  printf 'Dry run command:\n'
  printf '%q ' "${cmd[@]}"
  printf '\n'
  exit 0
fi

"${cmd[@]}"
