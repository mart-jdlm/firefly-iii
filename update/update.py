#!/usr/bin/env python3
"""New versions of the container images, and a one-command update (see the README, "Updates").

  update.py check [--mail]   list what has a newer version; --mail sends it by e-mail, once per set
  update.py apply            update one image at a time, after a backup and with a health check

Covers the Firefly III stack (this repository) and the Nextcloud stack (../nextcloud). Images pinned
to a version or digest are updated by editing docker-compose.yml; images on a moving tag
(nextcloud:33-apache...) by pulling it. Newer major versions are only reported: they can need
manual steps, so read the release notes first. Standard library only; runs on the host.
"""

import argparse
import json
import re
import smtplib
import subprocess
import sys
import time
import urllib.request
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STACKS = {"firefly": ROOT, "nextcloud": ROOT.parent / "nextcloud"}
STATE = ROOT / "backups" / ".state" / "update.json"
GITHUB = {"fireflyiii/core": "firefly-iii/firefly-iii", "fireflyiii/data-importer": "firefly-iii/data-importer"}
# URL answering 200 once a stack works, for the health check after an update.
HEALTH = {"firefly": "http://127.0.0.1:8080/login", "nextcloud": "http://127.0.0.1:8484/status.php"}


def get(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "firefly-update-check"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def version(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text))


def hub(repo: str) -> str:
    return f"https://registry.hub.docker.com/v2/repositories/{repo if '/' in repo else 'library/' + repo}"


def hub_tags(repo: str, name: str = "") -> list[dict]:
    return get(f"{hub(repo)}/tags?page_size=100&name={name}")["results"]


def images() -> list[tuple[str, str]]:
    found = []
    for stack, path in STACKS.items():
        compose = path / "docker-compose.yml"
        if compose.exists():
            for image in re.findall(r"^\s*image:\s*(\S+)", compose.read_text(), re.M):
                if (stack, image) not in found:
                    found.append((stack, image))
    return found


def local_digests(image: str) -> list[str]:
    result = subprocess.run(["docker", "image", "inspect", image, "-f", "{{json .RepoDigests}}"],
                            capture_output=True, text=True)
    return json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else []


def check_image(stack: str, image: str) -> list[dict]:
    """The updates (kind "update") and newer majors (kind "major") found for one image."""
    ref, _, digest = image.partition("@")
    repo, _, tag = ref.partition(":")
    item = {"stack": stack, "repo": repo, "image": image}
    if repo in GITHUB:
        latest = get(f"https://api.github.com/repos/{GITHUB[repo]}/releases/latest")["tag_name"].lstrip("v")
        current = tag.removeprefix("version-")
        if version(latest) > version(current):
            return [{**item, "kind": "update", "how": "pin", "current": current, "latest": latest,
                     "new_image": f"{repo}:version-{latest}"}]
        return []
    if digest:  # a moving tag pinned by digest (Firefly Pico)
        latest = get(f"{hub(repo)}/tags/{tag}")["digest"]
        if latest != digest:
            return [{**item, "kind": "update", "how": "pin", "current": digest[7:15], "latest": latest[7:15],
                     "new_image": f"{repo}:{tag}@{latest}"}]
        return []
    found = []
    if re.fullmatch(r"\d+\.\d+\.\d+", tag):  # pinned to a full version (MariaDB)
        names = [t["name"] for t in hub_tags(repo)]
        full = [n for n in names if re.fullmatch(r"\d+\.\d+\.\d+", n)]
        same = [n for n in full if version(n)[0] == version(tag)[0] and version(n) > version(tag)]
        if same:
            latest = max(same, key=version)
            found.append({**item, "kind": "update", "how": "pin", "current": tag, "latest": latest,
                          "new_image": f"{repo}:{latest}"})
        newer = [n for n in full if version(n)[0] > version(tag)[0]]
        if newer:
            found.append({**item, "kind": "major", "current": tag, "latest": max(newer, key=version)})
        return found
    # A moving tag (nextcloud:33-apache, mariadb:11.8, redis:7-alpine): new content under the same tag?
    latest = get(f"{hub(repo)}/tags/{tag}")["digest"]
    if not any(d.endswith(latest) for d in local_digests(image)):
        found.append({**item, "kind": "update", "how": "pull", "current": tag, "latest": "new build"})
    match = re.match(r"(\d+)(.*)", tag)
    if match and "." not in tag:  # 33-apache, 7-alpine: look for a newer major with the same suffix
        majors = {int(m.group(1)) for t in hub_tags(repo, match.group(2).lstrip("-")) for m in
                  [re.fullmatch(r"(\d+)" + re.escape(match.group(2)), t["name"])] if m}
        if majors and max(majors) > int(match.group(1)):
            found.append({**item, "kind": "major", "current": tag,
                          "latest": f"{max(majors)}{match.group(2)}"})
    return found


def check() -> list[dict]:
    items = []
    for stack, image in images():
        try:
            items += check_image(stack, image)
        except Exception as error:  # a registry hiccup must not hide the other results
            print(f"Could not check {image}: {error}", file=sys.stderr)
    return items


