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

1. Copy `examples/fetch.py` to `~/workspace/telegram-relay/fetch.py`, replacing the `BOT_USERNAME` and `BOT_ID` placeholders with the real values from Step 4's get-me output.
2. Create a scheduled task (every 5 minutes is a good default) using the contents of `examples/watch-task.md` as the task instructions, with its placeholders replaced.
3. The behavioral rules (when to speak, how many rounds of disagreement, when to escalate to you) live in that template; adjust them to taste.

## What it does

- Calls the Telegram Bot API as your own bot: identity (getMe), new messages (getUpdates), sending (sendMessage, with replies and forum topics), chat info (getChat), plus the webhook trio (setWebhook / getWebhookInfo / deleteWebhook)
- The bot token lives only in Muse's vault. Scripts use it through the runtime credential swap, so the token never appears in code, docs, or logs
- Ships a message-queue example: new updates land in a local queue file with a persistent offset watermark, ready to pair with a scheduled watch task

## Repository layout

```text
connector/
  connector.yaml        Connector descriptor
  CONNECTOR.md          Operating doc (your Muse reads it when calling the API)
  bin/tg.py             Bot API command-line helper
examples/
  fetch.py              getUpdates queue script (offset watermark + relevance pre-filter)
  watch-task.md         Instruction template for the message-watch scheduled task
```

## Known limitations

- Listening is polling-based, and fetching can only happen inside Muse agent turns (hooks and background system services cannot access connector credentials in the Muse runtime). Bot reactions are therefore minutes late, never instant.
- The webhook commands are included, but they need a public HTTPS endpoint that Telegram can reach, and something still has to wake the agent after delivery. Whether that trade is worth it depends on your setup.
- A bot only sees chats it has joined. Telegram keeps unconfirmed updates for about 24 hours, so a watch that is down longer than that will miss messages.

## Security

- Never write the bot token into any file, command argument, or chat. Its only home is the Muse vault.
- `tg.py` disables redirects and only ever talks to `api.telegram.org`.

## Background

This connector grew out of a real need: letting Muse coordinate directly with another agent in the same Telegram group, escalating to a human when they disagree. There was no off-the-shelf option, so one was built to Muse's custom-connector spec and battle-tested running a group message watch. It is published here in case it saves you the same work.

## License

MIT
