# Dependency Core Standard

## 规范说明
只报告依赖 CVE、许可证、版本收敛、scope、插件和供应链风险。

## 检查点
- 新增依赖是否有高危 CVE 或不可信来源。
- 测试依赖是否限制在 test/dev scope。
- 版本是否与 dependency management 冲突。

## 如何检查
1. 读取依赖文件 diff。
2. 结合 OSV、Trivy、Dependency-Check 观察。
3. 判断依赖是否进入运行时 classpath。

## 反例
```xml
<dependency><artifactId>junit-jupiter</artifactId></dependency>
```

## 正例
```xml
<dependency><artifactId>junit-jupiter</artifactId><scope>test</scope></dependency>
```
