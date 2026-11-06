#!/bin/sh
# Asks the data importer to run every import config in its /import directory (bank sync).
# The importer always answers "Seems to have worked", even when the import failed (revoked token,
# bank refusing the dates...), so the verdict comes from the importer's own log, mounted at
# $IMPORTER_LOGS: any ERROR line written during this run counts as a failure, except the two
# messages an empty bank response produces. The importer e-mails its own report (new transactions,
# expired bank consent). IMPORT_HEALTHCHECK_URL, when set, gets the result (0 = fine).
set -u

LOGS=${IMPORTER_LOGS:-/importer-logs}
# Messages that are not failures: no new transaction in the period.
BENIGN='Zero transactions|Too many errors in the data conversion|Exit code is (SUCCESS|NOTHING_WAS_IMPORTED)'

newest() {
  ls -t "$LOGS"/*.log 2>/dev/null | head -n 1
}

# Log lines written since the run started, whether or not the log rolled over to a new day.
since() {
  file=$(newest)
  [ -n "$file" ] || return 0
  if [ "$file" = "$1" ]; then
    tail -n +"$(($2 + 1))" "$file"
  else
    cat "$file"
  fi
}

# Log errors that are not benign, from the lines on stdin.
failures() {
  grep -F 'production.ERROR' | grep -vE "$BENIGN"
}

if [ "${1:-}" = "--check-log" ]; then # import.sh --check-log FILE: test the verdict on a log file.
  failures < "$2"
  exit $?
fi

file_before=$(newest)
lines_before=0
[ -n "$file_before" ] && lines_before=$(wc -l < "$file_before")

response=$(wget -qO- -T 600 --post-data '' \
  "http://importer:8080/autoimport?directory=/import&secret=$AUTO_IMPORT_SECRET" 2>&1)
rc=$?
echo "$response"
case "$response" in
  *"Seems to have worked"*) ;;
  *) rc=1 ;;
esac

errors=$(since "$file_before" "$lines_before" | failures | cut -c1-300)
if [ -n "$errors" ]; then
  echo "The importer logged errors:"
  echo "$errors"
  rc=1
elif [ -z "$(newest)" ]; then
  echo "No importer log to check at $LOGS (is the importer_logs volume mounted?)"
  rc=1
fi

if [ -n "${IMPORT_HEALTHCHECK_URL:-}" ]; then
  wget -q -T 10 -O /dev/null "$IMPORT_HEALTHCHECK_URL/$rc" || echo "Could not reach healthchecks.io"
fi
exit $rc
