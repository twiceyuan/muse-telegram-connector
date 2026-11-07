#!/usr/bin/env python3
"""Example: fetch new Telegram updates into a local queue file.

Designed to be run from inside a Muse agent turn (a scheduled watch
task, for example), because only agent turns can use the connector
credential. Appends compact records to queue.jsonl, persists the
getUpdates offset in state.json, and prints a digest:

- "NONE" when nothing relevant arrived
- "RELEVANT <n>" plus one compact line per relevant update
- "ERROR <description>" (exit 1) when the API call failed; the offset
  is not advanced in that case

Relevant means: any update in a group/supergroup chat, any private
message to the bot, any my_chat_member change (bot added/removed),
any message from another bot, and anything mentioning the bot.

Setup: fill in BOT_USERNAME and BOT_ID from `tg.py get-me`, and point
TG_CONNECTOR_BIN at the folder holding tg.py if you placed it
somewhere else.
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

# Fill these in from `tg.py get-me`.
BOT_USERNAME = "your_bot_username"
BOT_ID = 0


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
