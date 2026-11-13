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

### 第 5 步（可选，Muse 做）：配一个消息值守

如果你想让 Muse 主动盯着消息（例如和另一个 agent 在同一个群里协作），让它再做两件事。

**5.1 放置 relay 文件并写本机配置**

把 `relay/` 下的脚本放到 `~/workspace/telegram-relay/`，再在该目录建一个 `local.json`（只放本机、不进仓库），把第 4 步 get-me 返回的 bot 身份写进去：

```json
{"bot_username": "...", "bot_id": 123456789, "bot_name_keywords": ["你的 bot 显示名关键词"]}
```

可选的访问控制：

- `"owner_ids": [你的 Telegram user id]`：只有你的私聊算相关消息，陌生人的私聊被静默丢弃（不打 👀、不进队列，只记入本机 dropped.log 备查）。
- `"group_ids": [群 id]`：只监听名单内的群，其余群的消息静默丢弃；bot 被拉进新群的事件不会丢，值守仍能注意到并拿到新群 id。不配则它所在的所有群都算。

跑起来之后你会看到的行为：相关消息被拉到的瞬间会打上 👀（已读回执）；可能要回复时会保持「正在输入」状态，直到消息处理完；某条消息超过约 5 分钟还没处理完（典型是 agent 卡在宿主应用的确认卡上），看门狗会自己在会话里发一条提示。

**5.2 运行模式：常驻监听＋systemd 托管**

`listener.py` 是零 LLM 的长轮询守护进程，自己循环拉取、落队列、刷心跳（`listener-state.json`）。再配一个低频的 hook 或定时任务：队列里有未处理消息时唤醒 agent 回复；心跳过期时按托管规程恢复进程。值守的行为边界（什么时候发言、分歧几轮、什么时候找你）写在任务指令里，按需要改。

用 systemd 托管它（文件在 `systemd/`）：只靠 agent 回合拉起的进程活不长（实测脱离运行中位寿命约 7 分钟），每次死亡都要唤醒 agent 复活。`tg-listener.service` 用 `Restart=always` 让进程被杀后 3 秒内自动拉起（已实测）；`install.sh` 负责把 unit 装到 `/etc/systemd/system/` 并启用，同时把当前环境的出口代理变量快照成 `systemd/egress.env` 供服务出网——**该文件含运行时代理凭据，只放本机、绝不提交进仓库**（`install.sh` 本身只是生成它，可以提交）。注意：VM/运行时替换会抹掉 unit 并轮换代理凭据，替换后需由盯心跳的 hook 或兜底任务重跑 `install.sh` 恢复托管，脱离启动只作最后兜底。实测 24 小时（期间 VM 被多次替换）：systemd 实例零自行死亡、消息零丢失，未确认的 updates 在 Telegram 侧保留约 24 小时，短时中断不会漏消息。

## 它能做什么

- 以你的 Telegram bot 身份调用 Bot API：查身份（getMe）、拉新消息（getUpdates）、发消息（sendMessage，支持回复和话题）、查会话（getChat），外加 webhook 三件套（setWebhook / getWebhookInfo / deleteWebhook）
- bot token 只存放在 Muse 的保险库里，脚本通过运行时的凭据交换使用，代码、文档、日志里不出现 token 明文
- 附带消息值守：新消息落盘成队列文件并维护 offset 水位，配合 hook 或定时任务做消息值守

## 仓库结构

```text
connector/
  connector.yaml        连接器描述
  CONNECTOR.md          连接器操作文档（你的 Muse 日常调用时读它）
  bin/tg.py             Bot API 命令行助手
relay/
  fetch.py              getUpdates 队列化脚本（offset 水位 + 相关消息粗筛 + 👀 已读反应），listener 的拉取核心，也可单独直调补漏
  listener.py           零 LLM 常驻长轮询守护进程（心跳文件 + 外部恢复）
  typing_keeper.py      保持「正在输入」指示直到消息处理完的小守护脚本
  stuck_watchdog.py     单条消息的卡死看门狗：久未处理时在会话里发一条提示
systemd/
  tg-listener.service   systemd 托管 unit（Restart=always，3 秒自愈）
  install.sh            托管安装/恢复脚本（刷新 egress.env + 装 unit + 重启服务）
```

## 已知限制

- 消息监听靠长轮询，回复只能发生在 Muse 的 agent 回合里，所以 bot 的回复延迟是分钟级，做不到秒回。推荐 listener 常驻进程＋systemd 托管：凭据逐请求交换、进程内不驻留 token，死亡基本只剩 VM/运行时替换这一种，且可自动恢复。
- Webhook 命令已备好，但需要一个 Telegram 能访问的公网 HTTPS 接收端，且接收后仍需解决如何唤醒 agent，是否采用按你自己的环境权衡。
- bot 只能看到它加入的会话的消息；未确认的 updates 在 Telegram 侧只保留约 24 小时，值守中断超过这个时长会漏消息。

## 安全性

- 不要把 bot token 写进任何文件、命令参数或聊天记录，唯一存放处是 Muse 保险库。
- `tg.py` 禁用了重定向，请求只发往 `api.telegram.org`。

## 背景

这个连接器源于一个真实需求：让 Muse 和另一个 agent 在同一个 Telegram 群里直接沟通、分歧时找人裁决。官方没有现成的，就按自定义连接器规范搭了一个，已在实际使用中跑通群消息值守，现整理开源出来。

## License

MIT
