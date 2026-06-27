# Dependency Java Standard

## 规范说明
适用于 Maven / Gradle Java 项目。

## 检查点
- `pom.xml` 和 `build.gradle` 新增依赖必须声明合适 scope。
- 禁止引入已知高危版本，如老 fastjson、log4j 高危版本。
- 插件版本必须固定，避免动态版本。

## 如何检查
1. 搜索 dependency/plugin 变更。
2. 匹配工具 CVE 输出与依赖行。
3. 给出升级版本或 scope 修改片段。

## 反例
```xml
<version>1.2.47</version>
```

## 正例
```xml
<version>2.0.53</version>
```
