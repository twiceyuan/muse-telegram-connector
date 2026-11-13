#!/usr/bin/env bash
# One-shot deployment for muse-telegram-connector.
#
# Run from inside a clone of this repository:
#     bash deploy.sh [--skip-systemd]
#
# What it does (idempotent, safe to re-run):
#   1. Symlinks the connector files and relay scripts from this clone
#      into the Muse workspace layout. Links, never copies: the clone
#      stays the single source of truth and updates are `git pull`.
#      A pre-existing regular file at a link target is moved aside to
#      <name>.pre-deploy.bak instead of being overwritten.
#   2. Creates telegram-relay/local.json from a template if missing
#      (per-machine config; never committed). An existing file is
#      left untouched.
#   3. Installs the systemd hosting for the listener via
#      systemd/install.sh (unit + egress.env snapshot), unless
#      --skip-systemd is given or systemctl is unavailable.
#
# What it does NOT do (a human or an agent step, by design):
#   - Create the bot / save its token (BotFather + secure entry).
#   - Fill in local.json values (bot id from get-me, your chat ids).
#   - Wire the wake-up hook / scheduled task in the agent runtime.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="${MUSE_WORKSPACE:-$HOME/workspace}"
SKIP_SYSTEMD=0
[ "${1:-}" = "--skip-systemd" ] && SKIP_SYSTEMD=1

link_one() {
  local target="$1" source="$2"
  mkdir -p "$(dirname "$target")"
  if [ -L "$target" ]; then
    if [ "$(readlink "$target")" = "$source" ]; then
      echo "ok    $target"
    else
      ln -sfn "$source" "$target"
      echo "link  $target -> $source (replaced previous link)"
    fi
  elif [ -e "$target" ]; then
    mv "$target" "$target.pre-deploy.bak"
    ln -s "$source" "$target"
    echo "link  $target -> $source (previous file kept as $target.pre-deploy.bak)"
  else
    ln -s "$source" "$target"
    echo "link  $target -> $source"
  fi
}

CONN="$WS/custom-connectors/custom.telegram-bot"
link_one "$CONN/connector.yaml" "$SRC/connector/connector.yaml"
link_one "$CONN/CONNECTOR.md"   "$SRC/connector/CONNECTOR.md"
link_one "$CONN/bin/tg.py"      "$SRC/connector/bin/tg.py"

RELAY="$WS/telegram-relay"
for f in fetch.py listener.py typing_keeper.py stuck_watchdog.py; do
  link_one "$RELAY/$f" "$SRC/relay/$f"
done
link_one "$RELAY/systemd/tg-listener.service" "$SRC/systemd/tg-listener.service"
link_one "$RELAY/systemd/install.sh"          "$SRC/systemd/install.sh"

if [ -e "$RELAY/local.json" ]; then
  echo "ok    $RELAY/local.json (existing, untouched)"
else
  cat > "$RELAY/local.json" <<'JSON'
{
  "bot_id": null,
  "bot_name_keywords": [],
  "group_ids": [],
  "owner_ids": []
}
JSON
  echo "write $RELAY/local.json (template - fill in bot_id / owner_ids / group_ids)"
fi

if [ "$SKIP_SYSTEMD" = "1" ]; then
  echo "skip  systemd hosting (--skip-systemd)"
elif command -v systemctl >/dev/null 2>&1; then
  bash "$RELAY/systemd/install.sh"
  echo "done  systemd hosting installed (tg-listener)"
else
  echo "warn  systemctl not found - run listener.py detached instead and supervise its heartbeat"
fi

echo
echo "Deployment files are in place. Remaining human/agent steps:"
echo "  1. Create the bot in BotFather and save its token (secure entry - never in a file or in chat)."
echo "  2. Verify with tg.py get-me, then fill local.json: bot_id from get-me, owner_ids with your chat id, group_ids with the groups to watch."
echo "  3. Wire a wake-up hook / scheduled task in the agent runtime per the README (Step 5)."
