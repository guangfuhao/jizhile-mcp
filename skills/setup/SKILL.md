---
name: jizhile-setup
description: 在本机安全配置极致了 API Key 与附加码，并查询余额验证配置。
---

先调用 `jizhile_settings`。已配置时直接验证 `jizhile_balance`；不要反复索取 Key。

未配置时使用 `jizhile_setup_local(open_browser=true)`，用户在127.0.0.1限时配置页输入。不要要求把密钥贴到普通聊天。配置文件默认 `~/.config/jizhile-mcp/credentials.json`，权限0600；保存在插件仓库之外。配置页保存即停止，最长10分钟。

服务方入口：[极致了数据](https://www.jzl.com/)。接口与价格以[官方接口文档](https://s.apifox.cn/410674f9-f451-4b4f-957a-5f54f243bc83)为准。用户从服务方账户取得自己的API Key；文档使用的域名是www.dajiala.com，无额外已核实的Key发放接口。

配置完成后重试余额查询，报告余额和预算，不显示密钥。余额查询本次实测未扣费，文档没有明确免费承诺；业务接口通常计费。

默认单次10元、每日500元（北京时间）、保留100元余额。每次付费查询后的预计余额不得低于100元；已有环境变量配置仍优先生效。用户明确要求修改后，才可设置环境变量 `JIZHILE_SINGLE_LIMIT`、`JIZHILE_DAILY_LIMIT`、`JIZHILE_BALANCE_RESERVE`，并向用户说明影响。预算只约束本插件的调用；同Key在其它客户端消费、服务方调价或单次超额扣费不受本地硬限制，异常时本插件停止后续付费请求。
