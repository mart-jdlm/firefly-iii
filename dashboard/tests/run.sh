#!/bin/sh
# Runs every test of the dashboard. From anywhere: dashboard/tests/run.sh
#   Python (host): the server, standard library only.
#   JavaScript (Docker, no network): the pure logic of the page, with node's built-in runner.
#   Lint (Docker, needs the network once to install ESLint): set LINT=1.
#   End-to-end in headless Chrome against the running dashboard (see e2e/e2e.sh): set E2E=1.
set -e
cd "$(dirname "$0")/.."
echo "== python =="
python3 -m unittest discover -s tests -p 'test_*.py' "$@"
echo "== javascript =="
docker run --rm --network none -v "$PWD:/d:ro" -w /d node:22-alpine sh -c 'node --test tests/js/*.test.mjs' 2>&1 | grep -E '^(not ok|# (tests|pass|fail))|^ok ' | sed 's/^ok /  ok /'
if [ -n "$LINT" ]; then
  echo "== lint =="
  cache="${TMPDIR:-/tmp}/cairn-lint"; mkdir -p "$cache"; cp tests/js/eslint.config.js "$cache/"; echo '{"type":"module"}' > "$cache/package.json"
  docker run --rm --network host -v "$cache:/l" -v "$PWD:/d:ro" -w / node:22-alpine sh -c \
    'cd /l && { [ -x node_modules/.bin/eslint ] || npm i eslint@9 globals@15 --silent --no-audit --no-fund; } >/dev/null 2>&1; cd / && /l/node_modules/.bin/eslint --no-config-lookup -c /l/eslint.config.js d/static/js d/static/sw.js && echo "  eslint: no problem"'
fi
if [ -n "$E2E" ]; then
  echo "== end-to-end =="
  "$(dirname "$0")/e2e/e2e.sh"
fi
