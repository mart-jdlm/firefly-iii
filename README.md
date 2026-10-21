# Firefly III (self-hosted)

Docker Compose setup for a personal [Firefly III](https://www.firefly-iii.org/) instance, with the Data Importer and the Firefly Pico mobile front end.

## Services

| Service        | Image                             | Container              | URL                         |
|----------------|-----------------------------------|------------------------|-----------------------------|
| `app`          | `fireflyiii/core` (pinned)        | `firefly_iii_core`     | https://fedora.taile33049.ts.net      |
| `db`           | `mariadb` (pinned)                | `firefly_iii_db`       | internal only (port 3306)   |
| `importer`     | `fireflyiii/data-importer` (pinned) | `firefly_iii_importer` | https://fedora.taile33049.ts.net:8181 |
| `firefly-pico` | `cioraneanu/firefly-pico:dev` (digest) | `firefly_iii_pico`     | https://fedora.taile33049.ts.net:8282 |
| `cron`         | built from `cron/`                | `firefly_iii_cron`     | none (backups + daily cron) |

The services are only reachable from the Tailscale network, over HTTPS. Docker publishes their ports on `127.0.0.1` only, and [`tailscale serve`](https://tailscale.com/kb/1312/serve) proxies them:

```bash
tailscale serve --bg --https=443  http://127.0.0.1:8080   # Firefly III
tailscale serve --bg --https=8181 http://127.0.0.1:8181   # Data Importer
tailscale serve --bg --https=8282 http://127.0.0.1:8282   # Firefly Pico
tailscale serve status
```

This needs MagicDNS, HTTPS certificates and Serve enabled on the tailnet, and `sudo tailscale set --operator=$USER` once. The serve config persists across reboots. The importer and Pico talk to Firefly III directly over the Docker network (`http://app:8080`). If the machine name changes, update `APP_URL` in `.env` and `VANITY_URL` / `APP_URL` in `docker-compose.yml`.

Persistent data lives in named Docker volumes:

- `firefly_iii_db` — MariaDB data
- `firefly_upload` — attachments uploaded to Firefly III
- `pico_data` — Firefly Pico's local database

## Files

- `docker-compose.yml` — service definitions.
- `.env` — Firefly III core configuration (app key, DB connection, timezone, mail, etc.). **Not committed**; see [First-time setup](#first-time-setup).
- `.db.env` — MariaDB credentials, used by the `db` service. Must match `DB_DATABASE` / `DB_USERNAME` / `DB_PASSWORD` in `.env`. **Not committed**; copy `.db.env.example` and set a password.
- `.importer.env` — `FIREFLY_III_ACCESS_TOKEN` for the Data Importer. **Not committed.**
- `.backup.env`, `.rclone/` — restic password, Google Drive access and optional healthchecks.io URL for backups. **Not committed**; see [Off-site setup](#off-site-setup-once).
- `.enablebanking.pem` — Enable Banking private key for bank sync. **Not committed.**
- `import/` — data importer configs used by the daily bank import. **Not committed.**
- `.api.env` — `FIREFLY_TOKEN`, a personal access token for the PEA valuation. **Not committed.**
- `patrimoine/pea.txt` — PEA positions (see [PEA valuation](#pea-valuation)). **Not committed**; `patrimoine/pea.example.txt` shows the format.
- `cron/` — image, schedule, import and backup scripts for the `cron` service.

## First-time setup

1. Copy `.db.env.example` to `.db.env` and set `MYSQL_USER` / `MYSQL_PASSWORD`.
2. Get the official example config and save it as `.env`:
   ```bash
   curl -o .env https://raw.githubusercontent.com/firefly-iii/firefly-iii/main/.env.example
   ```
3. Edit `.env`:
   - `APP_KEY` — exactly 32 random characters (e.g. `head /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9' | head -c 32`).
   - `DB_HOST=db`, `DB_PORT=3306`, `DB_CONNECTION=mysql`, and `DB_DATABASE` / `DB_USERNAME` / `DB_PASSWORD` matching the `db` service.
   - `APP_URL=https://fedora.taile33049.ts.net`, `TZ` (currently `Europe/Paris`), `TRUSTED_PROXIES=**` (needed behind `tailscale serve`).
4. Start everything (and set up `tailscale serve`, see [Services](#services)):
   ```bash
   docker compose up -d
   ```
5. Open Firefly III and register the first user (it becomes the admin).
6. For the Data Importer: in Firefly III go to **Options → Profile → OAuth → Personal Access Tokens**, create a token, and put it in `.importer.env` as `FIREFLY_III_ACCESS_TOKEN=<token>`. Then `docker compose up -d importer`.
7. For Firefly Pico: open it on port 8282 and log in with a personal access token as well.

## Day-to-day

```bash
docker compose ps                    # status
docker compose logs -f app           # follow Firefly III logs
docker compose pull && docker compose up -d   # apply the versions in docker-compose.yml
docker compose restart importer      # restart a single service
docker compose down                  # stop (volumes are kept)
```

### Updates

Every image has a fixed version in `docker-compose.yml` (Pico follows its `dev` tag, pinned by digest), so `pull` never changes anything on its own. [Renovate](https://docs.renovatebot.com/) ([renovate.json](renovate.json)) opens a pull request on GitHub for each new version, on Saturday mornings. To apply one:

1. Read the release notes linked in the PR.
2. Back up: `docker exec firefly_iii_cron backup.sh`.
3. Merge the PR, then `git pull && docker compose pull && docker compose up -d`.

MariaDB has `MARIADB_AUTO_UPGRADE=1`, so its system tables are upgraded when its version changes.

### Scheduled jobs

The `cron` service (built from [cron/](cron/)) runs [cron/daily.sh](cron/daily.sh) when it starts and then every hour (`Europe/Paris` time). It runs, in order, each daily job that has not run in the last 20 hours:

1. [cron/import.sh](cron/import.sh): bank import (see [Bank sync](#bank-sync));
2. [cron/valuation.sh](cron/valuation.sh): PEA valuation (see [PEA valuation](#pea-valuation));
3. [cron/backup.sh](cron/backup.sh): backup (see [Backups](#backups));
4. Firefly III's cron endpoint, for recurring transactions, bill reminders and auto-budgets. Compose reads `STATIC_CRON_TOKEN` (32 characters) from `.env`.

So the machine does not need to be on at night: a day it was off is caught up a few minutes after it boots. A failed job is retried about 2 hours later (not hourly: the bank allows about 4 fetches a day). Timestamps of the last runs are in `backups/.state/`; delete one to force that job on the next hour.

Run them by hand:

```bash
docker exec firefly_iii_cron daily.sh       # whatever is due
docker exec firefly_iii_cron import.sh
docker exec firefly_iii_cron valuation.sh
docker exec firefly_iii_cron backup.sh
docker exec firefly_iii_cron sh -c 'wget -qO- http://app:8080/api/v1/cron/$STATIC_CRON_TOKEN'
docker logs firefly_iii_cron        # output of past runs
```

### Bill reminders by e-mail

Firefly III sends bill reminders through the `MAIL_*` settings in `.env` (Gmail SMTP: `smtp.gmail.com`, port 587, `tls`). `MAIL_PASSWORD` is a Google [app password](https://myaccount.google.com/apppasswords), not the account password. After changing it: `docker compose up -d app`, then use **Options → Preferences → Notifications → Send test message**.

## Bank sync

The Data Importer pulls transactions from the bank through [Enable Banking](https://enablebanking.com/) (free for your own accounts: a production application activated by linking your accounts, in "restricted mode"). Access is read-only.

Once a day (see [Scheduled jobs](#scheduled-jobs)) `import.sh` POSTs to the importer's `/autoimport`, which runs each config in `import/` (last 5 days; transactions already in Firefly III are recognised by the bank's ID and skipped). Rules are applied on import. The importer e-mails a report only when it has something to say: new transactions, or errors such as an expired consent.

Setup:

1. On the Enable Banking control panel, register a **production** application with redirect URL `https://<host>:8181/eb-callback`, keep the downloaded private key as `.enablebanking.pem` (mode 644: the importer runs as `www-data`), then *Activate by linking accounts*.
2. In `.importer.env`: `ENABLE_BANKING_APP_ID`, `CAN_POST_AUTOIMPORT=true`, `IMPORT_DIR_ALLOWLIST=/import`, `ENABLE_MAIL_REPORT=true` and the `MAIL_*` settings (same Gmail account as Firefly III, plus `MAIL_DESTINATION` and `MAIL_FROM_ADDRESS`). In `.env`: `AUTO_IMPORT_SECRET` (32 random characters).
3. Run one import by hand in the importer UI and download its configuration into `import/<name>.json`. Set its `date_range_number` to `5`.
4. Optional: `IMPORT_HEALTHCHECK_URL` in `.backup.env` for an alert when the daily import itself fails.

**Bank consent expires** (90 days for Crédit Agricole de Paris). To renew: run an import in the importer UI again, download the new configuration and replace the file in `import/`.

## PEA valuation

The bank only reports the PEA's cash movements, not what its holdings are worth. Each day `valuation.sh` reads the positions in `patrimoine/pea.txt` (Yahoo Finance symbol and quantity per line, plus `especes` for cash), prices them, and books the gap between that market value and the balance of the `PEA - Boursobank` account: a deposit from *Plus-values latentes* or a withdrawal to *Moins-values latentes*, category *Valorisation*, tag `valorisation`. The account balance therefore always equals the PEA's value. Contributions are still entered as usual (as transfers from the current account).

Setup:

1. In Firefly III, create a personal access token (**Options → Profile → OAuth**) and put it in `.api.env` (`chmod 600`) as `FIREFLY_TOKEN=<token>`.
2. Copy `patrimoine/pea.example.txt` to `patrimoine/pea.txt` and enter the positions. Find each symbol by searching the ISIN on [Yahoo Finance](https://finance.yahoo.com) (Paris listings end in `.PA`); only prices in euros are accepted.
3. **Before the first run**, make sure the account's balance equals the total contributed so far, so that only real gains are booked as *Plus-values latentes*.
4. `docker compose up -d --build cron`, then `docker exec firefly_iii_cron valuation.sh`.

After buying or selling, update `pea.txt` (quantities and `especes`). `PEA_POSITIONS` and `PEA_ACCOUNT` override the file and account name.

## Backups

Each day (see [Scheduled jobs](#scheduled-jobs)) `backup.sh`:

1. dumps the database to `backups/firefly_YYYY-MM-DD.sql.gz` and archives the `firefly_upload` volume to `backups/uploads_YYYY-MM-DD.tar.gz`, keeping 14 days locally;
2. if `.backup.env` sets `RESTIC_REPOSITORY`, sends both files to an encrypted [restic](https://restic.net/) repository on Google Drive (through rclone), keeping 7 daily, 4 weekly and 12 monthly snapshots.

`backups/`, `*.sql`, `*.sql.gz`, `.backup.env` and `.rclone/` are git-ignored.

### Off-site setup (once)

1. Authorize Google Drive (opens a link to visit in a browser on this machine; rclone only sees the files it creates):
   ```bash
   mkdir -p .rclone
   docker run --rm -it --user $(id -u):$(id -g) --network host -v "$PWD/.rclone":/config/rclone \
     rclone/rclone:1.71.2 config create gdrive drive scope=drive.file
   ```
2. Create `.backup.env` (`chmod 600`):
   ```
   RESTIC_REPOSITORY=rclone:gdrive:firefly-backup
   RESTIC_PASSWORD=<long random password>
   ```
   **Keep `RESTIC_PASSWORD` somewhere other than this machine (e.g. a password manager). Without it, the Drive copy cannot be decrypted.**
3. Create the repository and restart: `docker compose run --rm cron restic init && docker compose up -d cron`.

### Failure alerts (optional)

Add a healthchecks.io ping URL to `.backup.env`:

```
HEALTHCHECK_URL=https://hc-ping.com/<uuid>
```

`backup.sh` reports its exit code to it after every run. Backups run whenever the machine is on (see [Scheduled jobs](#scheduled-jobs)), not at a fixed time, so on healthchecks.io use a **simple** schedule: period 1 day, grace time 2 days. You get an e-mail when a run fails, or when no backup has happened for 3 days. Apply with `docker compose up -d cron`.

### Restore

Database, from a local dump:

```bash
gunzip -c backups/firefly_YYYY-MM-DD.sql.gz \
  | docker exec -i firefly_iii_db sh -c 'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
```

From Google Drive (needs `.rclone/` and `.backup.env`):

```bash
docker compose run --rm cron restic snapshots
docker compose run --rm cron restic restore latest --target /backups/restore
# files land in backups/restore/backups/
```

Attachments:

```bash
docker run --rm -v firefly-iii_firefly_upload:/data -v "$PWD/backups":/backup alpine \
  tar xzf /backup/uploads_YYYY-MM-DD.tar.gz -C /data
```

(The volume prefix depends on the Compose project name; check it with `docker volume ls`.)

## Security notes

- Secrets live only in the git-ignored `.env`, `.db.env`, `.importer.env`, `.backup.env` and `.rclone/`. Never put them back in `docker-compose.yml`.
- Ports 8080, 8181 and 8282 are bound to `127.0.0.1`: they are not reachable from the LAN, only through `tailscale serve`. Keep it that way.
