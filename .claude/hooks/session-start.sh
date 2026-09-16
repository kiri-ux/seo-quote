#!/bin/bash
# Installs everything the test suite needs. Two things bite on a fresh
# container and cost a whole session if missed:
#   1. `pip` is Python 3.11's; the tests run on 3.12. Installing with the
#      bare `pip` succeeds and changes nothing the tests can see.
#   2. The browser tests require playwright-core by absolute path,
#      /root/work/node_modules/playwright-core. Nothing puts it there.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$(dirname "$(dirname "$(readlink -f "$0")")")")}"

# 1. Python deps -- 3.12 explicitly, never the bare `pip`.
python3.12 -m pip install --quiet --break-system-packages --root-user-action=ignore -r requirements.txt

# 2. playwright-core where the browser tests look for it. Chromium itself is
#    already in the image at /opt/pw-browsers, which is the executablePath the
#    tests pass, so only the driver is missing.
mkdir -p /root/work
if [ ! -d /root/work/node_modules/playwright-core ]; then
  (cd /root/work && npm install playwright-core --silent --no-fund --no-audit)
fi

echo "[session-start] deps ready: python3.12 + playwright-core"
