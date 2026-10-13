# 极致了 · 公众号与视频号 MCP 插件

**简体中文** | [English](README.en.md)

供 Codex 和兼容 MCP 的 Agent 查询微信公众号、文章和视频号。实现了所给文档的50个操作目录与受预算保护的调用入口；并非每个上游操作都已真实测试。

- [服务方官网](https://www.jzl.com/)
- [官方 API 文档](https://s.apifox.cn/410674f9-f451-4b4f-957a-5f54f243bc83)
- 接口域名：`https://www.dajiala.com`。本项目为独立第三方客户端。

支持公众号账号搜索、基础/主体信息、估算指标、当天/历史文章、贴图文章、正文/详情、阅读点赞、评论；视频号账号与视频搜索、作品/回放列表、ID、博主信息、互动/评论、分享与下载链接。返回服务方原始字段，额外附计费摘要。下载链接查询不下载媒体。

## 视频口播转写与批量处理

**转写流程集成在同一个jizhile-mcp插件中**，新增 `jizhile-transcription` 技能。通过本机ffmpeg分离音轨，再调用火山方舟音频理解模型转为文字；不再把视频标题当作口播文案。支持XLSX、CSV、JSON清单，原始视频URL或本地video_path，最多500条、顺序处理、分段、后台进度、取消和断点续跑。

需要ffmpeg/ffprobe（macOS可运行 `brew install ffmpeg`），并单独配置火山方舟Key。可让Agent打开 `jizhile_transcription_setup_local` 本机配置页，或在终端隐藏输入：

```sh
uv run jizhile-configure-ark
uv run jizhile-transcribe /absolute/path/videos.xlsx --ids 1,2,45
uv run jizhile-transcribe --resume BATCH_ID --max-budget-yuan 1 --confirm-charge --accept-balance-unavailable
uv run jizhile-transcribe --status BATCH_ID
```

第一条清单命令只准备和估算，第二条恢复命令才在确认的总预算内转写。默认使用 `doubao-seed-2-0-mini-260428`，比本插件支持的Lite参考单价低；每180秒分段，提取16kHz单声道48kbps MP3，通过Base64提交模型。完成后删除临时视频/音频，保留逐条TXT和含来源行、状态、分段、token用量的results.json，原始表格不变。默认输出在仓库外私密目录，也可指定空的output_dir。

火山Key独立存储在 `~/.config/jizhile-mcp/ark-credentials.json`（0600），支持 `JIZHILE_ARK_API_KEY`、`ARK_API_KEY`、`JIZHILE_ARK_CONFIG_FILE`。火山转写与极致了查询分别计账。**方舟运行时Key无法在本流程中核实火山账户余额，工具明确返回未知；不能把极致了余额或其100元余额保护套用于火山账户。** 每批须指定总预算，确认计费及余额不可查询；每段提交前仍检查单次10元、每日500元和批次预算。

转写费用按返回token和[参考价格](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh)估算，不是实际账单。默认Mini的非音频输入/音频输入/输出参考价为0.2/3/2元每百万token，Lite为0.6/9/3.6元（输入≤32K，读取于2026-10-13）。预留含输出上限与余量；输出不完整、超出预留、未知扣费或强制中断时停止，不自动重试。完成结果与相同音频分段可复用；失败直链不自动调用收费接口刷新。

这是自动音频转写，可能存在地名、人名、金额等同音字错误，需复核；不包含字幕OCR，也不会未经请求进行润色或事实更正。分段时间不是逐字字幕对齐。真实3条验证摘要见[脱敏回执](docs/transcription-test-receipt.json)，没有公开素材、文案、Key或签名视频URL。

## 安装与配置

需要 Python 3.11+ 和 uv：

```sh
git clone https://github.com/guangfuhao/jizhile-mcp.git
cd jizhile-mcp
uv sync --frozen --extra dev
uv run jizhile-configure
```

终端隐藏输入Key及可选附加码。也可在Agent中调用 `jizhile_setup_local`，通过限时本机网页配置。密钥默认保存于 `~/.config/jizhile-mcp/credentials.json`（0600），不会进入仓库。也支持 `JIZHILE_API_KEY`、`JIZHILE_VERIFYCODE`、`JIZHILE_CONFIG_FILE`。工具读取始终遮盖密钥。

Codex 从 GitHub 安装：

```sh
codex plugin marketplace add guangfuhao/jizhile-mcp
codex plugin add jizhile-mcp@jizhile-local
```

开发者从本地源码安装：

```sh
python3 scripts/package_plugin.py
codex plugin marketplace add /absolute/path/to/jizhile-mcp
codex plugin add jizhile-mcp@jizhile-local
```

其他MCP客户端使用 `mcp.json` 中的stdio配置，把 `${PLUGIN_ROOT}` 替换为项目绝对路径。启动器也可直接执行：`/absolute/path/to/jizhile-mcp/scripts/run_mcp.sh`。

## 调用与计费保护

1. `jizhile_balance` 查询余额和预算；`jizhile_compare` 比较适用方案；`jizhile_catalog` 获取参数。
2. `jizhile_quote_search` 或 `jizhile_quote` 生成10分钟有效的一次性报价，不执行业务查询。Agent须展示本次费用、价格依据、当前及预计余额。
3. 用户已授权的操作和预算内，调用 `jizhile_execute(quote_id, confirm_charge=true)`。示例/未知价格另需用户明确预留金额并接受价格不确定性。
4. 向用户报告实际扣费及最新余额。低于安全预留金额时提醒；未确定的费用不能写成0元。

默认限制：**单次10元、每日500元、保留100元余额**，北京时间按日统计。每次查询后的预计余额必须至少为100元；例如余额100.50元时，可执行预计0.50元的查询，余额低于100元时会阻止新的付费查询。用户明确要求修改后，可配置 `JIZHILE_SINGLE_LIMIT`、`JIZHILE_DAILY_LIMIT`、`JIZHILE_BALANCE_RESERVE`；已有环境变量配置仍优先生效。预算不能通过查询工具参数临时提高。

同Key共用私密SQLite账本；跨进程串行执行收费请求。凭证用后失效；调用前持久化预留，进程崩溃仍保留待核对状态。成功结果缓存5分钟并标明时间；缓存本次新增业务查询费0元，可用 `fresh=true` 强制刷新。缓存按Key隔离；本地存储路径为 `~/.local/share/jizhile-mcp/<key-fingerprint>/`，可由 `JIZHILE_STATE_DIR` 设置父目录。

无自动重试、自动分页、自动升级更贵接口。失败响应也读取 `cost_money`/`cost`；超时、费用缺失或超出预留立即阻止后续收费。用户核对服务方账单并给出该次真实费用后，用 `jizhile_reconcile` 修正本地待核对账目。

**限制：服务方没有文档化的单次最大扣费参数，本地预算不能阻止上游在单次请求内调价或超额扣费，也不能限制同Key在其它客户端消费。报价是本地估算与预留，不是服务方保证价格。异常发生后插件阻止后续付费调用。** 账本不应被删除来绕过预算。

## 经济方案对比

以下依据2026-10-13读取的接口文档；明确标价与响应示例严格区分，实际以接口账单为准。

|需求|可比较方案|费用依据与选择|
|---|---|---|
|搜索公众号账号|实时搜索 / 数据库搜索|实时1元/次；数据库0.20元/条，每页20条，可能4元。未验证size可降低数量，按至少4元预留。|
|搜索文章|搜全部文章 / 文章类目|文档均0.50元/次；按排序、时间范围和返回字段选择。|
|搜索视频|搜全部视频 / 视频类目|文档0.50 / 1元每次；满足需求时选搜全部。|
|精确定位视频号|指定名称获取ID / 账号搜索|前者响应示例0.20元；后者文档1元/次。两者搜索范围不同，前者需接受不确定价格。|
|公众号正文|HTML / Pro / 纯文本富文本 / 含视频|响应示例0.02 / 0.025 / 0.03 / 0.10元，字段不同，不视作等价，也不是已确认报价。|
|公众号基础互动|基础 / Pro|响应示例0.02 / 0.04元；只需基础字段时无需升级。|

优先复用已获得的标识、列表数据与缓存，避免重复搜索、转换和补查。当天发文与历史文章窗口不同，不能只按单价替换。数据库粉丝为估算，不作为实时精确粉丝数。

## MCP 工具

`jizhile_settings`、`jizhile_setup_local`、`jizhile_balance`、`jizhile_catalog`、`jizhile_compare`、`jizhile_quote_search`、`jizhile_quote`、`jizhile_execute`、`jizhile_reconcile`。

口播转写工具：`jizhile_transcription_settings`、`jizhile_transcription_setup_local`、`jizhile_transcription_prepare`、`jizhile_transcription_run`、`jizhile_transcription_status`、`jizhile_transcription_cancel`、`jizhile_transcription_reconcile`。

常见指令：

- “搜索人民日报最近发布的公众号文章，预算不超过0.5元，先告诉我计费和余额。”
- “搜索北京楼市的视频号视频，优先便宜方案，总预算1元，最多一页。”
- “比较获取公众号正文的接口价格，先别付费查询。”
- “从这个50条视频表里，只转写第1、2、45条口播，先估算火山费用，在1元总预算内执行。”

所有操作目录和价格来源见 `src/jizhile_mcp/catalog.json`、`docs/sources.json`。长ID必须用字符串，避免超过JavaScript安全整数范围。部分文档有冲突，例如视频搜索字段说明写BusinessType=2，而示例为7；本插件使用视频示例7并在目录标注。

## 验证

```sh
uv run pytest -q
uv run python scripts/mcp_smoke.py
```

默认 smoke 仅验证MCP目录和比价工具，不发送计费业务请求。真实付费测试由 `--live` 显式启用，最多两次业务查询，文档预计合计1元；另受本地日预算、安全余额和余额实际状态保护。每次执行均打印报价后再调用，输出不包含密钥；子进程始终关闭。真实测试产生的回执包含账户余额，公开分享前须移除个人余额和账本字段。

2026-10-13已通过真实MCP stdio测试：关键词“人民日报”，公众号搜索返回15条文章，视频搜索返回12条视频，均检查到标题、内容ID和链接。各扣0.50元，共1元。两次重复查询命中缓存，新增业务费为0元。去除个人账户信息的摘要见 [测试回执](docs/live-test-receipt.json)。其余操作尚未逐项付费测试。

## 发布与密钥边界

仓库内 `bundle/` 为从源码生成的可安装插件目录，供GitHub市场直接安装。修改源码后运行 `python3 scripts/package_plugin.py` 并提交生成目录，CI会检查两者一致。

发布内容不包含API Key、附加码、本机配置、缓存或费用账本；`.env*`、`credentials*.json`、SQLite文件、虚拟环境与本地抓取原文均被忽略。GitHub Actions仅运行模拟测试和不计费的MCP检查，不配置真实Key，也不调用 `--live`。

安全检查可运行 `python3 scripts/check_secrets.py`。本机发布前可追加 `--local-config`，把本机已配置的密钥值与工作目录、Git历史和发布包进行比对；只输出检查结论，不输出密钥。
