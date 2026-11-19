#!/usr/bin/env bash
# SmallBiz Finance Agent — one-click start for macOS / Linux.
# macOS: double-click start.command in Finder.  Linux: ./start.sh
set -euo pipefail
cd "$(dirname "$0")"

PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && \
     "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/"
  [ "$(uname)" = "Darwin" ] && open "https://www.python.org/downloads/"
  read -r -p "Press Enter to close..." _ || true
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "First-time setup: creating a private Python environment..."
  "$PY" -m venv .venv
fi

exec .venv/bin/python launch.py "$@"
