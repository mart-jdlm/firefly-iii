#!/bin/bash
# Builds last month's financial review and e-mails it (see the README, "Monthly review"):
# data.py gathers the figures from Firefly III, Claude Code writes the comments, render.py lays
# them out as an HTML e-mail. Everything is kept in bilans/YYYY-MM.*. Started every day by the
# firefly-bilan systemd user timer: it does nothing once the month's review exists, so a month
# missed while the machine was off, or a failed run, is caught up on the next day it is on.
# bilan.sh [YYYY-MM] reviews another month; FORCE=1 rebuilds an existing review; NO_MAIL=1 skips
# the e-mail. Claude gets no tools at all: only the figures, in its prompt.
set -euo pipefail

cd "$(dirname "$0")/.."
month=${1:-$(date -d "$(date +%Y-%m-01) -1 day" +%Y-%m)}
out=bilans/$month

if [ -s "$out.html" ] && [ -z "${FORCE:-}" ]; then
  echo "$out.html already exists"
  exit 0
fi
mkdir -p bilans
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "Gathering the figures for $month"
docker compose build -q assistant
docker compose run --rm --no-deps -T -v ./bilan:/bilan:ro --entrypoint python assistant \
  /bilan/data.py "$month" >"$tmp/facts.json"

echo "Writing the comments"
{ sed -e "s/{{MONTH}}/$month/g" -e "s/{{TODAY}}/$(date +%F)/g" bilan/prompt.md; cat "$tmp/facts.json"; } \
  | claude -p --tools "" --strict-mcp-config --permission-mode dontAsk \
    --output-format json --json-schema "$(cat bilan/schema.json)" >"$tmp/claude.json"
python3 -c 'import json, sys; r = json.load(sys.stdin); json.dump(r["structured_output"], sys.stdout, ensure_ascii=False, indent=1)' \
  <"$tmp/claude.json" >"$tmp/comments.json"

python3 bilan/render.py "$tmp/facts.json" "$tmp/comments.json" "$tmp/review.html" "$tmp/review.txt"
[ -n "${NO_MAIL:-}" ] || python3 bilan/send_mail.py "$month" "$tmp/review.html" "$tmp/review.txt"

cp "$tmp/facts.json" "$out.facts.json"
cp "$tmp/comments.json" "$out.comments.json"
cp "$tmp/review.txt" "$out.txt"
cp "$tmp/review.html" "$out.html"
echo "Done: $out.html"
