# Coding Java Standard

## 规范说明
适用于 Java 代码正确性检视，结合阿里巴巴 Java 编码规约、P3C 可静态化规则和企业 Java Web 工程经验。Coding Agent 只关注语言级正确性、可读性、异常、空值、集合契约和并发基础用法，不重复检查安全、性能、数据库专项和领域建模专项问题。

## 检查点
- 命名不得以 `_` 或 `$` 开始/结束，不得使用中文、拼音或中英文混合命名。
- `BigDecimal` 不得使用 `double`/`float` 构造，金额计算必须保留明确精度和舍入策略。
- 不得直接使用 `Executors` 工厂方法创建生产线程池。
- `SimpleDateFormat` 不得作为 `static` 共享对象。
- 重写 `equals` 必须同时重写 `hashCode`，两者必须使用一致业务身份；普通 `xxx.equals(...)` 调用不属于该规则。
- 集合、Map、Page、Optional 类型返回值不得返回 `null`。
- 禁止 `printStackTrace()` 和 `System.out/System.err` 进入生产代码。
- `Optional.get()` 前必须证明存在值。
- `catch Exception` 不得吞异常或返回误导性成功。
- 不要仅因 `@Autowired` 字段注入输出独立问题；只有依赖直接造成资源泄漏、事务错误、领域模型污染等其他明确违规时，按对应专项规则报告。

## 如何检查
1. 搜索新增类名、字段名、方法名，检查是否命中 `_`、`$`、中文或拼音混合命名。
2. 搜索 `new BigDecimal(`、`Executors.new`、`new SimpleDateFormat(`、`public boolean equals(Object`、`public int hashCode()`。
3. 搜索 `return null`，确认方法返回类型是否为集合、Map、Page 或 Optional。
4. 搜索 `printStackTrace`、`System.out`、`System.err`、`catch (Exception`、`Optional.get()`。
5. 对每个问题给出精确行号、命中的规范条目、可替换建议代码和必要的回归测试建议。

## 反例
```java
class _PaymentService {
    private static final SimpleDateFormat FORMAT = new SimpleDateFormat("yyyy-MM-dd");

    BigDecimal amount(double value) {
        return new BigDecimal(value);
    }

    List<String> listOrders() {
        return null;
    }

    void log(Exception e) {
        e.printStackTrace();
        System.out.println(e.getMessage());
    }
}
```

## 正例
```java
class PaymentService {
    private static final DateTimeFormatter FORMATTER =
        DateTimeFormatter.ofPattern("yyyy-MM-dd");

    BigDecimal amount(String value) {
        return new BigDecimal(value).setScale(2, RoundingMode.HALF_UP);
    }

    List<String> listOrders() {
        return Collections.emptyList();
    }

    void log(String orderNo, Exception e) {
        log.error("payment operation failed orderNo={}", orderNo, e);
    }
}
```
