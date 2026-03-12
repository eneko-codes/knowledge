#!/bin/bash
# teardown.sh — Remove the doc-indexer development environment.
#
# Usage: bash teardown.sh
#
# Removes the Python virtual environment, Node.js dependencies, and
# the Chromium browser binary installed by setup.sh. Reclaims ~300MB.
#
# After running this, setup.sh must be re-run before indexing docs again.

set -e

cd "$(dirname "$0")"

removed=0

if [ -d ".venv" ]; then
    rm -rf .venv
    echo "Removed Python venv (.venv/)"
    removed=$((removed + 1))
fi

if [ -d "node_modules" ]; then
    rm -rf node_modules
    echo "Removed Node.js dependencies (node_modules/)"
    removed=$((removed + 1))
fi

# Playwright stores Chromium in ~/.cache/ms-playwright/
if [ -d "$HOME/.cache/ms-playwright" ]; then
    rm -rf "$HOME/.cache/ms-playwright"
    echo "Removed Chromium browser (~/.cache/ms-playwright/)"
    removed=$((removed + 1))
fi

if [ "$removed" -eq 0 ]; then
    echo "Nothing to remove — environment already clean."
else
    echo "Removed $removed items. Run setup.sh to reinstall."
fi
