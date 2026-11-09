#!/usr/bin/env python3
"""Fetch new Telegram updates into a local queue file.

Designed to be run from inside a Muse agent turn (a scheduled watch
task, for example), because only agent turns can use the connector
credential. Appends compact records to queue.jsonl, persists the
getUpdates offset in state.json, and prints a digest. Each fresh
relevant message gets a 👀 reaction at once (read receipt) and, when a
reply is plausible, a typing indicator kept alive by a detached
typing_keeper.py until the message is marked handled:

- "NONE" when nothing relevant arrived
- "RELEVANT <n>" plus one compact line per relevant update
- "ERROR <description>" (exit 1) when the API call failed; the offset
  is not advanced in that case

Relevant means: any update in a group/supergroup chat, any private
message to the bot, any my_chat_member change (bot added/removed),
any message from another bot, and anything mentioning the bot.

Setup: tell the scripts who your bot is in a local.json file placed
in the relay directory (TG_RELAY_DIR, where queue.jsonl lives), e.g.
{"bot_username": "your_bot_username", "bot_id": 123456789,
"bot_name_keywords": ["your", "bot", "nicknames"]}, with the values
from `tg.py get-me`. That file is local-only and never committed; the
same keys can also come from TG_BOT_USERNAME / TG_BOT_ID /
TG_BOT_NAME_KEYWORDS (comma-separated) environment variables, which
take precedence. Point TG_CONNECTOR_BIN at the folder holding tg.py
if you placed it somewhere else.
"""
import json
import os
import sys

CONNECTOR_BIN = os.environ.get(
    "TG_CONNECTOR_BIN",
    os.path.expanduser("~/workspace/custom-connectors/custom.telegram-bot/bin"),
)
sys.path.insert(0, CONNECTOR_BIN)
import tg  # noqa: E402

BASE = os.environ.get(
    "TG_RELAY_DIR", os.path.expanduser("~/workspace/telegram-relay"))
STATE = os.path.join(BASE, "state.json")
QUEUE = os.path.join(BASE, "queue.jsonl")


def load_local_config() -> dict:
    """Bot identity for this deployment; never committed to the repo.

    Precedence: TG_BOT_USERNAME / TG_BOT_ID / TG_BOT_NAME_KEYWORDS
    environment variables, then local.json in the relay directory,
    then local.json next to this script. Missing values fall back to
    the placeholders below, which match nothing.
    """
    cfg = {}
    for path in (os.path.join(BASE, "local.json"),
                 os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "local.json")):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                cfg.update(json.load(fh))
        except Exception:
            pass
    if os.environ.get("TG_BOT_USERNAME"):
        cfg["bot_username"] = os.environ["TG_BOT_USERNAME"]
    if os.environ.get("TG_BOT_ID"):
        try:
            cfg["bot_id"] = int(os.environ["TG_BOT_ID"])
        except ValueError:
            pass
    if os.environ.get("TG_BOT_NAME_KEYWORDS"):
        cfg["bot_name_keywords"] = [
            w.strip() for w in
            os.environ["TG_BOT_NAME_KEYWORDS"].split(",") if w.strip()]
    return cfg


_CONFIG = load_local_config()
BOT_USERNAME = _CONFIG.get("bot_username", "your_bot_username")
BOT_ID = int(_CONFIG.get("bot_id", 0) or 0)

# Optional: words that count as naming the bot in group text (its
# display name, for example). A group message from another bot that
# mentions the bot by @username or by one of these words also gets the
# typing indicator.
BOT_NAME_KEYWORDS = tuple(_CONFIG.get("bot_name_keywords", ()))


def load_offset() -> int:
    try:
        with open(STATE, "r", encoding="utf-8") as fh:
            return int(json.load(fh).get("offset", 0))
    except Exception:
        return 0


def save_offset(offset: int) -> None:
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"offset": offset}, fh)
    os.replace(tmp, STATE)


