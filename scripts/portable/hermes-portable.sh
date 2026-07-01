#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PORTABLE_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
HERMES_HOME="$PORTABLE_ROOT/.hermes"
export HERMES_HOME

mkdir -p \
  "$HERMES_HOME/logs" \
  "$HERMES_HOME/plugins" \
  "$HERMES_HOME/skills" \
  "$HERMES_HOME/extensions"

check_python() {
  "$@" -c 'import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)' >/dev/null 2>&1
}

if [ -x "$PORTABLE_ROOT/venv/bin/python" ] && check_python "$PORTABLE_ROOT/venv/bin/python"; then
  PYTHON="$PORTABLE_ROOT/venv/bin/python"
elif [ -x "$PORTABLE_ROOT/.venv/bin/python" ] && check_python "$PORTABLE_ROOT/.venv/bin/python"; then
  PYTHON="$PORTABLE_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1 && check_python python3; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1 && check_python python; then
  PYTHON="python"
else
  echo "Hermes portable requires Python >=3.11,<3.14." >&2
  exit 1
fi

cd "$PORTABLE_ROOT"
exec "$PYTHON" -m hermes_cli.main "$@"
