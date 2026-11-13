# muse-telegram-connector

[English](README.en.md) | 中文

让 [Muse](https://muse.ai)（Meta 的个人 AI 助手）以一个 Telegram bot 的身份收发消息的自定义连接器。Muse 没有官方 Telegram 连接器，这个项目按它自己的自定义连接器规范补上。

## 部署方法：把本仓库发给你的 Muse

你不需要自己动手装。把本仓库的链接发给你的 Muse，跟它说一句「按 README 部署这个 Telegram 连接器」，它会照下面的步骤一步步完成，你只需要在第 1 步建 bot、第 2 步填一次 token。

### 第 1 步（你来做）：在 BotFather 建 bot

1. 在 Telegram 里打开 @BotFather，发送 `/newbot`，按提示建一个 bot，保存它发给你的 token。
2. 再给 BotFather 发 `/setprivacy`，选你的 bot，设为 **Disable**。这样 bot 在群里能看到全部消息（把 bot 设为群管理员有同样效果）。
3. 回到和 Muse 的对话，说一句「bot 建好了」。

### 第 2 步（Muse 做）：登记 token 到保险库

Muse 调用凭据登记，参数如下，然后把生成的安全页面链接发给你，你在页面里填入第 1 步的 token（只进保险库，不经过聊天记录）：

```json
{
  "provider": "telegram-bot",
  "auth_scheme": "api_key",
  "placement": "url_path_segment:/bot{}",
  "api_hosts": ["api.telegram.org"]
}
```

### 第 3 步（Muse 做）：放置连接器文件

把本仓库的文件按下面的对应关系放进 Muse 的工作区：

| 本仓库路径 | 放到 |
| --- | --- |
| `connector/connector.yaml` | `~/workspace/custom-connectors/custom.telegram-bot/connector.yaml` |
| `connector/CONNECTOR.md` | `~/workspace/custom-connectors/custom.telegram-bot/CONNECTOR.md` |
| `connector/bin/tg.py` | `~/workspace/custom-connectors/custom.telegram-bot/bin/tg.py` |

### 第 4 步（Muse 做）：验证

运行：

```text
python3 ~/workspace/custom-connectors/custom.telegram-bot/bin/tg.py get-me
```

返回 `ok: true` 即部署成功，输出里的 `result.username` 和 `result.id` 就是你的 bot 身份。如果返回 401，是 token 不对或已被吊销，回到 BotFather 用 `/mybots` 查看当前 token 后重新登记。

完成后你就可以把 bot 拉进群，或者直接私聊它给你的 Muse 留言。

### 第 5 步（可选，Muse 做）：配一个消息值守任务

如果你想让 Muse 主动盯着群消息（例如和另一个 agent 在群里协作），让它再做三件事：

1. 把 `relay/fetch.py`、`relay/watch.py`、`relay/typing_keeper.py`、`relay/stuck_watchdog.py` 和 `relay/listener.py` 都放到 `~/workspace/telegram-relay/`，再在该目录建一个 `local.json`，把第 4 步 get-me 返回的 bot 身份写进去（`{"bot_username": ..., "bot_id": ..., "bot_name_keywords": [...]}`）。这个文件只放本机、不进仓库。可选项：再加一个 `"owner_ids": [你的 Telegram user id]`，陌生人的私聊就会被静默丢弃（不打 👀、不触发输入状态、不进队列，只记入本机 dropped.log 备查）；不配则所有私聊都算相关消息。群聊也可以用 `"group_ids": [群 id]` 限制为只监听名单内的群，其余群的消息同样静默丢弃（但 bot 被拉进新群的事件不会丢，值守仍会注意到、也能拿到新群 id 以便加进名单）；不配则它所在的所有群都算。fetch.py / watch.py 拉到相关消息会立刻打 👀 反应（已读回执），并在可能要回复时拉起 typing_keeper.py 保持「正在输入」直到消息被标记处理完，同时拉起 stuck_watchdog.py 盯住这条消息：超过约 5 分钟还没处理完（典型情况是 agent 卡在宿主应用的确认卡上），它会自己在会话里发一条提示，消息处理完就自动退出；watch.py 以 600 秒为一片做长轮询。可选的常驻模式：`listener.py` 是零 LLM 的长轮询守护进程，自己循环拉取并落盘，agent 只在队列里有未处理消息时被唤醒回复、以及进程心跳过期时被唤醒复活它（靠 hook 或低频定时任务盯 `listener-state.json`）；它随 VM/运行时替换而死，但 offset 纪律保证复活后不漏消息（Telegram 侧未确认 updates 保留约 24 小时）。
2. 用 `relay/watch-task.md` 的内容作为定时任务的指令模板（替换其中的占位符），建一个每 10 分钟运行的定时任务。模板用「监督者＋短 watcher」机制：每轮先查 watcher 心跳，健康就秒退；watcher 一任约 60 分钟，靠 watch.py 的 `--wait-lock` 在文件锁上排队无缝交接。
3. 值守的行为边界（什么时候发言、分歧几轮、什么时候找你）都写在模板里，可按你的需要改。

#### systemd 托管 listener（推荐）

上面第 1 条里的 `listener.py` 如果只靠 hook/定时任务拉起，进程本身仍会在几分钟到一两小时后无声死亡（实测脱离运行的中位寿命只有约 7 分钟），每次死亡都要唤醒一次 agent 来复活。用 systemd 托管可以治本：

- `systemd/tg-listener.service`：`Restart=always` + `RestartSec=3`，进程被 kill -9 后 3 秒内自动拉起（已实测）；`listener.lock` 保证同一时间只有一个实例，`listener.stop` 文件存在时不启动（维护开关）。
- `systemd/install.sh`：把 unit 装到 `/etc/systemd/system/` 并 `daemon-reload` + `enable` + `restart`。它还会把当前环境的出口代理变量快照成 `systemd/egress.env`（600 权限），因为 unit 的 `EnvironmentFile` 要用它来出网——**这个文件含运行时代理凭据，只放本机，绝不提交进仓库**；`install.sh` 本身只是从当前环境生成它，可以提交。
- VM/运行时替换会抹掉 `/etc/systemd/system/` 下的 unit（也轮换代理凭据），所以替换后监听会停，直到 hook 或每小时兜底任务发现心跳过期、重跑 `install.sh` 恢复托管（脱离启动只作最后兜底）。24 小时实测（2026-11-12 20:06 至 2026-11-13 20:17）：VM 被替换 13 次，systemd 实例零自行死亡、消息零丢失；Telegram 相关 hook 的输入 token 从试点一天的约 2580 万降到约 1155 万（-55%）。

## 它能做什么

- 以你的 Telegram bot 身份调用 Bot API：查身份（getMe）、拉新消息（getUpdates）、发消息（sendMessage，支持回复和话题）、查会话（getChat），外加 webhook 三件套（setWebhook / getWebhookInfo / deleteWebhook）
- bot token 只存放在 Muse 的保险库里，脚本通过运行时的凭据交换使用，代码、文档、日志里不出现 token 明文
- 附带消息值守：新消息落盘成队列文件并维护 offset 水位，配合定时任务做群消息值守

## 仓库结构

```text
connector/
  connector.yaml        连接器描述
  CONNECTOR.md          连接器操作文档（你的 Muse 日常调用时读它）
  bin/tg.py             Bot API 命令行助手
relay/
  fetch.py              getUpdates 队列化脚本（offset 水位 + 相关消息粗筛 + 👀 已读反应）
  watch.py              长轮询值守切片（600 秒一片，文件锁 + --wait-lock 无缝交接）
  typing_keeper.py      保持「正在输入」指示直到消息处理完的小守护脚本
  stuck_watchdog.py     单条消息的卡死看门狗：久未处理时在会话里发一条提示
  listener.py           零 LLM 常驻长轮询守护进程（可选模式，心跳文件 + 外部复活）
  watch-task.md         消息值守定时任务的指令模板（监督者＋短 watcher 机制）
systemd/
  tg-listener.service   systemd 托管 unit（Restart=always，3 秒自愈）
  install.sh            重装托管脚本（刷新 egress.env + 装 unit + 重启服务）
```

## 已知限制

- 消息监听靠长轮询。回复只能发生在 Muse 的 agent 回合里，所以 bot 的回复延迟仍是分钟级，做不到秒回。拉取有两种跑法：watch.py 切片只能在 agent 回合里跑；listener.py 常驻进程由 agent 回合拉起后可以自己持续拉取（凭据是逐请求交换的，进程内不驻留 token），但它活不过 VM/运行时替换，需要 hook 或定时任务盯心跳复活；推荐用 `systemd/` 的托管方式（见第 5 步），可将死亡收敛到只剩 VM 替换本身。
- Webhook 命令已备好，但需要一个 Telegram 能访问的公网 HTTPS 接收端，且接收后仍需解决如何唤醒 agent，是否采用按你自己的环境权衡。
- bot 只能看到它加入的会话的消息；未确认的 updates 在 Telegram 侧只保留约 24 小时，值守中断超过这个时长会漏消息。

## 安全性

- 不要把 bot token 写进任何文件、命令参数或聊天记录，唯一存放处是 Muse 保险库。
- `tg.py` 禁用了重定向，请求只发往 `api.telegram.org`。

## 背景

这个连接器源于一个真实需求：让 Muse 和另一个 agent 在同一个 Telegram 群里直接沟通、分歧时找人裁决。官方没有现成的，就按自定义连接器规范搭了一个，已在实际使用中跑通群消息值守，现整理开源出来。

## License

MIT
