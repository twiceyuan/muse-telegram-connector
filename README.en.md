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

### Step 3 (Muse): link the connector files into the workspace

Clone this repository to a stable location (for example `~/workspace/github-publish/muse-telegram-connector`), then **symlink** the connector files into the Muse workspace — do not copy them:

| Link (create in the workspace) | Target (file in the clone) |
| --- | --- |
| `~/workspace/custom-connectors/custom.telegram-bot/connector.yaml` | `connector/connector.yaml` |
| `~/workspace/custom-connectors/custom.telegram-bot/CONNECTOR.md` | `connector/CONNECTOR.md` |
| `~/workspace/custom-connectors/custom.telegram-bot/bin/tg.py` | `connector/bin/tg.py` |

Symlinks keep exactly one source of truth between the deployment and the repo: updating later is just a `git pull` in the clone and takes effect immediately; copied files inevitably drift away from the repo.

### Step 4 (Muse): verify

Run:

```text
python3 ~/workspace/custom-connectors/custom.telegram-bot/bin/tg.py get-me
```

`ok: true` means the deployment works. `result.username` and `result.id` in the output are your bot's identity. A 401 means the token is wrong or was revoked: check the current token in BotFather under `/mybots` and register again.

After this you can add the bot to a group, or DM it to leave messages for your Muse.

### Step 5 (optional, Muse): set up a message watch

If you want Muse to actively watch messages (for example, to coordinate with another agent in the same group), have it do two more things.

**5.1 Place the relay files and write the local config**

Symlink the scripts under `relay/` into `~/workspace/telegram-relay/` (pointing at the clone from Step 3, not copies, for the same reason), then create a `local.json` in that directory (stays on your machine, never enters the repo) with the bot identity from Step 4's get-me output:

```json
{"bot_username": "...", "bot_id": 123456789, "bot_name_keywords": ["keywords from your bot's display name"]}
```

Optional access control:

- `"owner_ids": [your Telegram user id]`: only your DMs count as relevant; private messages from anyone else are dropped silently (no 👀 reaction, no queue entry; they are logged to a local dropped.log for later review).
- `"group_ids": [chat id]`: only listed groups are watched and other groups' messages are dropped silently; the event of the bot being added to a new group is never dropped, so the watch still notices and can learn the new group's id. Without it, every group the bot belongs to counts.

Behavior you will see once it runs: each relevant message gets a 👀 reaction the moment it is pulled (a read receipt); while a reply is plausible, a "typing..." indicator is kept alive until the message is handled; and if one message stays unhandled for about five minutes (the classic case is the agent being frozen on an approval prompt in the host app), a watchdog posts one hint into the chat by itself.

**5.2 Run mode: resident listener under systemd**

`listener.py` is a zero-LLM long-polling daemon that pulls updates, queues them, and keeps a heartbeat (`listener-state.json`) fresh by itself. Pair it with an infrequent hook or scheduled task that wakes an agent to reply to unhandled queue records, and restores the daemon per the hosting notes below when the heartbeat goes stale. The behavioral rules (when to speak, how many rounds of disagreement, when to escalate to you) live in that task's instructions; adjust them to taste.

Host it under systemd (files in `systemd/`): a daemon launched from agent turns does not live long (a detached process lived about 7 minutes at the median in our runs), and every death costs an agent wake-up. `tg-listener.service` uses `Restart=always` so a killed process is back within 3 seconds (verified); `install.sh` installs the unit under `/etc/systemd/system/` and enables it, and snapshots the current environment's egress proxy variables into `systemd/egress.env` for the service to reach the network — **that file carries runtime proxy credentials, stays on your machine, and must never be committed** (`install.sh` itself only generates it, so it is safe to commit). Note: a VM/runtime replacement wipes the unit and rotates the proxy credentials, so after a replacement the heartbeat watcher or a backstop task must re-run `install.sh` to restore hosting; a detached start is only the last resort. In 24 hours of production use with multiple VM replacements, systemd-hosted instances never died on their own and no messages were lost; Telegram keeps unconfirmed updates for about 24 hours, so short outages miss nothing.

## What it does

- Calls the Telegram Bot API as your own bot: identity (getMe), new messages (getUpdates), sending (sendMessage, with replies and forum topics), chat info (getChat), plus the webhook trio (setWebhook / getWebhookInfo / deleteWebhook)
- The bot token lives only in Muse's vault. Scripts use it through the runtime credential swap, so the token never appears in code, docs, or logs
- Ships a message watch: new updates land in a local queue file with a persistent offset watermark, paired with a hook or scheduled task

## Repository layout

```text
connector/
  connector.yaml        Connector descriptor
  CONNECTOR.md          Operating doc (your Muse reads it when calling the API)
  bin/tg.py             Bot API command-line helper
relay/
  fetch.py              getUpdates queue script (offset watermark + relevance pre-filter + 👀 read reactions); the listener's pulling core, also runnable standalone for backfill
  listener.py           Zero-LLM resident long-poll daemon (heartbeat + external recovery)
  typing_keeper.py      Tiny keeper that holds a "typing..." indicator until a message is handled
  stuck_watchdog.py     Per-message stuck watchdog: posts one hint in the chat when handling stalls
systemd/
  tg-listener.service   systemd unit for hosting the listener (Restart=always, heals in 3s)
  install.sh            Hosting install/recovery script (refreshes egress.env + installs the unit + restarts the service)
```

## Known limitations

- Listening is long-poll based. Replying can only happen inside Muse agent turns, so bot replies are minutes late, never instant. The recommended setup is the resident listener under systemd: credentials are swapped per request and never resident in the process, deaths narrow down to VM/runtime replacements, and those recover automatically.
- The webhook commands are included, but they need a public HTTPS endpoint that Telegram can reach, and something still has to wake the agent after delivery. Whether that trade is worth it depends on your setup.
- A bot only sees chats it has joined. Telegram keeps unconfirmed updates for about 24 hours, so a watch that is down longer than that will miss messages.

## Security

- Never write the bot token into any file, command argument, or chat. Its only home is the Muse vault.
- `tg.py` disables redirects and only ever talks to `api.telegram.org`.

## Background

This connector grew out of a real need: letting Muse coordinate directly with another agent in the same Telegram group, escalating to a human when they disagree. There was no off-the-shelf option, so one was built to Muse's custom-connector spec and battle-tested running a group message watch. It is published here in case it saves you the same work.

## License

MIT