def describe(item: dict) -> str:
    where = "" if item["stack"] == "firefly" else f" ({item['stack']})"
    kind = "NOUVELLE VERSION MAJEURE, à lire avant" if item["kind"] == "major" else "mise à jour"
    return f"- {item['repo']}{where}: {item['current']} -> {item['latest']}  [{kind}]"


def read_env(path: Path) -> dict[str, str]:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            env[key] = value.strip().strip("\"'")
    return env


def send_mail(items: list[dict]) -> None:
    env = read_env(ROOT / ".env")
    message = EmailMessage()
    message["Subject"] = f"Serveur : {len(items)} mise(s) à jour disponible(s)"
    message["From"] = env["MAIL_FROM"]
    message["To"] = env.get("BILAN_TO") or env["MAIL_FROM"]
    message.set_content("\n".join(["Nouvelles versions disponibles :", "", *map(describe, items), "",
                                   "Pour appliquer les mises à jour (sauvegarde, test de santé, retour arrière) :",
                                   f"  python3 {Path(__file__).resolve()} apply"]))
    with smtplib.SMTP(env["MAIL_HOST"], int(env.get("MAIL_PORT", 587)), timeout=60) as smtp:
        smtp.starttls()
        smtp.login(env["MAIL_USERNAME"], env["MAIL_PASSWORD"])
        smtp.send_message(message)


def compose(stack: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *args], cwd=STACKS[stack], text=True, capture_output=True)


def stale_services(stack: str) -> list[str]:
    """Services whose container runs an older image than the one their tag now points to.

    `docker compose up -d` does not notice a moving tag (nextcloud:33-apache) that was re-pulled."""
    config = json.loads(compose(stack, "config", "--format", "json").stdout)
    stale = []
    for name, service in config["services"].items():
        container = compose(stack, "ps", "-q", name).stdout.strip()
        if not container or not service.get("image"):
            continue
        running = subprocess.run(["docker", "inspect", "-f", "{{.Image}}", container],
                                 capture_output=True, text=True).stdout.strip()
        current = subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", service["image"]],
                                 capture_output=True, text=True).stdout.strip()
        if current and running != current:
            stale.append(name)
    return stale


def healthy(stack: str) -> bool:
    for _ in range(36):  # up to 3 minutes
        time.sleep(5)
        status = compose(stack, "ps", "--format", "{{.Name}} {{.Status}}").stdout
        states = [line for line in status.splitlines() if line.strip()]
        if states and not any("starting" in s or "unhealthy" in s or "Restarting" in s for s in states):
            try:
                if urllib.request.urlopen(HEALTH[stack], timeout=15).status == 200:
                    return True
            except Exception:
                pass
    return False


def apply() -> None:
    items = [i for i in check() if i["kind"] == "update"]
    majors = [i for i in check() if i["kind"] == "major"] if not items else []
    if not items:
        print("Tout est à jour." + ("".join("\n" + describe(m) for m in majors) if majors else ""))
        return
    print("\n".join(map(describe, items)))
    backed_up = False
    for item in items:
        if input(f"\nAppliquer {item['repo']} {item['current']} -> {item['latest']} ? [o/N] ").lower() != "o":
            continue
        if item["stack"] == "firefly" and not backed_up:
            print("Sauvegarde Firefly III...")
            if subprocess.run(["docker", "exec", "firefly_iii_cron", "backup.sh"], capture_output=True).returncode:
                print("La sauvegarde a échoué, mise à jour annulée.")
                return
            backed_up = True
        if item["stack"] == "nextcloud":
            print("Nextcloud : sauvegarde automatique chaque nuit à 3h30 (timer nextcloud-backup).")
        path = STACKS[item["stack"]] / "docker-compose.yml"
        before = path.read_text()
        if item["how"] == "pin":
            path.write_text(before.replace(item["image"], item["new_image"]))
        result = compose(item["stack"], "pull")
        if result.returncode == 0:
            result = compose(item["stack"], "up", "-d", "--build")
        if result.returncode == 0 and (stale := stale_services(item["stack"])):
            print(f"Recréation de : {', '.join(stale)}")
            result = compose(item["stack"], "up", "-d", "--force-recreate", *stale)
        if result.returncode == 0 and healthy(item["stack"]):
            print("OK, tout est en bonne santé.")
            if item["how"] == "pin" and item["stack"] == "firefly":
                subprocess.run(["git", "-c", "user.name=update.py", "-c", "user.email=update@localhost", "commit", "-qam",
                                f"Update {item['repo']} to {item['latest']}"], cwd=ROOT)
                print("Commit créé (git push origin master pour l'envoyer).")
        else:
            print(f"Échec : {result.stderr[-400:]}\nRetour à l'ancienne version.")
            path.write_text(before)
            compose(item["stack"], "up", "-d")
            return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["check", "apply"])
    parser.add_argument("--mail", action="store_true")
    args = parser.parse_args()
    if args.command == "apply":
        apply()
        return
    items = check()
    print("\n".join(map(describe, items)) if items else "Tout est à jour.")
    if args.mail and items:
        key = sorted(f"{i['repo']}={i['latest']}" for i in items)
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
        if state.get("notified") != key:  # one mail per set of versions, not one a week
            send_mail(items)
            STATE.write_text(json.dumps({"notified": key}))
            print("Mail envoyé.")


if __name__ == "__main__":
    main()
