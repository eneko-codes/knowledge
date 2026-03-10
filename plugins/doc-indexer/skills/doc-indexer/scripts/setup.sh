#!/bin/bash
# setup.sh — One-time environment setup for doc-indexer scripts.
#
# Creates an isolated Python virtual environment in .venv/, installs all
# Python dependencies, downloads the Chromium browser binary, and installs
# the Node.js dependency (Defuddle) for content extraction.
#
# This script is idempotent — safe to run multiple times.
#
# After running this script, activate the venv with:
#   source .venv/bin/activate
#
# Requirements:
#   - Python 3.8+
#   - Node.js 18+ (for Defuddle content extraction)
#   - ~200MB disk space for Chromium browser download
#   - Internet connection for pip install, npm install, and Playwright browser download

set -e

cd "$(dirname "$0")"

# --- Python environment ---

python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies:
#   - playwright:         Browser automation (used by crawl.py and verify.py)
#   - playwright-stealth: Anti-fingerprint patches to bypass bot detection
pip install -r requirements.txt

# Download the Chromium browser binary for Playwright (~200MB one-time).
playwright install chromium

# --- Node.js environment ---

# Check that Node.js is available (required for Defuddle content extraction)
if ! command -v node &> /dev/null; then
    echo "ERROR: Node.js is required but not found."
    echo "Install Node.js 18+ from https://nodejs.org/ and re-run this script."
    exit 1
fi

# Install Defuddle — the primary content extraction engine.
# Multi-pass content detection with code block standardization
# (language detection, line number removal, toolbar cleanup).
npm install

echo ""
echo "Setup complete."
echo "  Python venv: source .venv/bin/activate"
echo "  Node.js deps: $(node -e 'console.log(require("./node_modules/defuddle/package.json").version)' 2>/dev/null || echo 'installed')"
