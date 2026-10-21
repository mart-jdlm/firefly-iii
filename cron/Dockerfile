FROM alpine:3.22

RUN apk add --no-cache supercronic tzdata mariadb-client restic rclone jq

COPY crontab /etc/crontab
COPY daily.sh import.sh valuation.sh backup.sh /usr/local/bin/

CMD ["sh", "-c", "daily.sh & exec supercronic /etc/crontab"]
