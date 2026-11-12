#!/usr/bin/env bash
# Creates demo keys A (analytics) and B (support) via /key/generate.
# Writes them to .keys.env (git-ignored). Usage: scripts/create_keys.sh
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
BASE="${LITELLM_URL:-http://localhost:4000}"

gen() {
  curl -sS "$BASE/key/generate" \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' -d "$1" |
    python3 -c 'import sys,json; print(json.load(sys.stdin)["key"])'
}

# Teams are created first so keys can be attached to them (team_id = alias here for readability).
for t in analytics support; do
  curl -sS "$BASE/team/new" -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' \
    -d "{\"team_id\":\"$t\",\"team_alias\":\"$t\"}" >/dev/null || true
done

KEY_A=$(gen '{"key_alias":"key-a-analytics","team_id":"analytics","models":["gpt-4o-mini","claude-sonnet"],"max_budget":1}')
KEY_B=$(gen '{"key_alias":"key-b-support","team_id":"support","models":["gpt-4o-mini"],"max_budget":1,"rpm_limit":10}')
umask 077
printf 'KEY_A=%s\nKEY_B=%s\n' "$KEY_A" "$KEY_B" > .keys.env
echo "Created key A (analytics: gpt-4o-mini, claude-sonnet, budget 1) and key B (support: gpt-4o-mini, budget 1, rpm 10)."
echo "Saved to .keys.env"
