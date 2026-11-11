# muse-telegram-connector

English | [中文](README.md)

A custom connector that lets [Muse](https://muse.ai) (Meta's personal AI assistant) read and send Telegram messages as a bot. Muse ships no official Telegram connector; this project fills the gap using Muse's own custom-connector mechanism.

## How to deploy: hand this repo to your Muse

You do not need to install anything by hand. Send this repository's link to your Muse and tell it "deploy this Telegram connector following the README". It will walk through the steps below; you only act in Step 1 (create the bot) and Step 2 (enter the token once).

### Step 1 (you): create a bot in BotFather

1. Open @BotFather in Telegram, send `/newbot`, follow the prompts to create a bot, and save the token it gives you.
2. Send `/setprivacy` to BotFather, pick your bot, and set it to **Disable**. This lets the bot see all messages in groups (making the bot a group admin has the same effect).
3. Go back to your Muse chat and say "the bot is ready".

### Step 2 (Muse): register the token in the vault

Muse registers an API credential with the parameters below and sends you a secure page link. Enter the token from Step 1 on that page (it goes into the vault only, never through chat):

```json
{
  "provider": "telegram-bot",
  "auth_scheme": "api_key",
  "placement": "url_path_segment:/bot{}",
  "api_hosts": ["api.telegram.org"]
}
```

### Step 3 (Muse): place the connector files

Copy this repository's files into the Muse workspace using this mapping:

| In this repo | Goes to |
| --- | --- |
| `connector/connector.yaml` | `~/workspace/custom-connectors/custom.telegram-bot/connector.yaml` |
| `connector/CONNECTOR.md` | `~/workspace/custom-connectors/custom.telegram-bot/CONNECTOR.md` |
| `connector/bin/tg.py` | `~/workspace/custom-connectors/custom.telegram-bot/bin/tg.py` |

### Step 4 (Muse): verify

Run:

```text
python3 ~/workspace/custom-connectors/custom.telegram-bot/bin/tg.py get-me
```

`ok: true` means the deployment works. `result.username` and `result.id` in the output are your bot's identity. A 401 means the token is wrong or was revoked: check the current token in BotFather under `/mybots` and register again.

After this you can add the bot to a group, or DM it to leave messages for your Muse.

### Step 5 (optional, Muse): set up a message watch

If you want Muse to actively watch group messages (for example, to coordinate with another agent in the same group), have it do three more things:

1. Copy `relay/fetch.py`, `relay/watch.py`, `relay/typing_keeper.py`, `relay/stuck_watchdog.py`, and `relay/listener.py` into `~/workspace/telegram-relay/`, then create a `local.json` in that directory with the bot identity from Step 4's get-me output (`{"bot_username": ..., "bot_id": ..., "bot_name_keywords": [...]}`). That file stays on your machine and never enters the repo. Optional: add `"owner_ids": [your Telegram user id]` and private messages from anyone else are dropped silently (no 👀 reaction, no typing indicator, no queue entry; they are logged to a local dropped.log for later review); without it, every private message counts as relevant. Group chats can be restricted the same way with `"group_ids": [chat id]`: only listed groups are watched and other groups' messages are dropped silently (the event of the bot being added to a new group is never dropped, so the watch still notices and can learn the new group's id for the allowlist); without it, every group the bot belongs to counts. fetch.py / watch.py react 👀 to each relevant message the moment it is pulled (a read receipt) and, when a reply is plausible, start typing_keeper.py to keep a "typing..." indicator alive until the message is marked handled, plus stuck_watchdog.py watching that one message: if it is still unhandled after about five minutes (the classic case is the agent being frozen on an approval prompt in the host app), the watchdog posts one hint into the chat by itself and exits once the message is handled; watch.py long-polls in 600-second slices. Optional resident mode: `listener.py` is a zero-LLM long-polling daemon that pulls and queues updates by itself; an agent is woken only to reply to unhandled queue records, or to revive the daemon when its heartbeat (listener-state.json) goes stale, checked by a hook or an infrequent scheduled task. It dies with VM/runtime replacements, but the offset discipline means a revived daemon loses nothing (Telegram keeps unconfirmed updates for about 24 hours).
2. Create a scheduled task (every 10 minutes) using the contents of `relay/watch-task.md` as the task instructions, with its placeholders replaced. The template uses a supervisor-plus-short-watcher pattern: each run first checks the watcher heartbeat and exits at once when healthy; a watcher serves a term of about 60 minutes, handing over seamlessly by queueing on a file lock with watch.py's `--wait-lock`.
3. The behavioral rules (when to speak, how many rounds of disagreement, when to escalate to you) live in that template; adjust them to taste.

## What it does

- Calls the Telegram Bot API as your own bot: identity (getMe), new messages (getUpdates), sending (sendMessage, with replies and forum topics), chat info (getChat), plus the webhook trio (setWebhook / getWebhookInfo / deleteWebhook)
- The bot token lives only in Muse's vault. Scripts use it through the runtime credential swap, so the token never appears in code, docs, or logs
- Ships a message watch: new updates land in a local queue file with a persistent offset watermark, ready to pair with a scheduled watch task

## Repository layout

```text
connector/
  connector.yaml        Connector descriptor
  CONNECTOR.md          Operating doc (your Muse reads it when calling the API)
  bin/tg.py             Bot API command-line helper
relay/
  fetch.py              getUpdates queue script (offset watermark + relevance pre-filter + 👀 read reactions)
  watch.py              Long-poll watch slice (600s slices, file lock + --wait-lock seamless handover)
  typing_keeper.py      Tiny keeper that holds a "typing..." indicator until a message is handled
  stuck_watchdog.py     Per-message stuck watchdog: posts one hint in the chat when handling stalls
  listener.py           Zero-LLM resident long-poll daemon (optional mode, heartbeat + external revival)
  watch-task.md         Instruction template for the message-watch scheduled task (supervisor + short watcher)
```

## Known limitations

- Listening is long-poll based. Replying can only happen inside Muse agent turns, so bot replies are minutes late, never instant. Pulling has two modes: watch.py slices run inside agent turns; a listener.py resident process, once launched from an agent turn, keeps pulling by itself (credentials are swapped per request and never resident in the process), but it does not survive VM/runtime replacements and needs a hook or scheduled task watching its heartbeat to revive it.
- The webhook commands are included, but they need a public HTTPS endpoint that Telegram can reach, and something still has to wake the agent after delivery. Whether that trade is worth it depends on your setup.
- A bot only sees chats it has joined. Telegram keeps unconfirmed updates for about 24 hours, so a watch that is down longer than that will miss messages.

## Security

- Never write the bot token into any file, command argument, or chat. Its only home is the Muse vault.
- `tg.py` disables redirects and only ever talks to `api.telegram.org`.

## Background

This connector grew out of a real need: letting Muse coordinate directly with another agent in the same Telegram group, escalating to a human when they disagree. There was no off-the-shelf option, so one was built to Muse's custom-connector spec and battle-tested running a group message watch. It is published here in case it saves you the same work.

## License

MIT
