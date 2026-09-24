# 芯片前沿雷达

每天从 arXiv、GitHub 和硬件新闻源搜集 DSP、FPGA、可重构计算及嵌入式信息，筛选近期条目并发送一条手机简报。默认送达**个人微信**：使用 Server酱 Turbo；也支持 Bark、Telegram 和企业微信群机器人。代码仅用 Python 标准库，不需要 AI API。

## 先看效果

需要 Python 3.11 或更新版本。在项目目录运行：

```powershell
python -m frontier_watch --sample
```

这条命令使用离线演示数据，**不推送、不记录已发送条目**。查看真实来源目前能筛出什么：

```powershell
python -m frontier_watch --dry-run
```

简报列出标题、主题、来源、简介和原文链接。英文来源的标题与简介保留原文，避免自动翻译误读技术名词。

## 不建 GitHub 仓库：在 Windows 每天发到个人微信

1. 在 [Server酱 Turbo](https://sct.ftqq.com/docs/getting-started/sendkey/) 用微信扫码登录，获取以 `SCT` 开头的 SendKey，并按其页面完成微信接收渠道设置。**不要把 SendKey 发到聊天或写进仓库。**
2. 在项目目录打开 PowerShell，运行下方安装命令。它会以隐藏输入方式询问 SendKey，用当前 Windows 账户的 DPAPI 加密后保存在 `%LOCALAPPDATA%\FrontierWatch\sendkey.dpapi`，再创建每天 **09:17** 的 `FrontierWatchDaily` 计划任务。

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_windows.ps1
   ```

3. 在「任务计划程序」中找到 `FrontierWatchDaily`，右键 **运行**，检查微信收到的第一期简报；也可在 PowerShell 执行 `Start-ScheduledTask -TaskName FrontierWatchDaily`。任务使用安装时登录的 Windows 账户运行。电脑需在运行时联网并保持该账户登录；错过时间时会在任务计划程序认为可用后补跑。

安装脚本只在本机存储加密凭据，不把 SendKey 放进任务命令行。想改时间，可重新运行安装脚本并加 `-At '08:30'`。要停用，打开任务计划程序禁用 `FrontierWatchDaily` 即可。

## GitHub 云端部署（可选）

1. 在 [Server酱 Turbo](https://sct.ftqq.com/docs/getting-started/sendkey/) 用微信扫码登录，按官方指引获取 `SendKey`，并在手机微信内完成接收渠道设置。免费额度目前为每天 5 条，足够每日简报。**不要把 SendKey 写进仓库或聊天。**
2. 在 GitHub 建立一个空仓库，将这个项目上传到仓库默认分支；打开 **Settings → Secrets and variables → Actions → New repository secret**，名称填 `SERVERCHAN_SENDKEY`，值填刚取得的 SendKey。
3. 在 **Settings → Actions → General → Workflow permissions** 确认工作流可写仓库内容；工作流需要提交 `data/sent.json`，以便第二天避开发过的条目。如果仓库有分支保护，请允许 GitHub Actions 更新默认分支。
4. 打开 **Actions → DSP FPGA 前沿简报 → Run workflow** 手动运行一次，检查微信消息与运行日志。之后会在北京时间**每天约 09:17** 自动运行；GitHub 定时任务可能延迟。没有符合条件的新信息时，本次安静结束。

定时配置在 [digest.yml](.github/workflows/digest.yml)。默认不需要设置 `PUSH_CHANNEL`；它的默认值为 `serverchan`。一次发送成功后，程序才把条目 ID 与规范化链接写入 `data/sent.json`。发送失败或预览时不会写状态。若各来源全部失败，程序报错且不会发送空简报。

## 其他手机渠道

在 GitHub 仓库的 **Actions variables** 中设置 `PUSH_CHANNEL`；凭据放 **Actions secrets**：

| `PUSH_CHANNEL` | 接收端 | 必需的 Secrets / Variables |
| --- | --- | --- |
| `serverchan`（默认） | 个人微信 | Secret `SERVERCHAN_SENDKEY` |
| `bark` | iPhone 的 [Bark](https://github.com/Finb/Bark/blob/master/docs/en-us/tutorial.md) | Secret `BARK_DEVICE_KEY`；自建时可设置 Variable `BARK_SERVER_URL` |
| `telegram` | [Telegram 机器人](https://core.telegram.org/bots/api) | Secrets `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` |
| `wecom` | [企业微信群机器人](https://developer.work.weixin.qq.com/document/path/91770) | Secret `WECOM_WEBHOOK_URL` |

Telegram 用户须先给机器人发送 `/start`，然后取得自己的 `chat_id`。企业微信机器人在企业微信 App 内接收，与个人微信不同。Bark 只用于 iPhone。所有渠道都经 HTTPS 请求发送；密钥不会写入日志或状态文件。

## 在本机手动运行

先在当前终端设置环境变量（以下为 PowerShell 示例），再运行：

```powershell
$env:PUSH_CHANNEL = "serverchan"
$env:SERVERCHAN_SENDKEY = "从 Server酱取得的密钥"
python -m frontier_watch --dry-run
python -m frontier_watch
```

本机运行后，`data/sent.json` 会留在本机。上面的 Windows 安装脚本已自动配置计划任务；手动设置环境变量只用于调试。需要离线验证时运行：

```powershell
python -m unittest discover -s tests -v
```

## 筛选逻辑与信息源

- 默认时间窗口是最近 72 小时，最多 8 条；可用 `--lookback-hours 48 --limit 5` 修改。
- 按 DSP、FPGA、RTL/HLS、RISC-V、MCU/SoC、嵌入式等主题关键词评估相关性。已推送的 ID 和规范化 URL 都会过滤。
- 想替换默认主题词，复制 [topics.json](examples/topics.json) 修改后运行 `python -m frontier_watch --dry-run --topics examples/topics.json`；定时工作流也可将 `--topics examples/topics.json` 加到运行命令中。
- 论文使用 [arXiv 官方 RSS](https://info.arxiv.org/help/rss.html)；项目使用 [GitHub Search API](https://docs.github.com/en/rest/search/search)，查找最近 14 天创建的相关仓库；新闻使用 [CNX Software](https://www.cnx-software.com/feed/) 和 [Hackaday](https://hackaday.com/blog/feed/) 的 RSS。来源错误会在日志中列出，不影响其他来源。
- 仅抓取公开摘要与链接，不抓取或转载全文。排序依据为关键词与发布时间，属于启发式筛选，不代表论文或项目质量评审。

## 参考项目

- [TrendRadar](https://github.com/sansan0/TrendRadar)：RSS、关键词和多渠道推送的通用实现。
- [agents-radar](https://github.com/duanyytop/agents-radar)：跨 GitHub/arXiv 等来源制作技术简报的思路。
- [arxiv-daily](https://github.com/yyyanbj/arxiv-daily)：arXiv 关键词追踪与 GitHub Actions 定时流程。

本项目是聚焦 DSP/FPGA/嵌入式的独立轻量实现，适合直接调整关键词或信息源。源码和测试在 `frontier_watch/`、`tests/`。
