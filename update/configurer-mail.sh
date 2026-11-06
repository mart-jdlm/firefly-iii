#!/bin/bash
# bash ~/server/firefly-iii/update/configurer-mail.sh : règle l'envoi de mail (Gmail) dans .env,
# teste la connexion, puis redémarre Firefly. Le mot de passe ne s'affiche pas quand vous le collez.
cd /home/squishy8316/server/firefly-iii || exit 1
read -rp "Adresse Gmail [mart.jdlm@gmail.com] : " addr
addr=${addr:-mart.jdlm@gmail.com}
read -rsp "Mot de passe d'application Google (16 lettres, espaces acceptés) : " pw; echo
pw=${pw// /}
[ -n "$pw" ] || { echo "Mot de passe vide, rien n'a été modifié."; exit 1; }
ADDR="$addr" PW="$pw" python3 - <<'PY' || exit 1
import os, smtplib, sys
try:
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
        s.starttls(); s.login(os.environ["ADDR"], os.environ["PW"])
    print("Connexion à Gmail : OK")
except Exception as e:
    print("Connexion à Gmail impossible :", e); print("Rien n'a été modifié."); sys.exit(1)
values = {"MAIL_MAILER": "smtp", "MAIL_HOST": "smtp.gmail.com", "MAIL_PORT": "587", "MAIL_ENCRYPTION": "tls",
          "MAIL_USERNAME": os.environ["ADDR"], "MAIL_PASSWORD": os.environ["PW"], "MAIL_FROM": os.environ["ADDR"]}
lines = open(".env").read().split("\n")
done = set()
out = []
for l in lines:
    k = l.split("=", 1)[0]
    if k in values and not l.startswith("#"):
        out.append(f"{k}={values[k]}"); done.add(k)
    else:
        out.append(l)
while out and out[-1] == "": out.pop()
out += [f"{k}={v}" for k, v in values.items() if k not in done]
open(".env", "w").write("\n".join(out) + "\n")
os.chmod(".env", 0o600)
PY
docker compose up -d app 2>&1 | grep -E 'app' | tail -1
echo "Fait : l'envoi de mail est configuré."
