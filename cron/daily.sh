#!/bin/sh
# Runs the daily jobs in order (bank import, backup, Firefly III cron), each at most once every
# 20 hours. It is started with the container and every hour, so a day missed while the machine
# was off is caught up as soon as it is back on. A failed job is retried about 2 hours later.
set -u

STATE=/backups/.state
mkdir -p "$STATE"

# One run at a time (container start and the hourly schedule can overlap).
exec 9>"$STATE/.lock"
flock -n 9 || exit 0

due() {
  [ -z "$(find "$STATE/$1" -mmin -1200 2>/dev/null)" ]
}

run() {
  name=$1
  shift
  due "$name" || return 0
  echo "== $name"
  if "$@"; then
    touch "$STATE/$name"
  else
    echo "$name failed, retrying in about 2 hours"
    # Pretend it ran 18 hours ago, so it is due again in 2.
    touch -d "$(date -d "@$(($(date +%s) - 64800))" '+%Y-%m-%d %H:%M:%S')" "$STATE/$name"
  fi
}

firefly_cron() {
  wget -qO- "http://app:8080/api/v1/cron/$STATIC_CRON_TOKEN" && echo
}

# After a boot, give Firefly III and the importer up to 10 minutes to come up.
for _ in $(seq 60); do
  wget -q -T 5 -O /dev/null http://app:8080/login && wget -q -T 5 -O /dev/null http://importer:8080/ && break
  sleep 10
done

run import /usr/local/bin/import.sh
run backup /usr/local/bin/backup.sh
run firefly firefly_cron

chown -R "${BACKUP_OWNER:-root}" "$STATE"
