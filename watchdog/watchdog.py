#!/usr/bin/env python3
"""Hourly health check of the server; mails when something is wrong (see the README, "Monitoring").

Checks: every container is up and healthy, the web pages answer, the Firefly III backup and the
nightly Nextcloud backup are recent, no job of the cron service keeps failing, the disk is not
full. Mails once per set of problems (and once more when they are gone), not every hour.
Standard library only; runs on the host.

  watchdog.py            check and mail
  watchdog.py --print    check, only print
"""

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "update"))
from update import ROOT, read_env, send_text  # noqa: E402

STATE = ROOT / "backups" / ".state"
CONTAINERS = ["firefly_iii_core", "firefly_iii_db", "firefly_iii_importer", "firefly_iii_pico",
              "firefly_iii_cron", "nextcloud_app", "nextcloud_db", "nextcloud_cron", "nextcloud_redis"]
PAGES = {"Firefly III": "http://127.0.0.1:8080/login", "Importer": "http://127.0.0.1:8181/",
         "Pico": "http://127.0.0.1:8282/", "Nextcloud": "http://127.0.0.1:8484/status.php"}
BACKUP_MAX_HOURS = 30   # the nightly jobs run every ~24 h; a missed day shows after 30 h
FAILED_MAX_HOURS = 6    # a failing job is retried every 2 hours: 3 failures in a row is a problem
DISK_MAX_PERCENT = 85


def hours_since(timestamp: float) -> float:
    return (time.time() - timestamp) / 3600


def problems() -> list[str]:
    found = []
    ps = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}"], capture_output=True, text=True)
    if ps.returncode:
        # One message, not nine "absent": the check could not ask Docker (daemon stopped, no permission).
        found.append(f"Docker inaccessible depuis la surveillance : {ps.stderr.strip()[:120]}")
    else:
        status = dict(line.split("|", 1) for line in ps.stdout.splitlines() if "|" in line)
        for name in CONTAINERS:
            text = status.get(name, "absent")
            if not text.startswith("Up") or "unhealthy" in text or "Restarting" in text:
                found.append(f"Conteneur {name} : {text}")
    for name, url in PAGES.items():
        try:
            code = urllib.request.urlopen(url, timeout=20).status
        except Exception as error:
            code = getattr(error, "code", str(error)[:60])
        if code != 200:
            found.append(f"{name} ne répond pas correctement ({code})")

    backup = STATE / "backup"
    if not backup.exists() or hours_since(backup.stat().st_mtime) > BACKUP_MAX_HOURS:
        found.append("La sauvegarde de Firefly III n'a pas réussi depuis plus de 30 h")
    for marker in sorted(STATE.glob("*.failed")):
        if hours_since(marker.stat().st_mtime) > FAILED_MAX_HOURS:
            found.append(f"La tâche « {marker.stem} » échoue depuis {hours_since(marker.stat().st_mtime):.0f} h "
                         "(voir : docker logs firefly_iii_cron)")

    # The root script /usr/local/sbin/nextcloud-backup.sh touches this file once the local copy is done.
    # (systemd's own "Result" is reset by a reboot and says nothing about a run cut short by a crash.)
    marker = Path("/var/backups/nextcloud/.last-success")
    if not marker.exists():
        found.append("Aucune sauvegarde Nextcloud réussie enregistrée (fichier-témoin absent)")
    elif hours_since(marker.stat().st_mtime) > BACKUP_MAX_HOURS:
        found.append(f"La dernière sauvegarde Nextcloud réussie date de {hours_since(marker.stat().st_mtime):.0f} h")

    usage = shutil.disk_usage("/")
    if usage.used / usage.total * 100 > DISK_MAX_PERCENT:
        found.append(f"Disque plein à {usage.used / usage.total * 100:.0f} %")
    return found


def main() -> None:
    found = problems()
    print("\n".join(found) if found else "Tout va bien.")
    if "--print" in sys.argv:
        return
    state_file = STATE / "watchdog.json"
    before = json.loads(state_file.read_text()).get("problems", []) if state_file.exists() else []
    if found and found != before:
        send_text(f"Serveur : {len(found)} problème(s)", "Problèmes détectés :\n\n- " + "\n- ".join(found))
        print("Mail envoyé.")
    elif not found and before:
        send_text("Serveur : tout est rentré dans l'ordre", "Les problèmes signalés précédemment ont disparu :\n\n- "
                  + "\n- ".join(before))
        print("Mail de rétablissement envoyé.")
    state_file.write_text(json.dumps({"problems": found}))


if __name__ == "__main__":
    main()
