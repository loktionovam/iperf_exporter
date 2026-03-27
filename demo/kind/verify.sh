#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ -x "${ROOT_DIR}/venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/venv/bin/python"
elif [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 exec "${PYTHON_BIN}" -m pytest "${ROOT_DIR}/tests/kind/test_demo_cluster.py" -q
