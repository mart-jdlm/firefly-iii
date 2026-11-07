# Firefly III (self-hosted)

Docker Compose setup for a personal [Firefly III](https://www.firefly-iii.org/) instance, with the Data Importer and the Firefly Pico mobile front end.

## Services

| Service        | Image                             | Container              | URL                         |
|----------------|-----------------------------------|------------------------|-----------------------------|
| `app`          | `fireflyiii/core` (pinned)        | `firefly_iii_core`     | https://$TS_HOST      |
| `db`           | `mariadb` (pinned)                | `firefly_iii_db`       | internal only (port 3306)   |
| `importer`     | `fireflyiii/data-importer` (pinned) | `firefly_iii_importer` | https://$TS_HOST:8181 |
| `firefly-pico` | `cioraneanu/firefly-pico:dev` (digest) | `firefly_iii_pico`     | https://$TS_HOST:8282 |
| `cron`         | built from `cron/`                | `firefly_iii_cron`     | none (backups + daily cron) |
| `assistant`    | built from `assistant/`           | started by Claude Code | none (MCP over stdio)       |

The services are only reachable from the Tailscale network, over HTTPS. Docker publishes their ports on `127.0.0.1` only, and [`tailscale serve`](https://tailscale.com/kb/1312/serve) proxies them:

```bash
tailscale serve --bg --https=443  http://127.0.0.1:8080   # Firefly III
tailscale serve --bg --https=8181 http://127.0.0.1:8181   # Data Importer
tailscale serve --bg --https=8282 http://127.0.0.1:8282   # Firefly Pico
tailscale serve status
```

This needs MagicDNS, HTTPS certificates and Serve enabled on the tailnet, and `sudo tailscale set --operator=$USER` once. The serve config persists across reboots. The importer and Pico talk to Firefly III directly over the Docker network (`http://app:8080`). If the machine name changes, update `TS_HOST` and `APP_URL` in `.env`, then `docker compose up -d`.

Persistent data lives in named Docker volumes:

- `firefly_iii_db` — MariaDB data
- `firefly_upload` — attachments uploaded to Firefly III
- `pico_data` — Firefly Pico's local database
- `importer_logs` — the Data Importer's log, also mounted read-only in `cron` so that `import.sh` can tell whether an import worked

## Files

- `docker-compose.yml` — service definitions.
- `.env` — Firefly III core configuration (app key, DB connection, timezone, mail, etc.). **Not committed**; see [First-time setup](#first-time-setup).
  It also holds what Compose passes to the other services: `TS_HOST` (the machine's Tailscale name), `FIREFLY_III_ACCESS_TOKEN` and `ENABLE_BANKING_APP_ID` (Data Importer), `RESTIC_REPOSITORY` / `RESTIC_PASSWORD` and the optional `HEALTHCHECK_URL`, `IMPORT_HEALTHCHECK_URL`, `KEEP_DAYS` (backups). The MariaDB container reuses `DB_DATABASE` / `DB_USERNAME` / `DB_PASSWORD`.
- `.rclone/` — Google Drive access for the off-site backups. **Not committed**; see [Off-site setup](#off-site-setup-once).
- `.enablebanking.pem` — Enable Banking private key for bank sync. **Not committed.**
- `import/` — data importer configs used by the daily bank import. **Not committed.**
- `.api.env` — `FIREFLY_TOKEN`, a personal access token used by the `assistant` and the PEA valuation. **Not committed.**
- `patrimoine/objectifs.json` — savings goals, written by the assistant (`set_goal`). **Not committed**.
- `patrimoine/pea.txt` — PEA positions (see [PEA valuation](#pea-valuation)); optional, the valuation is skipped without it. **Not committed**; `patrimoine/pea.example.txt` shows the format.
- `cron/` — image, schedule, import and backup scripts for the `cron` service.
- `assistant/`, `.mcp.json` — MCP server that lets Claude Code read Firefly III (see [Assistant](#assistant)).
- `update/` — new image versions: weekly e-mail and one-command update (see [Updates](#updates)).
- `watchdog/` — hourly health check and monthly restore test, both by e-mail (see [Monitoring](#monitoring)).
- `bilan/` — monthly HTML review, commented by Claude Code and e-mailed (see [Monthly review](#monthly-review)); reviews are kept in `bilans/`, **not committed**.

## First-time setup

1. Get the official example config and save it as `.env`:
   ```bash
   curl -o .env https://raw.githubusercontent.com/firefly-iii/firefly-iii/main/.env.example
   ```
2. Edit `.env`:
   - `APP_KEY` — exactly 32 random characters (e.g. `head /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9' | head -c 32`).
   - `DB_HOST=db`, `DB_PORT=3306`, `DB_CONNECTION=mysql`, and `DB_DATABASE` / `DB_USERNAME` / `DB_PASSWORD` matching the `db` service.
   - `TS_HOST=<machine>.<tailnet>.ts.net` (added at the end), `APP_URL=https://<TS_HOST>`, `TZ` (currently `Europe/Paris`), `TRUSTED_PROXIES=**` (needed behind `tailscale serve`).
3. Start everything (and set up `tailscale serve`, see [Services](#services)):
   ```bash
   docker compose up -d
   ```
4. Open Firefly III and register the first user (it becomes the admin).
5. For the Data Importer: in Firefly III go to **Options → Profile → OAuth → Personal Access Tokens**, create a token, and put it in `.env` as `FIREFLY_III_ACCESS_TOKEN=<token>`. Then `docker compose up -d importer`. Give each use its own token name (`Importer`, `Assistant`, `Pico`) and never revoke or replace one that is in use: whatever uses it then fails with a 401 (see [Security notes](#security-notes)).
6. For Firefly Pico: open it on port 8282 and log in with a personal access token as well.

## Day-to-day

```bash
docker compose ps                    # status
docker compose logs -f app           # follow Firefly III logs
docker compose pull && docker compose up -d   # apply the versions in docker-compose.yml
docker compose restart importer      # restart a single service
docker compose down                  # stop (volumes are kept)
```

### Updates

Every image has a fixed version in `docker-compose.yml` (Pico follows its `dev` tag, pinned by digest), so `pull` never changes anything on its own. [update/update.py](update/update.py) (standard library only, run on the host) finds and applies new versions, for this stack and for Nextcloud (`../nextcloud`):

```bash
python3 update/update.py check          # what has a newer version
python3 update/update.py apply          # update, one image at a time, asking each time
```

- **Notification:** a systemd user timer ([update/firefly-update.timer](update/firefly-update.timer)) runs `check --mail` every Saturday at 08:00 and e-mails the list, once per set of versions. Enable it with `bash update/install-timer.sh`. The mail uses the `MAIL_*` settings of `.env` (set them with `bash update/configurer-mail.sh`), to `MAIL_FROM` or `BILAN_TO`.
- **`apply`:** backs Firefly III up first (`backup.sh`), edits `docker-compose.yml` (or pulls the moving tag for Nextcloud), runs `docker compose up -d --build`, waits until every container is healthy and the web page answers, and goes back to the previous version if it does not. A successful Firefly III update is committed (`git push origin master` to send it). It finds: Firefly III and the Data Importer (GitHub releases), MariaDB (same major), Pico (new `dev` build), and new builds of the moving Nextcloud, Redis and MariaDB tags.
- **New major versions** (MariaDB 13, Nextcloud 34/35, Redis 8...) are only reported, never applied: read the release notes first and go one major at a time. Nextcloud is backed up every night at 03:30 by the root timer `nextcloud-backup.timer`; check that the last run succeeded before updating it.

MariaDB has `MARIADB_AUTO_UPGRADE=1`, so its system tables are upgraded when its version changes.

### Monitoring

Two scripts in [watchdog/](watchdog/) (standard library only, run on the host by systemd user timers) tell you when something silently stops working. They mail through the `MAIL_*` settings of `.env`. Enable both with `bash watchdog/install-timers.sh`.

- [watchdog.py](watchdog/watchdog.py), every hour: every container up and healthy, the web pages (Firefly III, importer, Pico, Nextcloud) answering, the Firefly III backup less than 30 hours old, the last nightly Nextcloud backup recent (it reads the marker `/var/backups/nextcloud/.last-success`, see [Nextcloud](#nextcloud-backup)), no cron job failing for more than 6 hours (`daily.sh` leaves a `backups/.state/<job>.failed` marker), disk under 85 %. It mails once per set of problems, and once more when they are gone. `python3 watchdog/watchdog.py --print` only prints.
- [restore_test.py](watchdog/restore_test.py), on the 1st of each month: restores the latest dump from the restic repository on Google Drive into a throwaway MariaDB container, checks that the transactions and accounts are there and close to the live database, and mails the result either way. `python3 watchdog/restore_test.py --print` runs it now (about 5 minutes).

It cannot warn you when the machine itself is off or offline: nothing runs then. Add an external ping (for example healthchecks.io, through `HEALTHCHECK_URL` and `IMPORT_HEALTHCHECK_URL` in `.env`) if you want that.

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

Once a day (see [Scheduled jobs](#scheduled-jobs)) `import.sh` POSTs to the importer's `/autoimport`, which runs each config in `import/` (last 5 days; transactions already in Firefly III are recognised by the bank's ID and skipped). Rules are applied on import. The importer's own e-mail report is off (`ENABLE_MAIL_REPORT=false`): an import that fails, such as an expired bank consent, is caught by `import.sh` (below) and by the [monitoring](#monitoring).

The importer answers "Seems to have worked" even when an import fails, so `import.sh` reads the importer's own log (the `importer_logs` volume, mounted read-only in `cron`) and treats any `ERROR` line written during the run as a failure, except the "Zero transactions" messages an empty period produces. A failed import is retried about 2 hours later and shows in `docker logs firefly_iii_cron`. Duplicates are avoided with `duplicate_detection_method: "cell"` in the import configs: the bank's transaction ID is looked up in Firefly III before anything is added.

Setup:

1. On the Enable Banking control panel, register a **production** application with redirect URL `https://<host>:8181/eb-callback`, keep the downloaded private key as `.enablebanking.pem` (mode 644: the importer runs as `www-data`), then *Activate by linking accounts*.
2. In `.env`: `ENABLE_BANKING_APP_ID` and `AUTO_IMPORT_SECRET` (32 random characters). The importer's `CAN_POST_AUTOIMPORT`, `IMPORT_DIR_ALLOWLIST` and `ENABLE_MAIL_REPORT` are set in `docker-compose.yml`; to have the importer e-mail its own report as well, set `ENABLE_MAIL_REPORT=true` there and add the importer's mail variables (`MAIL_MAILER`, `MAIL_HOST`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_ENCRYPTION`, `MAIL_DESTINATION`, `MAIL_FROM_ADDRESS`) to the importer's `environment:` block: it no longer reads `.env` as a whole.
3. Run one import by hand in the importer UI and download its configuration into `import/<name>.json`. Set its `date_range` to `partial` and `date_range_number` to `5`, otherwise it keeps asking for the fixed dates it was downloaded with (the bank then refuses it with a misleading "more than 90 days" error).
4. Optional: `IMPORT_HEALTHCHECK_URL` in `.env` for an alert when the daily import itself fails.

**Bank consent expires** (90 days for Crédit Agricole de Paris; each bank has its own config in `import/`). The failing import shows in the monitoring mail. To renew: run an import in the importer UI again, download the new configuration and replace the file in `import/`.

## PEA valuation

Optional: skipped ("No /patrimoine/pea.txt, skipping") when `patrimoine/pea.txt` does not exist, which is the right setting without a PEA. The bank only reports the PEA's cash movements, not what its holdings are worth. Each day `valuation.sh` reads the positions in `patrimoine/pea.txt` (Yahoo Finance symbol and quantity per line, plus `especes` for cash), prices them, and books the gap between that market value and the balance of the `PEA - Boursobank` account: a deposit from *Plus-values latentes* or a withdrawal to *Moins-values latentes*, category *Valorisation*, tag `valorisation`. The account balance therefore always equals the PEA's value. Contributions are still entered as usual (as transfers from the current account).

Setup:

1. In Firefly III, create an asset account named `PEA - Boursobank` (or set `PEA_ACCOUNT`), and a personal access token (**Options → Profile → OAuth**, name it `Assistant`) that you put in `.api.env` (`chmod 600`) as `FIREFLY_TOKEN=<token>`. Run `docker compose up -d cron` afterwards: the container reads `.api.env` only when it is created.
2. Copy `patrimoine/pea.example.txt` to `patrimoine/pea.txt` and enter the positions. Find each symbol by searching the ISIN on [Yahoo Finance](https://finance.yahoo.com) (Paris listings end in `.PA`); only prices in euros are accepted.
3. **Before the first run**, make sure the account's balance equals the total contributed so far, so that only real gains are booked as *Plus-values latentes*.
4. `docker compose up -d --build cron`, then `docker exec firefly_iii_cron valuation.sh`.

After buying or selling, tell the assistant (`set_pea_position`) or edit `pea.txt` yourself (quantities and `especes`). `PEA_POSITIONS` and `PEA_ACCOUNT` override the file and account name.

## Assistant

[assistant/server.py](assistant/server.py) is an [MCP](https://modelcontextprotocol.io) server that gives Claude Code access to Firefly III, so finances can be asked about and kept in plain language ("how much did I spend on restaurants this summer?", "what is my net worth?", "can I afford a 600 € trip in March?", "put last week's uncategorised transactions in the right categories"). Its tools:

| Tool | Returns |
|------|---------|
| `net_worth` | net worth, split into everyday accounts, savings, investments and debts |
| `accounts` | every asset and liability account with its balance |
| `summary` | income, spending and savings over a period |
| `by_category` | spending or income per category over a period |
| `monthly_history` | income, spending and savings per month |
| `budgets` | each budget's amount, spent and left over a period |
| `upcoming_bills` | expected bill payments in the next days |
| `search_transactions` | transactions matching a Firefly III search query |
| `pea_positions` | PEA holdings at today's prices, with weights |
| `goals` | savings goals (a target balance on an account, optional deadline) with progress, pace and estimated date |
| `set_goal` ✏️ | creates or replaces a savings goal (an account balance target or a Firefly III piggy bank) in `patrimoine/objectifs.json` |
| `remove_goal` ✏️ | deletes a savings goal |
| `set_pea_position` ✏️ | sets the quantity held of a PEA position (or the cash) in `patrimoine/pea.txt` |
| `net_worth_history` | net worth at the end of each month, by group, with what was saved and the PEA's market moves |
| `projection` | net worth year by year over the next years, and when each family debt is cleared |
| `update_transaction` ✏️ | changes a transaction's category, budget, tags, description or notes |
| `create_transaction` ✏️ | records a withdrawal, deposit or transfer (rules are applied) |
| `set_budget` ✏️ | creates a budget or changes its automatic amount and period |
| `rules` | every rule (triggers and actions), in the order Firefly III runs them |
| `preview_rule` | past transactions a rule matches, without changing anything |
| `save_rule` ✏️ | creates a rule, or replaces the triggers and actions of an existing one |
| `apply_rule` ✏️ | runs a rule on past transactions |

The ✏️ tools change data: Claude Code asks before each call (unless the tool is allowed in `/permissions`), and the server tells Claude to spell out the change first. None of them deletes anything.

`net_worth_history` measures saving as the month's net worth change minus the PEA's unrealised gains, so money borrowed from family counts against it, unlike `monthly_history`. `projection` starts from today's balances and, unless told otherwise, assumes the user keeps saving the median of the last 12 months, paying into the PEA and repaying debts at the last 12 months' pace, with a 5 % yearly PEA return, 1.5 % on cash and savings and 2 % inflation. Each of these can be changed in the question ("and if I put 100 € a month in the PEA?").

Rules are how transactions get filed for good: they run on every new transaction, imports included. The groups run in order, so rules in a later group (such as *Budgets*, which sets a budget from the category) see what the earlier ones set.

Spending and income figures leave out the `Dette …` and `PEA …` accounts, so family debt adjustments and PEA valuations do not count as income or spending.

Claude Code starts it from [.mcp.json](.mcp.json) when a session opens in this directory (approve the `firefly` server on first use; `/mcp` shows its status). It runs in the `assistant` container on the Docker network, with `FIREFLY_TOKEN` from `.api.env` (see [PEA valuation](#pea-valuation)), and is rebuilt on each start, so changes to `server.py` apply to the next session. The `assistant` profile keeps `docker compose up` from starting it.

## Monthly review

Every month, [bilan/bilan.sh](bilan/bilan.sh) e-mails an HTML review of the month that just ended: key figures (income, spending, what was really saved, net worth), spending per category against the 3 months before, largest expenses, budgets, net worth over 6 months, uncategorised transactions with a suggested category, bills due next month, and where the current pace leads in 5 years.

1. [bilan/data.py](bilan/data.py) gathers every figure from Firefly III, in the `assistant` container with the [assistant](#assistant)'s helpers.
2. Claude Code reads them and writes the comments only (summary, highlights, things to check, suggested categories, advice), as JSON following [bilan/schema.json](bilan/schema.json). Its instructions are in [bilan/prompt.md](bilan/prompt.md).
3. [bilan/render.py](bilan/render.py) lays both out as an e-mail (tables and inline styles, with a plain-text version), and [bilan/send_mail.py](bilan/send_mail.py) sends it through the `MAIL_*` settings in `.env`, to `MAIL_FROM` or `BILAN_TO` if set.

The figures, comments and e-mail are kept in `bilans/YYYY-MM.*` (git-ignored).

Claude gets no tools at all, only the figures in its prompt: it cannot change data.

It runs on the host, not in a container, so it uses the Claude subscription of the logged-in user. A systemd user timer starts it every day at 10:00, or at login if the machine was off then. It does nothing once the month's review exists, so a missed month or a failed run is caught up the next day.

Setup (once):

1. Install Claude Code in `~/.local/bin` (`curl -fsSL https://claude.ai/install.sh | bash`) and log in once (`claude`).
2. Enable the timer (the units stay in the repository; they expect it in `~/server/firefly-iii`):
   ```bash
   systemctl --user link ~/server/firefly-iii/bilan/firefly-bilan.service
   systemctl --user enable --now ~/server/firefly-iii/bilan/firefly-bilan.timer
   ```
3. Once, for this and the other user timers ([update](#updates), [watchdog](#monitoring)) to run without a login session: `sudo loginctl enable-linger $USER`. Their e-mails need the `MAIL_*` settings of `.env`.

By hand: `bilan/bilan.sh` (last month), `bilan/bilan.sh 2026-09` (another month), `FORCE=1 bilan/bilan.sh` (rebuild an existing review), `NO_MAIL=1 bilan/bilan.sh` (no e-mail). Logs: `journalctl --user -u firefly-bilan`.

## Backups

Each day (see [Scheduled jobs](#scheduled-jobs)) `backup.sh`:

1. dumps the database to `backups/firefly_YYYY-MM-DD.sql.gz` and archives the `firefly_upload` volume to `backups/uploads_YYYY-MM-DD.tar.gz`, keeping 14 days locally;
2. if `.env` sets `RESTIC_REPOSITORY`, sends both files to an encrypted [restic](https://restic.net/) repository on Google Drive (through rclone), keeping 7 daily, 4 weekly and 12 monthly snapshots.

`backups/`, `*.sql`, `*.sql.gz` and `.rclone/` are git-ignored.

### Off-site setup (once)

1. Authorize Google Drive (opens a link to visit in a browser on this machine; rclone only sees the files it creates):
   ```bash
   mkdir -p .rclone
   docker run --rm -it --user $(id -u):$(id -g) --network host -v "$PWD/.rclone":/config/rclone \
     rclone/rclone:1.71.2 config create gdrive drive scope=drive.file
   ```
2. Add to `.env`:
   ```
   RESTIC_REPOSITORY=rclone:gdrive:firefly-backup
   RESTIC_PASSWORD=<long random password>
   ```
   **Keep `RESTIC_PASSWORD` somewhere other than this machine (e.g. a password manager). Without it, the Drive copy cannot be decrypted.**
3. Create the repository and restart: `docker compose run --rm cron restic init && docker compose up -d cron`.

### Failure alerts (optional)

Add a healthchecks.io ping URL to `.env`:

```
HEALTHCHECK_URL=https://hc-ping.com/<uuid>
```

`backup.sh` reports its exit code to it after every run. Backups run whenever the machine is on (see [Scheduled jobs](#scheduled-jobs)), not at a fixed time, so on healthchecks.io use a **simple** schedule: period 1 day, grace time 2 days. You get an e-mail when a run fails, or when no backup has happened for 3 days. Apply with `docker compose up -d cron`.

### If the upload to Google Drive times out

Two different causes have been seen, both showing up as `context deadline exceeded` or very slow runs:

- **DNS inside the containers.** Docker's resolver forwards to the host's, which is Tailscale's here, and lookups failed for minutes (`lookup oauth2.googleapis.com on 127.0.0.11:53: server misbehaving`; rclone reads that as "rate limited" and retries). The `dns:` entry of the `x-hardened` block in `docker-compose.yml` (1.1.1.1 and 9.9.9.9) fixes it for every service. Test: `docker exec firefly_iii_cron getent hosts oauth2.googleapis.com`.
- **Google's own quota.** rclone uses a Google API project shared by all its users unless you give it your own, and Google then answers `RATE_LIMIT_EXCEEDED`. The Nextcloud backup hit it once. The lasting fix is to create your own OAuth client in the Google Cloud console and set `client_id` and `client_secret` in the `gdrive` remote (see rclone's "Making your own client_id" documentation); until then, restic's local cache (`RESTIC_CACHE_DIR`) keeps the number of requests down.

### Nextcloud backup

Nextcloud (`../nextcloud`, outside this repository) is backed up by the root systemd timer `nextcloud-backup.timer` (every night around 03:30), which runs `/usr/local/sbin/nextcloud-backup.sh`: Nextcloud in maintenance mode, a dump of its database, then [restic](https://restic.net/) to `gdrive:nextcloud-backup` (its own repository and password, in `/etc/nextcloud-backup.env`) for the dump, `/srv/nextcloud-data` and the `config` directory, keeping 7 daily, 4 weekly and 12 monthly snapshots. On success it touches `/var/backups/nextcloud/.last-success`, which the [monitoring](#monitoring) reads. The script is root-only and not versioned here, so keep a copy of `/etc/nextcloud-backup.env`'s password elsewhere. After a crash that interrupted a run, `restic unlock` (as root, with that environment) removes the stale lock that would otherwise block the next one. A full run can take several minutes, or more when Google Drive throttles the requests.

### Restore

Nextcloud (not tested end to end): as root with the environment of `/etc/nextcloud-backup.env`, `restic restore latest --tag nextcloud --target /restore` brings back `/srv/nextcloud-data`, the database dump and the `config` directory, each under its full original path inside `/restore`; put the data back in `/srv/nextcloud-data`, load the dump with `gunzip -c nextcloud_YYYY-MM-DD.sql.gz | docker compose exec -T db sh -c 'mariadb -u root -p"$MARIADB_ROOT_PASSWORD" nextcloud'` (in `../nextcloud`), restore `config/config.php`, then `docker compose exec -u www-data app php occ maintenance:data-fingerprint`.

Firefly III, database, from a local dump:

```bash
gunzip -c backups/firefly_YYYY-MM-DD.sql.gz \
  | docker exec -i firefly_iii_db sh -c 'mariadb -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
```

Firefly III, from Google Drive (needs `.rclone/` and the `RESTIC_*` lines of `.env`; `python3 watchdog/restore_test.py --print` does a dry run of this every month):

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

- Secrets live only in the git-ignored `.env` and `.rclone/`. Never put them back in `docker-compose.yml`.
- Ports 8080, 8181 and 8282 are bound to `127.0.0.1`: they are not reachable from the LAN, only through `tailscale serve`. Keep it that way.
- Every container drops all Linux capabilities and cannot gain new ones (`cap_drop: ALL` and `no-new-privileges` through the `x-hardened` block of `docker-compose.yml`); each service adds back only what its entrypoint needs (`cap_add`). If a new image refuses to start after an update, a missing capability is the first thing to check in `docker logs`.
- The repository is public: it must never contain a secret. `.env`, `.api.env`, `.rclone/`, `*.pem`, `import/`, `patrimoine/` and `backups/` are git-ignored; check `git status` before each push. The Tailscale host name appears in older commits, which is harmless: the services only answer on the tailnet.
- The host: SSH accepts keys only (`PasswordAuthentication no`, no root login, in `/etc/ssh/sshd_config.d/10-cle-seule.conf`) and `ufw` allows only Tailscale and the local network. Keep a working key before changing that file, or the machine can only be reached with a keyboard.
- `.enablebanking.pem` is mode 644 because the importer runs as `www-data` inside its container, and `.env` also reaches the Firefly III container (restic password, importer token). Both are accepted trade-offs of a single-user machine.
- Personal access tokens (`.api.env`, and `FIREFLY_III_ACCESS_TOKEN` in `.env`) can be revoked in Firefly III (Options > Profile > OAuth). Revoking one breaks what uses it: the importer, the assistant and the PEA valuation. The nightly import then fails and shows up in `docker logs firefly_iii_cron` and in the monitoring mail.
