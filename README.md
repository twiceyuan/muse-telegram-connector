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

1. 把 `relay/fetch.py`、`relay/watch.py` 和 `relay/typing_keeper.py` 都放到 `~/workspace/telegram-relay/`，再在该目录建一个 `local.json`，把第 4 步 get-me 返回的 bot 身份写进去（`{"bot_username": ..., "bot_id": ..., "bot_name_keywords": [...]}`）。这个文件只放本机、不进仓库。fetch.py / watch.py 拉到相关消息会立刻打 👀 反应（已读回执），并在可能要回复时拉起 typing_keeper.py 保持「正在输入」直到消息被标记处理完；watch.py 以 600 秒为一片做长轮询。
2. 用 `relay/watch-task.md` 的内容作为定时任务的指令模板（替换其中的占位符），建一个每 10 分钟运行的定时任务。模板用「监督者＋短 watcher」机制：每轮先查 watcher 心跳，健康就秒退；watcher 一任约 60 分钟，靠 watch.py 的 `--wait-lock` 在文件锁上排队无缝交接。
3. 值守的行为边界（什么时候发言、分歧几轮、什么时候找你）都写在模板里，可按你的需要改。

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
  watch-task.md         消息值守定时任务的指令模板（监督者＋短 watcher 机制）
```

## 已知限制

- 消息监听靠长轮询，拉取本身是秒级命中，但拉取和回复都只能发生在 Muse 的 agent 回合里（钩子和常驻系统服务都拿不到连接器凭据，这是 Muse 运行时的边界）。所以 bot 的回复延迟仍是分钟级，做不到秒回。
- Webhook 命令已备好，但需要一个 Telegram 能访问的公网 HTTPS 接收端，且接收后仍需解决如何唤醒 agent，是否采用按你自己的环境权衡。
- bot 只能看到它加入的会话的消息；未确认的 updates 在 Telegram 侧只保留约 24 小时，值守中断超过这个时长会漏消息。

## 安全性

- 不要把 bot token 写进任何文件、命令参数或聊天记录，唯一存放处是 Muse 保险库。
- `tg.py` 禁用了重定向，请求只发往 `api.telegram.org`。

## 背景

这个连接器源于一个真实需求：让 Muse 和另一个 agent 在同一个 Telegram 群里直接沟通、分歧时找人裁决。官方没有现成的，就按自定义连接器规范搭了一个，已在实际使用中跑通群消息值守，现整理开源出来。

## License

MIT