def compact(update: dict) -> dict:
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    sender = msg.get("from") or {}
    record = {
        "update_id": update.get("update_id"),
        "kind": "message" if "message" in update else
                "edited_message" if "edited_message" in update else
                "my_chat_member" if "my_chat_member" in update else "other",
        "message_id": msg.get("message_id"),
        "date": msg.get("date"),
        "chat_id": chat.get("id"),
        "chat_type": chat.get("type"),
        "chat_title": chat.get("title"),
        "thread_id": msg.get("message_thread_id"),
        "from_id": sender.get("id"),
        "from_name": sender.get("first_name"),
        "from_username": sender.get("username"),
        "from_is_bot": sender.get("is_bot", False),
        "text": msg.get("text") or msg.get("caption"),
        "reply_to_message_id": (msg.get("reply_to_message") or {}).get("message_id"),
        "new_chat_members": [m.get("username") for m in msg.get("new_chat_members", [])],
    }
    if "my_chat_member" in update:
        mcm = update["my_chat_member"]
        record["chat_id"] = (mcm.get("chat") or {}).get("id")
        record["chat_type"] = (mcm.get("chat") or {}).get("type")
        record["chat_title"] = (mcm.get("chat") or {}).get("title")
        record["text"] = "my_chat_member: " + json.dumps(
            mcm.get("new_chat_member", {}), ensure_ascii=False)[:200]
    return record


def is_relevant(record: dict) -> bool:
    if record["from_id"] == BOT_ID:
        return False
    if record["kind"] == "my_chat_member":
        return True
    if record["chat_type"] in ("group", "supergroup", "private"):
        return True
    if record.get("from_is_bot"):
        return True
    if record.get("text") and ("@" + BOT_USERNAME) in record["text"]:
        return True
    return False


def needs_typing(record: dict) -> bool:
    """Whether an incoming relevant message should show typing at once.

    Private chats always (only the owner talks to the bot there). In
    groups only when a human writes or the bot is named, so other
    bots' routine acknowledgements don't flash a typing indicator for
    a message that will get no reply.
    """
    if record.get("kind") != "message" or not record.get("message_id"):
        return False
    if record.get("chat_type") == "private":
        return True
    if record.get("chat_type") in ("group", "supergroup"):
        if not record.get("from_is_bot"):
            return True
        text = record.get("text") or ""
        if ("@" + BOT_USERNAME) in text:
            return True
        low = text.lower()
        if any(word in low for word in BOT_NAME_KEYWORDS):
            return True
    return False


def signal_typing(record: dict) -> None:
    """Best-effort typing indicator the moment a relevant message lands.

    Telegram typing lasts ~5s but agent turns take minutes, so spawn a
    detached keeper (typing_keeper.py, placed next to this script's
    data directory) that refreshes it until the message is marked
    handled. Never blocks the fetch loop.
    """
    import subprocess
    if not needs_typing(record):
        return
    key = "%s:%s" % (record["chat_id"], record["message_id"])
    try:
        subprocess.Popen(
            [sys.executable, os.path.join(BASE, "typing_keeper.py"),
             str(record["chat_id"]), key],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    except Exception:
        pass


def mark_read(record: dict) -> None:
    """Best-effort 👀 reaction on a message just pulled (read receipt).

    Only for fresh (non-edited) messages with an id; failures are
    ignored so a reaction problem never blocks the fetch loop.
    """
    if record.get("kind") != "message" or not record.get("message_id"):
        return
    try:
        tg.call("setMessageReaction", {
            "chat_id": record["chat_id"],
            "message_id": record["message_id"],
            "reaction": [{"type": "emoji", "emoji": "👀"}],
        })
    except Exception:
        pass


def main() -> int:
    os.makedirs(BASE, exist_ok=True)
    offset = load_offset()
    result = tg.call("getUpdates", {
        "offset": offset,
        "timeout": 0,
        "limit": 100,
        "allowed_updates": ["message", "edited_message", "my_chat_member"],
    }, http_timeout=30)
    if not result.get("ok"):
        print("ERROR " + str(result.get("description", result))[:200])
        return 1
    updates = result.get("result", [])
    relevant = []
    max_id = offset - 1
    with open(QUEUE, "a", encoding="utf-8") as qf:
        for update in updates:
            record = compact(update)
            qf.write(json.dumps(record, ensure_ascii=False) + "\n")
            max_id = max(max_id, int(update.get("update_id", 0)))
            if is_relevant(record):
                relevant.append(record)
                mark_read(record)
                signal_typing(record)
    if updates:
        save_offset(max_id + 1)
    if not relevant:
        print("NONE")
        return 0
    print(f"RELEVANT {len(relevant)}")
    for r in relevant:
        line = {
            "chat_id": r["chat_id"], "chat_type": r["chat_type"],
            "chat_title": r["chat_title"], "thread_id": r["thread_id"],
            "from": r["from_username"] or r["from_name"],
            "from_is_bot": r["from_is_bot"],
            "message_id": r["message_id"],
            "text": (r["text"] or "")[:300],
        }
        print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
