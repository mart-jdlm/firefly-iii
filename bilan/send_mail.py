"""Sends a monthly review by e-mail: send_mail.py YYYY-MM REVIEW.html REVIEW.txt.

Uses Firefly III's SMTP settings from .env (MAIL_HOST, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD,
MAIL_FROM). The review goes to BILAN_TO if set, otherwise to MAIL_FROM.
"""

import os
import smtplib
import sys
from email.message import EmailMessage

MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]


def read_env(path: str) -> dict[str, str]:
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                env[key] = value.strip().strip("\"'")
    return env


def main() -> None:
    month, html_path, text_path = sys.argv[1:4]
    env = read_env(".env")
    year, number = month.split("-")
    message = EmailMessage()
    message["Subject"] = f"Bilan financier de {MONTHS[int(number) - 1]} {year}"
    message["From"] = env["MAIL_FROM"]
    message["To"] = os.environ.get("BILAN_TO") or env["MAIL_FROM"]
    with open(text_path, encoding="utf-8") as f:
        message.set_content(f.read())
    with open(html_path, encoding="utf-8") as f:
        message.add_alternative(f.read(), subtype="html")
    with smtplib.SMTP(env["MAIL_HOST"], int(env.get("MAIL_PORT", 587)), timeout=60) as smtp:
        smtp.starttls()
        smtp.login(env["MAIL_USERNAME"], env["MAIL_PASSWORD"])
        smtp.send_message(message)
    print(f"Sent to {message['To']}")


if __name__ == "__main__":
    main()
