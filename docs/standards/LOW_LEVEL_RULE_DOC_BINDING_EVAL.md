# 低级缺陷专家规范文档绑定评估

适用专家：低级缺陷 Agent

适用范围：Java / Spring 业务代码中的空值、Optional、金额精度、集合遍历修改、异常吞掉、资源关闭和基础并发 API 误用。

排除范围：架构设计、DDD 建模、专项安全漏洞、依赖 CVE、数据库容量优化、前端交互。

## LLDOC-NULL-101 可空对象链式解引用
- severity: high
- category: low_level_null_safety
- applies_to: src/main/java/**/*.java

### 规范说明
新增代码不得对 Repository 查询结果、外部接口返回对象、Map.get 结果或 getter 链路直接连续解引用；必须先显式判空或使用 Optional/orElseThrow 表达失败语义。

### 检查点
- 是否出现 `customer.getProfile().getNickname().trim()` 这类链式调用。
- 上游对象是否来自可能为空的查询、缓存或外部响应。
- 同一方法内是否存在非空断言、orElseThrow 或明确校验。

### 证据要求
必须给出新增问题行、对象来源行和缺少判空的说明。

### 反例
`String name = customer.getProfile().getNickname().trim();`

### 正例
`String name = Optional.ofNullable(customer.getProfile()).map(Profile::getNickname).filter(StringUtils::hasText).orElseThrow(...);`

### 误报模式
对象由构造器强制注入且字段为 final；或方法入口已经通过 `Objects.requireNonNull` 保证。

### 修复建议
用显式判空、orElseThrow 或空对象模式替代链式裸调用。

## LLDOC-OPT-102 Optional.get 未先判断存在性
- severity: medium
- category: low_level_optional
- applies_to: src/main/java/**/*.java

### 规范说明
不得在没有 `isPresent`、`orElseThrow`、`orElse` 或业务兜底的情况下直接调用 `Optional.get()`。

### 检查点
- 是否直接调用 `optional.get()`。
- 调用前是否有控制流保证 Optional 一定有值。
- 缺失时是否会转化为清晰的业务异常。

### 证据要求
必须展示 Optional 创建/返回位置和 `.get()` 调用位置。

### 反例
`PaymentOrder order = orderRepository.findById(id).get();`

### 正例
`PaymentOrder order = orderRepository.findById(id).orElseThrow(() -> new NotFoundException(id));`

### 误报模式
同一分支内已有 `if (optional.isPresent())` 且 get 位于该分支。

### 修复建议
使用 `orElseThrow` 或显式处理缺失分支。

## LLDOC-MONEY-103 BigDecimal 使用 double 构造金额
- severity: high
- category: low_level_money
- applies_to: src/main/java/**/*.java

### 规范说明
金额、费率和折扣不得使用 `new BigDecimal(double)` 构造；浮点二进制误差会进入金额计算。

### 检查点
- 是否出现 `new BigDecimal(rate)`、`new BigDecimal(0.1)`。
- 变量是否参与金额、折扣、手续费、汇率、费率计算。
- 是否应改为字符串构造或 `BigDecimal.valueOf`。

### 证据要求
必须展示 double 来源和 BigDecimal 构造行。

### 反例
`BigDecimal discount = new BigDecimal(rate);`

### 正例
`BigDecimal discount = BigDecimal.valueOf(rate);`

### 误报模式
非金额业务且仅用于测试断言的近似值。

### 修复建议
使用 `BigDecimal.valueOf(double)` 或字符串常量，并明确 scale 和 RoundingMode。

## LLDOC-COLL-104 增强 for 遍历中修改集合
- severity: medium
- category: low_level_collection
- applies_to: src/main/java/**/*.java

### 规范说明
不得在增强 for 遍历集合时直接调用原集合的 `remove/add/clear`；会触发 `ConcurrentModificationException` 或跳过元素。

### 检查点
- 是否在 `for (T item : list)` 内调用 `list.remove(item)`。
- 是否使用 Iterator.remove、removeIf 或收集后统一删除。

### 证据要求
必须展示循环声明行和集合修改行。

### 反例
`for (Order order : orders) { orders.remove(order); }`

### 正例
`orders.removeIf(Order::isExpired);`

### 误报模式
遍历的是副本，例如 `for (T item : new ArrayList<>(list))`。

### 修复建议
使用 `Iterator.remove`、`removeIf` 或先收集再批量删除。

## LLDOC-EXC-105 异常被吞掉并返回 null 或空结果
- severity: high
- category: low_level_exception
- applies_to: src/main/java/**/*.java

### 规范说明
业务关键路径不得捕获宽泛异常后只 `printStackTrace`、返回 null、返回空集合或伪造成功；这会隐藏真实失败并扩大后续 NPE 或数据不一致。

### 检查点
- 是否 `catch (Exception e)` 后返回 null/空集合/默认成功。
- 是否缺少日志、错误码和异常传播。
- 调用方是否会把 null 当作正常结果继续使用。

### 证据要求
必须展示 catch 块和返回语句。

### 反例
`catch (Exception ex) { ex.printStackTrace(); return null; }`

### 正例
`catch (IOException ex) { throw new PaymentImportException("load failed", ex); }`

### 误报模式
明确的 best-effort 非关键路径，且日志、指标和降级语义完整。

### 修复建议
捕获具体异常，记录结构化日志，返回显式失败或抛出领域异常。

## LLDOC-RES-106 IO 资源未使用 try-with-resources 关闭
- severity: medium
- category: low_level_resource
- applies_to: src/main/java/**/*.java

### 规范说明
新增 IO、JDBC、Stream、Reader、InputStream 等资源必须使用 try-with-resources 或等价 finally 关闭。

### 检查点
- 是否创建 `new FileInputStream`、`Files.newInputStream`、`Connection`、`ResultSet`。
- 是否缺少 try-with-resources、finally close 或框架托管生命周期。

### 证据要求
必须展示资源创建行和缺少关闭的作用域。

### 反例
`FileInputStream input = new FileInputStream(file); props.load(input);`

### 正例
`try (FileInputStream input = new FileInputStream(file)) { props.load(input); }`

### 误报模式
资源由容器或框架托管，当前代码不拥有关闭责任。

### 修复建议
改为 try-with-resources，并把解析失败转化为明确异常。

## LLDOC-CONC-107 static SimpleDateFormat 跨线程共享
- severity: high
- category: low_level_concurrency
- applies_to: src/main/java/**/*.java

### 规范说明
不得把 `SimpleDateFormat` 放在 static 字段中跨请求共享；它不是线程安全对象。

### 检查点
- 是否存在 `private static final SimpleDateFormat`。
- 是否在 Controller/Service/Component 等多线程对象中复用。
- 是否可替换为 `DateTimeFormatter`。

### 证据要求
必须展示 static 字段声明和使用位置。

### 反例
`private static final SimpleDateFormat FORMATTER = new SimpleDateFormat("yyyyMMdd");`

### 正例
`private static final DateTimeFormatter FORMATTER = DateTimeFormatter.BASIC_ISO_DATE;`

### 误报模式
对象只在单线程临时局部变量中创建并使用。

### 修复建议
使用线程安全的 `java.time.format.DateTimeFormatter` 或每次创建局部 formatter。
