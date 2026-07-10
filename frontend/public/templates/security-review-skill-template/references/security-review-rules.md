# Security Review Rules

## SEC-AUTH-001 管理接口鉴权检查
- severity: high
- applies_to: src/main/java/**,src/**/*.ts

### 检查点
管理端、运营端、批量处理、资金或敏感数据接口必须做身份认证和权限校验。新增或修改接口时，如果能修改业务状态、导出敏感数据、执行审批或触发补偿任务，必须明确校验当前用户权限。

### 证据要求
- 新增或修改 Controller、Handler、RPC 接口、定时任务触发入口或管理 API
- 接口涉及审批、退款、配置、导出、用户权限、资金或敏感数据
- 源码中缺少权限注解、权限服务调用、角色校验或统一鉴权链路证据

### 误报模式
- 普通只读健康检查、公开元数据查询或静态资源接口
- 权限由统一网关或切面处理，且代码中能看到明确注解、拦截器或路由配置
- 测试代码、demo 代码或本地调试入口

### 修复建议
在入口处增加认证和授权校验；使用统一权限组件校验角色、资源范围和操作类型；补充未授权访问测试和审计记录。

## SEC-DATA-002 敏感数据输出检查
- severity: high
- applies_to: src/main/java/**,src/**/*.ts

### 检查点
接口响应、日志、异常消息、导出文件和异步消息不能直接输出手机号、身份证号、银行卡、token、密钥、密码、个人地址等敏感字段。必须脱敏、过滤或只返回必要字段。

### 证据要求
- 代码读取或返回 user、customer、account、token、secret、password、mobile、idCard、bankCard 等敏感字段
- 字段进入响应 DTO、日志、异常、导出内容或消息体
- 缺少脱敏函数、字段白名单、权限过滤或安全审计说明

### 误报模式
- 字段已经经过 mask、desensitize、redact、encrypt 或等价处理
- 仅内部测试 fixture 或模拟数据
- 日志只记录不可逆 hash、traceId 或非敏感业务 id

### 修复建议
使用响应白名单和脱敏工具；日志中只保留必要的 traceId、业务 id 或不可逆摘要；为敏感字段输出增加单元测试。

## REDIS-TTL-002 Redis 业务缓存 TTL 检查
- severity: medium
- applies_to: src/main/java/**,src/**/*.ts

### 检查点
业务缓存写入 Redis 时必须设置过期时间。永久配置 key、feature flag、灰度开关、系统配置 key 不属于本检查点。

### 证据要求
- 使用 redisTemplate.opsForValue().set、set、hset 或等价 Redis 写入
- key 属于用户状态、订单详情、审批状态、任务进度或业务结果缓存
- 缺少 Duration、expire、setEx、EX 参数或等价过期时间

### 误报模式
- 永久配置 key，例如 system:feature:config
- feature flag、灰度开关、系统配置等明确永久 key
- 代码紧随其后调用 expire 设置过期时间

### 修复建议
为业务缓存设置合理 TTL；永久 key 必须用常量命名并注释说明 permanent/config 语义；补充缓存过期行为测试。
