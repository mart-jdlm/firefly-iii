FROM alpine:3.22

RUN apk add --no-cache supercronic tzdata mariadb-client restic rclone

COPY crontab /etc/crontab
COPY backup.sh /usr/local/bin/backup.sh
COPY import.sh /usr/local/bin/import.sh

CMD ["supercronic", "/etc/crontab"]
