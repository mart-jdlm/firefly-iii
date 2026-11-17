#!/bin/sh
# End-to-end check of the RUNNING dashboard in headless Chrome (Docker image of Playwright, ~1 GB
# pulled once). Needs the network the first time (npm install of Playwright).
#   dashboard/tests/e2e/e2e.sh --save   record the current look as the baseline (before a refactor)
#   dashboard/tests/e2e/e2e.sh          check, and compare with the baseline (after the refactor)
# The baseline holds the texts of your pages, so it contains your figures: keep it private. It goes
# stale as your data changes: record a new one right before the change you want to verify.
# CAIRN_URL (default http://127.0.0.1:8787) points at another instance.
set -e
cd "$(dirname "$0")/../.."
cache="${TMPDIR:-/tmp}/cairn-e2e"; mkdir -p "$cache"; echo '{}' > "$cache/package.json"
[ "$1" = "--save" ] && mode=save || mode=""
docker run --rm --network host --ipc=host -e CAIRN_URL -e NODE_PATH=/l/node_modules -v "$cache:/l" -v "$PWD:/d" -w /l \
  mcr.microsoft.com/playwright:v1.50.0-noble sh -c \
  '[ -d node_modules/playwright ] || npm i playwright@1.50.0 --silent --no-audit --no-fund >/dev/null 2>&1; node /d/tests/e2e/snap.js '"$mode"
