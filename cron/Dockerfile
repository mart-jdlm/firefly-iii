FROM alpine:3.22

RUN apk add --no-cache supercronic tzdata mariadb-client restic rclone

COPY crontab /etc/crontab
COPY daily.sh import.sh backup.sh /usr/local/bin/

CMD ["sh", "-c", "daily.sh & exec supercronic /etc/crontab"]
