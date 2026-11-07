#!/usr/bin/env python3
"""Telegram Bot API helper for the custom.telegram-bot connector in Muse.

The bot token never appears in this file. The URL is built with a
credential surrogate from Muse's dynamic_credentials helper, and the
real token is swapped in by the Muse runtime only on the outbound
request to api.telegram.org. Build the URL with the RAW surrogate, as
below: the swap matches it literally, so it must not be
percent-encoded. Never print request URLs (they carry the surrogate).
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry, read_json_response

# Must match the connector id you registered in Muse.
CREDENTIAL = "custom.telegram-bot"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused, verify the endpoint")


def call(method: str, params: dict, http_timeout: float = 40.0) -> dict:
    surrogate = str(dynamic_credential_entry(CREDENTIAL)["surrogate"]).strip()
    url = "https://api.telegram.org/bot" + surrogate + "/" + method
    body = json.dumps(params).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(
            request, timeout=http_timeout
        ) as response:
            return read_json_response(response)
    except urllib.error.HTTPError as exc:
        try:
            return read_json_response(exc)
        except Exception:
            return {"ok": False, "error_code": exc.code, "description": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram Bot API helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("get-me")

    p_upd = sub.add_parser("get-updates")
    p_upd.add_argument("--offset", type=int, default=None)
    p_upd.add_argument("--timeout", type=int, default=0)
    p_upd.add_argument("--limit", type=int, default=100)

    p_send = sub.add_parser("send-message")
    p_send.add_argument("--chat-id", required=True)
    p_send.add_argument("--text", required=True)
    p_send.add_argument("--reply-to", type=int, default=None)
    p_send.add_argument("--thread-id", type=int, default=None)

    p_chat = sub.add_parser("get-chat")
    p_chat.add_argument("--chat-id", required=True)

    p_wh = sub.add_parser("set-webhook")
    p_wh.add_argument("--url-file", required=True,
                      help="file holding the webhook base URL, no trailing slash")
    p_wh.add_argument("--webhook-config", required=True,
                      help="JSON file with path and secret for the receiver")

    sub.add_parser("get-webhook-info")
    sub.add_parser("delete-webhook")

    args = parser.parse_args()

    if args.cmd == "get-me":
        result = call("getMe", {})
    elif args.cmd == "get-updates":
        params = {"timeout": args.timeout, "limit": args.limit,
                  "allowed_updates": ["message", "edited_message", "my_chat_member"]}
        if args.offset is not None:
            params["offset"] = args.offset
        result = call("getUpdates", params, http_timeout=args.timeout + 30)
    elif args.cmd == "send-message":
        params = {"chat_id": args.chat_id, "text": args.text}
        if args.reply_to is not None:
            params["reply_parameters"] = {"message_id": args.reply_to}
        if args.thread_id is not None:
            params["message_thread_id"] = args.thread_id
        result = call("sendMessage", params)
    elif args.cmd == "get-chat":
        result = call("getChat", {"chat_id": args.chat_id})
    elif args.cmd == "set-webhook":
        with open(args.url_file, "r", encoding="utf-8") as fh:
            base_url = fh.read().strip().rstrip("/")
        with open(args.webhook_config, "r", encoding="utf-8") as fh:
            wh = json.load(fh)
        result = call("setWebhook", {
            "url": base_url + "/" + wh["path"],
            "secret_token": wh["secret"],
            "allowed_updates": ["message", "edited_message", "my_chat_member"],
            "drop_pending_updates": False,
        })
    elif args.cmd == "get-webhook-info":
        result = call("getWebhookInfo", {})
    elif args.cmd == "delete-webhook":
        result = call("deleteWebhook", {"drop_pending_updates": False})
    else:  # pragma: no cover
        return 2

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
