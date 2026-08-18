#!/bin/zsh
# Double-click launcher for strata.
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -e ".[dev]"
fi
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
open "http://localhost:${STRATA_PORT:-8020}"
exec ./.venv/bin/python -m strata.app
