#!/bin/sh
# Asks the data importer to run every import config in its /import directory (bank sync).
# The importer e-mails its own report (errors, expired bank consent); this script only checks
# that the run happened, and reports to IMPORT_HEALTHCHECK_URL when that is set.
set -u

response=$(wget -qO- -T 600 --post-data '' \
  "http://importer:8080/autoimport?directory=/import&secret=$AUTO_IMPORT_SECRET" 2>&1)
rc=$?
echo "$response"
case "$response" in
  *"Seems to have worked"*) ;;
  *) rc=1 ;;
esac

if [ -n "${IMPORT_HEALTHCHECK_URL:-}" ]; then
  wget -q -T 10 -O /dev/null "$IMPORT_HEALTHCHECK_URL/$rc" || echo "Could not reach healthchecks.io"
fi
exit $rc
