# MiniMax 与 GLM 模型能力适配设计

## 目标

让代码检视主流程在 MiniMax 与 GLM 模型之间切换时保持相同的 Skill、规范、上下文和 Judge 语义，同时根据模型能力生成兼容的请求参数，避免固定 12K 输出、结构化输出协议不兼容和截断静默丢失导致的召回率下降。

## 方案

新增集中式模型能力档案。能力档案根据 provider 与 model 识别模型族，并允许项目 `llm.model_overrides` 覆盖默认值。档案负责声明：最大输出 token、推荐输出 token、Thinking 参数、结构化输出模式、seed 支持和流式 reasoning 字段。

请求构建统一经过能力档案：

- GLM-5.2 显式开启 Thinking，使用 `json_object`，默认推荐 32768、最大 131072。
- GLM-5.1/GLM-5 显式开启 Thinking，使用 `json_object`，但不发送仅新模型支持的推理强度参数。
- MiniMax 保持普通 JSON 提示词与既有参数兼容；若网关明确拒绝结构化输出，再按单个参数降级。
- 未识别模型使用保守的 OpenAI-compatible 默认档案。

所有模型继续使用相同的 prompt builder、Skill 规则正文、ContextUnit 和 Judge 流程。适配层不能修改检视规则或过滤标准。

## 输出协议和解析

新协议使用顶层对象 `{"findings": [...]}`，兼容只支持 `json_object` 的网关。解析器同时接受旧顶层数组，保证历史缓存和 exact replay 可用。

每次调用记录 effective max tokens、模型族、Thinking 模式、结构化输出模式、finish reason、reasoning 长度、content 长度和解析漏斗。`finish_reason=length` 或 JSON 不完整时，不直接把残缺结果交给 Judge，而是执行一次受限的 JSON 修复调用；修复失败时记录明确原因。

## 参数降级

不再将所有 HTTP 4xx 视为 schema 不支持。只有错误正文明确指向 `response_format`、`json_schema`、`thinking` 或 `seed` 时，才移除对应参数并重试一次。429、鉴权错误和上下文超限保持原始错误语义。

## 配置与界面

移除前后端 12000 硬上限。配置值仍优先于推荐值，并按模型能力最大值校验。示例配置和 README 说明 MiniMax/GLM 的推荐配置、网关地址、密钥环境变量和兼容覆盖方式。

本地未跟踪配置切换为 `glm-5.2`、32768 输出 token，并保留现有网关和密钥来源；密钥不会写入受版本控制文件。

## 验证

- 单元测试验证 GLM-5.2、GLM-5.1、MiniMax 和未知模型的能力解析。
- 请求契约测试验证 Thinking、response format、seed 和输出 token。
- 解析测试验证新旧 JSON、截断和无效路径统计。
- 运行 worker 测试、前端测试与构建。
- 使用本地服务做一次模型配置读取和请求载荷烟测；只有具备可用网关额度时才声称完成真实 LLM 调用。
