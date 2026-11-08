# Telegram Bot

- `custom.telegram-bot` connects Muse to the Telegram Bot API at `api.telegram.org`. It authenticates with the registered `api_key` credential, which is the bot token you created with BotFather for your own bot.

- Helpers live in `~/workspace/custom-connectors/custom.telegram-bot/bin/`. The helper `tg.py` offers get-me, get-updates, send-message, send-photo, get-chat, set-webhook, get-webhook-info and delete-webhook. `send-message` sends a typing chat action just before the message by default (use `--no-typing` to skip it); `send-photo --chat-id <id> --photo <file> [--caption ...]` sends an upload_photo chat action first, then uploads the local file.

## Connect

- The connection was registered with `credentials.request_api_access` and these details. Reuse them to reconnect:

```json
{
  "provider": "telegram-bot",
  "auth_scheme": "api_key",
  "placement": "url_path_segment:/bot{}",
  "api_hosts": ["api.telegram.org"]
}
```

- Before the first change in a conversation, prove access with a harmless read:

```text
python3 ~/workspace/custom-connectors/custom.telegram-bot/bin/tg.py get-me
```

## Credentials

- The registered connection holds the credential. Helpers import `/opt/muse/skills/custom-connector-setup/bin/dynamic_credentials.py`, which returns an `hsurr:` surrogate and places it where the provider reads the key. Muse swaps in the real credential only on an approved request to a registered host.

- Never put a key, token, password or cookie in this doc, a helper, a command argument, an environment variable or a log. Never ask the user to paste one in chat.

- Keep redirects disabled on authenticated requests.

- On a 401 or 403, check the request first. Confirm that the helper attached the credential, that the host is registered and that the placement and scopes match.

- Only when a request that carried the credential is still rejected, call `credentials.request_api_access` with the details above and `"reconnect": true`.

## Build the request URL

- Build Bot API URLs by concatenating the raw surrogate after `bot`, exactly as `tg.py` does through `dynamic_credential_entry`. The runtime swap matches the surrogate literally, so it must reach the request byte for byte: never percent-encode it, and never print a request URL.

## Verify the bot identity

- Read the bot account behind the stored token. This call changes nothing.

```text
python3 ~/workspace/custom-connectors/custom.telegram-bot/bin/tg.py get-me
```

- Read `result.username`, `result.id`, `result.can_join_groups` and `result.can_read_all_group_messages` from the JSON output. `can_read_all_group_messages` is true only when group privacy mode is off for the bot (BotFather `/setprivacy`, or make the bot a group admin).

## Fetch new messages

- Read the updates Telegram buffered for the bot. getUpdates with an offset confirms all earlier updates, so advance the offset only after the updates are safely stored. The example script `examples/fetch.py` in the repository owns that state and prints a NONE, RELEVANT or ERROR digest.

```text
python3 ~/workspace/telegram-relay/fetch.py
```

- The fetch step runs only inside agent turns, because hooks and system services have no connector credentials in the Muse runtime.

## Send a message

- Send a text message as the bot to a chat the bot belongs to. This changes state, so only send when the user asked for it or when a watch task's rules apply.

```text
python3 ~/workspace/custom-connectors/custom.telegram-bot/bin/tg.py send-message --chat-id <chat_id> --text "<text>"
```

- Add `--reply-to <message_id>` to reply to one message, and `--thread-id <message_thread_id>` for a forum topic inside a supergroup. Read the new `result.message_id` from the JSON output.

## Read a chat

- Read basic information about a chat by id or username. This call changes nothing.

```text
python3 ~/workspace/custom-connectors/custom.telegram-bot/bin/tg.py get-chat --chat-id <chat_id>
```

## Recover from errors

- Telegram answers 401 when the token format is right but the token is wrong or revoked. Ask the user to confirm the current token in BotFather under API Token, then reconnect.

- After a failed or timed-out change, check the current state with a read before trying again, because the first request may have completed.

## Limits

- The bot sees group messages only when group privacy mode is off for this bot. It cannot read chats it has not joined, and Telegram keeps unconfirmed updates for about 24 hours.

- A message watch has to poll from inside agent turns, so reactions are minutes late, never instant. Hooks and systemd services were both ruled out for polling, because hooks have no connector credentials and services do not inherit the tool environment or approvals.

## Related skills

- Use `muse.skill_search` to find other skills and `muse.connector_search` to find other connectors.
