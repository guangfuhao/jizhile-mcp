# 火山转写参考

文档读取日期：2026-10-13。

- [音频理解](https://docs.volcengine.com/docs/ark/audio-understanding?lang=zh)：支持Responses/Chat的音频输入；本插件使用Responses的`input_audio.audio_url`及`data:audio/mpeg;base64,...`。Base64单文件上限25MB、120分钟；每秒音频约6.25 token，以响应usage为准。
- [Responses API](https://docs.volcengine.com/docs/ark/create-model-responses-api?lang=zh)：POST `https://ark.cn-beijing.volces.com/api/v3/responses`，Bearer API Key。关闭思考，限制max_output_tokens，设置store=false。不使用Files上传，因此无需维护或删除云端文件。
- [模型价格](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh)：价格随服务方政策变化，按参考价计算的金额不是实际账单。

本插件核对的在线常规推理参考价，输入长度不超过32K，单位为元/百万token：

|模型|非音频输入|音频输入|输出|
|---|---:|---:|---:|
|doubao-seed-2-0-mini-260428|0.2|3|2|
|doubao-seed-2-0-lite-260428|0.6|9|3.6|

预留估算按每秒8个音频token、512个文本输入token、受限输出token再加25%余量计算；实际完成后按返回usage计算费用估算。没有audio_tokens细分时，保守把全部输入按音频计价；没有完整token用量则费用待核对并暂停。忽略可能存在的缓存折扣，避免低估。

方舟运行时API Key未提供在此工作流中可核实的账户余额查询接口；工具输出ark_balance_yuan=null、actual_bill_yuan=null，不冒用极致了余额或将未知值写为0。独立按Key保存转写账本，单次与每日上限沿用插件配置，但100元余额保护只在极致了查询工作流中可验证。

默认顺序处理，最长单视频60分钟、下载250MB、分段30至300秒。分段按本地音频时长顺序拼接，时间是分段范围，并非逐字字幕对齐。自动结果不保证专有名词、金额或逐字准确率；不进行未经请求的润色或事实更正。
