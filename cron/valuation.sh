#!/bin/sh
# Brings the PEA account in Firefly III to its market value: quantity × last price (Yahoo Finance)
# for each line of $PEA_POSITIONS, plus cash. The gap with the account's balance is booked as an
# unrealised gain (deposit) or loss (withdrawal), so the balance always equals what the PEA is worth.
# Contributions and withdrawals are still entered as usual; only the market moves are booked here.
# Needs FIREFLY_TOKEN (personal access token, from .api.env). Skipped when there is no positions file.
set -eu -o pipefail

POSITIONS=${PEA_POSITIONS:-/patrimoine/pea.txt}
ACCOUNT=${PEA_ACCOUNT:-PEA - Boursobank}

if [ ! -f "$POSITIONS" ]; then
  echo "No $POSITIONS, skipping"
  exit 0
fi

# api PATH [JSON]: GET, or POST when JSON is given.
api() {
  wget -qO- --header "Authorization: Bearer $FIREFLY_TOKEN" \
    --header 'Accept: application/vnd.api+json' --header 'Content-Type: application/json' \
    ${2:+--post-data "$2"} "http://app:8080/api/v1$1"
}

# Last price of a Yahoo Finance symbol (e.g. CW8.PA), only if quoted in euros.
price() {
  wget -qO- -T 30 -U 'Mozilla/5.0' "https://query1.finance.yahoo.com/v8/finance/chart/$1?range=1d&interval=1d" \
    | jq -er '.chart.result[0].meta | select(.currency == "EUR") | .regularMarketPrice'
}

total=0
while read -r symbol quantity _; do
  case $symbol in '' | '#'*) continue ;; esac
  if [ "$symbol" = especes ]; then
    value=$quantity
  else
    p=$(price "$symbol") || { echo "No price in EUR for $symbol"; exit 1; }
    value=$(awk -v q="$quantity" -v p="$p" 'BEGIN { printf "%.2f", q * p }')
    echo "$symbol: $quantity × $p = $value"
  fi
  total=$(awk -v t="$total" -v v="$value" 'BEGIN { printf "%.2f", t + v }')
done < "$POSITIONS"

account=$(api "/accounts?type=asset&limit=200" \
  | jq -ec --arg n "$ACCOUNT" '.data[] | select(.attributes.name == $n) | {id, balance: .attributes.current_balance}') \
  || { echo "No asset account named \"$ACCOUNT\""; exit 1; }
id=$(echo "$account" | jq -r .id)
balance=$(echo "$account" | jq -r .balance)
delta=$(awk -v t="$total" -v b="$balance" 'BEGIN { printf "%.2f", t - b }')
echo "Market value $total, balance $balance, gap $delta"

case $delta in
  0.00 | -0.00)
    echo "Already at market value"
    exit 0
    ;;
  -*)
    split=$(jq -n --arg a "${delta#-}" --arg id "$id" \
      '{type: "withdrawal", amount: $a, source_id: $id, destination_name: "Moins-values latentes"}')
    ;;
  *)
    split=$(jq -n --arg a "$delta" --arg id "$id" \
      '{type: "deposit", amount: $a, source_name: "Plus-values latentes", destination_id: $id}')
    ;;
esac

body=$(jq -n --argjson s "$split" --arg d "$(date +%F)" '{
  apply_rules: false,
  transactions: [$s + {date: $d, description: "Valorisation PEA", category_name: "Valorisation", tags: ["valorisation"]}]
}')
api /transactions "$body" | jq -r '"Booked transaction " + .data.id'
