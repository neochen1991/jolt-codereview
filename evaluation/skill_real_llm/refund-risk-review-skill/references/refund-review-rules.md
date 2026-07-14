# Refund Review Rules

## BIZ-CONSISTENCY-001 退款补偿一致性检查
- severity: high
- applies_to: src/main/java/**/refund/**/*.java

### 检查点
退款审核、强制退款、批量退款或补偿逻辑同时修改支付、订单、库存、优惠券、消息等多个业务副作用时，必须有事务边界、补偿状态机、可靠事件或幂等保护。否则会出现部分成功、部分失败、重复补偿或状态不一致。

### 证据要求
- 退款、库存、优惠券、订单状态、消息发送中至少两个业务副作用同时出现
- 缺少事务边界、补偿状态、可靠事件或幂等状态检查
- 失败路径会导致部分成功、部分失败或重复补偿

### 误报模式
- 只是纯查询或只读导出
- 所有副作用都被同一个事务性 outbox 或状态机保护
- 测试代码或本地 demo

### 反例
- 仅查询退款状态、导出报表或计算预估金额，不修改任何业务副作用
- 所有副作用通过同一事务性 outbox 事件或补偿状态机统一编排

### 跳过条件
- 测试代码、本地 demo、mock 数据构造器
- 没有同时出现两个以上业务副作用

### 修复建议
引入退款补偿状态机或 outbox 事件；每个副作用以 refundId/requestId 做幂等；失败后进入可重试补偿状态，并暴露运营可见的异常单。

## BIZ-AUDIT-001 退款审核审计完整性检查
- severity: high
- applies_to: src/main/java/**/refund/**/*.java

### 检查点
管理或运营接口执行退款审核、强制退款或批量通过时，必须记录操作人、退款单、订单、前后状态、原因和请求号。只在日志里打印失败不能替代审计记录。

### 证据要求
- 管理或运营接口执行退款审核、强制退款或批量通过
- 存在 operator、reason 或 admin endpoint 语义
- 缺少审计记录、审计事件或审计落库调用

### 误报模式
- 普通用户自助查询或只读接口
- 审计由统一切面记录且代码中明确标注审计字段
- 测试代码

### 反例
- 普通用户查询退款详情或取消本人退款申请
- 审计由明确的 AOP/拦截器统一记录，且代码中可见 operator、reason 和 requestId 字段

### 跳过条件
- 测试代码、本地 demo、纯查询接口
- 没有管理、运营、强制退款或批量审核语义

### 修复建议
在审核成功和失败路径都写入 RefundAuditEvent/RefundAuditRecord，字段包含 operator、refundId、orderId、beforeStatus、afterStatus、reason、requestId 和 occurredAt。

## REDIS-TTL-002 退款缓存 TTL 检查
- severity: medium
- applies_to: src/main/java/**/refund/**/*.java

### 检查点
退款详情、退款进度、退款审核状态等业务缓存写入 Redis 时必须设置过期时间。永久配置 key、feature flag、灰度开关、系统配置 key 不属于本检查点。

### 证据要求
- 使用 redisTemplate.opsForValue().set 或等价 Redis 写入
- key 属于退款详情、退款进度、退款审核状态等业务缓存
- 缺少 Duration、expire、setEx 或等价过期时间

### 误报模式
- 永久配置 key，例如 system:refund:config
- feature flag、灰度开关、系统配置等明确永久 key
- 代码紧随其后调用 expire 设置过期时间

### 反例
- 永久配置 key，例如 system:refund:config、feature flag、灰度开关等配置 key，明确需要长期存在
- Redis 写入后在同一分支立即调用 expire、setEx 或带 Duration 的 set

### 跳过条件
- 测试代码、本地 demo、配置初始化脚本
- key 不属于退款详情、退款进度或审核状态等业务缓存

### 修复建议
为业务缓存设置 TTL；永久 key 必须在代码中用常量命名和注释说明 permanent/config 语义。
