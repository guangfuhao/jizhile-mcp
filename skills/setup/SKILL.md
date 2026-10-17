---
name: jizhile-setup
description: 在本机安全配置极致了公众号/视频号Key或云端点全媒体/电商X-API-Key，核实换算单位并验证对应服务余额。
---

先调用 `jizhile_settings`。原公众号、视频号服务使用顶层configured和极致了Key；其余全媒体、电商服务使用yddm.configured与云端点独立X-API-Key。按用户要用的平台检查对应配置，不因另一服务未配置而索取无关Key；不得混用两者或火山转写Key。

已有对应Key时直接调用 `jizhile_balance(provider="jizhile")` 或 `jizhile_balance(provider="yddm")` 验证，不反复索取Key。缺少时调用 `jizhile_setup_local(open_browser=true, provider="jizhile")` 或 `provider="yddm"`，由用户在127.0.0.1限时页面输入。不要要求把密钥贴到聊天。默认配置分别保存在仓库外 `~/.config/jizhile-mcp/credentials.json` 与 `yddm-credentials.json`，权限0600；配置页保存即停止，最长10分钟。

云端点还须核实两项换算：业务data.cost/data.balance每1元的单位数、个人信息data.balance_cents每1元的单位数。页面参考值1000来自“100积分”和资费表“0.1元”的交叉推算，不等于账户保证；不能只凭字段名猜测“分”。用户核实后勾选确认；未确认时可保存Key、读取原始余额，但不能报价付费。Agent不能替用户勾选确认或私自设置units_confirmed。

原服务入口：[极致了数据](https://www.jzl.com/)，[原API文档](https://s.apifox.cn/410674f9-f451-4b4f-957a-5f54f243bc83)，请求域名www.dajiala.com。[云端点API文档](https://s.apifox.cn/6faad22e-3ea1-4934-8926-69d0efb2dce1/llms.txt)定义api.yddm.com及X-API-Key。用户从各自服务方账户取得密钥；不要使用文档中示例Key。火山转写配置走同插件转写技能。

配置完成后验证对应余额，报告单位、预算和paid_calls_allowed，不输出Key或云端点个人信息。鉴权或余额查询通过不代表业务数据查询成功；不要为了验证而自动执行付费样例。

默认单次10元、公众号与云端点查询合计每日500元（北京时间）、各账户保留100元余额，火山转写另行计账。不能用一方余额抵另一方；余额不足时保留拦截，不为测试自行降低预留。仅当用户明确要求修改后，才可设置JIZHILE_SINGLE_LIMIT、JIZHILE_DAILY_LIMIT、JIZHILE_BALANCE_RESERVE并说明影响。同Key在其他客户端消费、服务方调价或单次超额扣费不受本地硬限制；异常时停止后续付费请求并核对账目。
