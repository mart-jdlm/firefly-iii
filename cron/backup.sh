#!/bin/sh
# Dumps the database and, if there are any, archives attachments into /backups (kept $KEEP_DAYS days),
# then checks that the files can be read back.
# Optional: HEALTHCHECK_URL (healthchecks.io ping URL) to get alerted when a run fails or is missed.
set -eu -o pipefail

# On exit: hand the results back to the host user (this runs as root to read attachments),
# then report the exit code to healthchecks.io when HEALTHCHECK_URL is set.
on_exit() {
  rc=$?
  rm -f /backups/*.tmp
  chown -R "${BACKUP_OWNER:-root}" /backups
  if [ -n "${HEALTHCHECK_URL:-}" ]; then
    wget -q -T 10 -O /dev/null "$HEALTHCHECK_URL/$rc" || echo "Could not reach healthchecks.io"
  fi
  exit $rc
}
trap on_exit EXIT

date=$(date +%F)
db="/backups/firefly_$date.sql.gz"
uploads="/backups/uploads_$date.tar.gz"

echo "Dumping database to $db"
mariadb-dump -h db -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" --single-transaction "$MYSQL_DATABASE" | gzip > "$db.tmp"
gzip -t "$db.tmp"
mv "$db.tmp" "$db"

# Attachments: only archive when there is at least one file (an empty volume gives a useless archive).
if [ -n "$(find /uploads -mindepth 1 -type f -print -quit)" ]; then
  echo "Archiving attachments to $uploads"
  tar czf "$uploads.tmp" -C /uploads .
  tar tzf "$uploads.tmp" > /dev/null
  mv "$uploads.tmp" "$uploads"
else
  echo "No attachments: skipping the uploads archive"
fi

find /backups -maxdepth 1 \( -name 'firefly_*.sql.gz' -o -name 'uploads_*.tar.gz' \) -mtime +"${KEEP_DAYS:-14}" -delete

echo "Backup done"
