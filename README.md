# Firefly III (self-hosted)

Docker Compose setup for a personal [Firefly III](https://www.firefly-iii.org/) instance, with the Data Importer and the Firefly Pico mobile front end.

## Services

| Service        | Image                             | Container              | URL                         |
|----------------|-----------------------------------|------------------------|-----------------------------|
| `app`          | `fireflyiii/core:latest`          | `firefly_iii_core`     | http://100.92.223.17:8080   |
| `db`           | `mariadb:lts`                     | `firefly_iii_db`       | internal only (port 3306)   |
| `importer`     | `fireflyiii/data-importer:latest` | `firefly_iii_importer` | http://100.92.223.17:8181   |
| `firefly-pico` | `cioraneanu/firefly-pico:dev`     | `firefly_iii_pico`     | http://100.92.223.17:8282   |
| `cron`         | `alpine:3.22`                     | `firefly_iii_cron`     | none (calls `app` daily)    |

`100.92.223.17` is the host's address on the private network (a Tailscale-range IP). Change it in `docker-compose.yml` and `.env` (`APP_URL`) if the host moves.

Persistent data lives in named Docker volumes:

- `firefly_iii_db` — MariaDB data
- `firefly_upload` — attachments uploaded to Firefly III
- `pico_data` — Firefly Pico's local database

## Files

- `docker-compose.yml` — service definitions.
- `.env` — Firefly III core configuration (app key, DB connection, timezone, mail, etc.). **Not committed**; see [First-time setup](#first-time-setup).
- `.db.env` — MariaDB credentials, used by the `db` service. Must match `DB_DATABASE` / `DB_USERNAME` / `DB_PASSWORD` in `.env`. **Not committed**; copy `.db.env.example` and set a password.
- `.importer.env` — `FIREFLY_III_ACCESS_TOKEN` for the Data Importer. **Not committed.**

## First-time setup

1. Copy `.db.env.example` to `.db.env` and set `MYSQL_USER` / `MYSQL_PASSWORD`.
2. Get the official example config and save it as `.env`:
   ```bash
   curl -o .env https://raw.githubusercontent.com/firefly-iii/firefly-iii/main/.env.example
   ```
3. Edit `.env`:
   - `APP_KEY` — exactly 32 random characters (e.g. `head /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9' | head -c 32`).
   - `DB_HOST=db`, `DB_PORT=3306`, `DB_CONNECTION=mysql`, and `DB_DATABASE` / `DB_USERNAME` / `DB_PASSWORD` matching the `db` service.
   - `APP_URL`, `TZ` (currently `America/Toronto`), `TRUSTED_PROXIES=**`.
4. Start everything:
   ```bash
   docker compose up -d
   ```
5. Open Firefly III on port 8080 and register the first user (it becomes the admin).
6. For the Data Importer: in Firefly III go to **Options → Profile → OAuth → Personal Access Tokens**, create a token, and put it in `.importer.env` as `FIREFLY_III_ACCESS_TOKEN=<token>`. Then `docker compose up -d importer`.
7. For Firefly Pico: open port 8282 and log in with a personal access token as well.

## Day-to-day

```bash
docker compose ps                    # status
docker compose logs -f app           # follow Firefly III logs
docker compose pull && docker compose up -d   # update all images
docker compose restart importer      # restart a single service
docker compose down                  # stop (volumes are kept)
```

`app` and `importer` use `:latest` and Pico uses `:dev`, so `pull` can bring breaking changes. Back up before updating.

### Recurring transactions / cron

Firefly III needs a daily cron call for recurring transactions, bill reminders and auto-budgets. The `cron` service calls `http://app:8080/api/v1/cron/<STATIC_CRON_TOKEN>` every day at 03:00 (America/Toronto). Compose reads `STATIC_CRON_TOKEN` (32 characters) from `.env`.

Run it by hand:

```bash
docker exec firefly_iii_cron sh -c 'wget -qO- http://app:8080/api/v1/cron/$STATIC_CRON_TOKEN'
```

## Backups

`*.sql`, `*.sql.gz` and `backups/` are git-ignored, so dumps can be kept in this folder.

Back up the database:

```bash
mkdir -p backups
docker exec firefly_iii_db sh -c 'mariadb-dump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
  | gzip > backups/firefly_$(date +%F).sql.gz
```

Restore:

```bash
gunzip -c backups/firefly_YYYY-MM-DD.sql.gz \
  | docker exec -i firefly_iii_db sh -c 'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
```

Attachments are in the `firefly_upload` volume and are not in the SQL dump:

```bash
docker run --rm -v firefly-iii_firefly_upload:/data -v "$PWD/backups":/backup alpine \
  tar czf /backup/uploads_$(date +%F).tar.gz -C /data .
```

(The volume prefix depends on the Compose project name; check it with `docker volume ls`.)

## Security notes

- Secrets live only in the git-ignored `.env`, `.db.env` and `.importer.env`. Never put them back in `docker-compose.yml`.
- Ports 8080, 8181 and 8282 are published on every interface on the host. Use a firewall or bind them to the private IP (e.g. `"100.92.223.17:8080:8080"`) if the host is reachable from the internet.
