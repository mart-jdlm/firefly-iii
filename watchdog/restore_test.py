#!/usr/bin/env python3
"""Monthly proof that the backup can be restored (see the README, "Monitoring").

Takes the latest Firefly III dump from backups/, loads it into a
throwaway MariaDB container (same image as production, removed afterwards) and checks that the
data is there and close to the live database. Mails the result either way. Production is only
read. Standard library only; runs on the host.

  restore_test.py            test and mail
  restore_test.py --print    test, only print
"""

import gzip
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "update"))
from update import ROOT, images, send_text  # noqa: E402

NAME = "firefly-restore-test"
COUNT = ("select count(*) from transaction_journals where deleted_at is null",
         "select count(*) from accounts where deleted_at is null",
         "select count(*) from information_schema.tables where table_schema = database()")


def sh(*cmd: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, **kwargs)


def counts(container: str, user: str, password: str, database: str) -> list[int]:
    out = []
    for query in COUNT:
        result = sh("docker", "exec", container, "mariadb", f"-u{user}", f"-p{password}", database, "-N", "-e", query, text=True)
        out.append(int(result.stdout.strip()))
    return out


def run_test() -> str:
    """Returns a one-line summary; raises on any failure."""
    dumps = sorted((ROOT / "backups").glob("firefly_*.sql.gz"))
    if not dumps:
        raise RuntimeError("Aucun dump trouvé dans backups/")
    path = str(dumps[-1])
    sql = gzip.decompress(dumps[-1].read_bytes())

    image = next(i for stack, i in images() if stack == "firefly" and i.startswith("mariadb"))
    sh("docker", "rm", "-f", NAME)
    try:
        started = sh("docker", "run", "-d", "--name", NAME, "-e", "MARIADB_ROOT_PASSWORD=restore",
                     "-e", "MARIADB_DATABASE=restore", image, text=True)
        if started.returncode:
            raise RuntimeError(f"Base temporaire impossible à démarrer : {started.stderr[-200:]}")
        for _ in range(60):
            if sh("docker", "exec", NAME, "mariadb", "-uroot", "-prestore", "-e", "select 1").returncode == 0:
                break
            time.sleep(2)
        loaded = sh("docker", "exec", "-i", NAME, "mariadb", "-uroot", "-prestore", "restore", input=sql)
        if loaded.returncode:
            raise RuntimeError(f"Le dump ne se charge pas : {loaded.stderr[-200:].decode(errors='replace')}")
        restored = counts(NAME, "root", "restore", "restore")
        env = sh("docker", "exec", "firefly_iii_db", "printenv", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE", text=True)
        user, password, database = env.stdout.split()
        live = counts("firefly_iii_db", user, password, database)
    finally:
        sh("docker", "rm", "-f", NAME)

    summary = (f"{path.rsplit('/', 1)[-1]} : {restored[0]} transactions, {restored[1]} comptes, {restored[2]} tables "
               f"(base actuelle : {live[0]} transactions, {live[1]} comptes)")
    if restored[2] < 50 or restored[0] == 0 or abs(live[0] - restored[0]) > max(20, live[0] // 20):
        raise RuntimeError("Résultat inattendu : " + summary)
    return summary


def main() -> None:
    try:
        summary = run_test()
        subject, body = "Serveur : test de restauration réussi", "La dernière sauvegarde se restaure correctement.\n\n" + summary
    except Exception as error:
        subject, body = "Serveur : ÉCHEC du test de restauration", f"La dernière sauvegarde n'a pas pu être restaurée.\n\n{error}"
    print(body)
    if "--print" not in sys.argv:
        send_text(subject, body)


if __name__ == "__main__":
    main()
