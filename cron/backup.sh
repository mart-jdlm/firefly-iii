#!/bin/sh
# Dumps the database and archives attachments into /backups (kept $KEEP_DAYS days),
# then pushes them to the restic repository ($RESTIC_REPOSITORY) when one is configured.
# Optional: HEALTHCHECK_URL (healthchecks.io ping URL) to get alerted when a run fails or is missed.
set -eu -o pipefail

# On exit: hand the results back to the host user (this runs as root to read attachments),
# then report the exit code to healthchecks.io when HEALTHCHECK_URL is set.
on_exit() {
  rc=$?
  rm -f /backups/*.tmp
  chown -R "${BACKUP_OWNER:-root}" /backups /config/rclone
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
mv "$db.tmp" "$db"

echo "Archiving attachments to $uploads"
tar czf "$uploads.tmp" -C /uploads .
mv "$uploads.tmp" "$uploads"

find /backups -maxdepth 1 \( -name 'firefly_*.sql.gz' -o -name 'uploads_*.tar.gz' \) -mtime +"${KEEP_DAYS:-14}" -delete

if [ -z "${RESTIC_REPOSITORY:-}" ]; then
  echo "No RESTIC_REPOSITORY, skipping off-site copy"
  exit 0
fi

echo "Sending to $RESTIC_REPOSITORY"
restic backup --host firefly --tag nightly "$db" "$uploads"
restic forget --host firefly --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune
echo "Backup done"
