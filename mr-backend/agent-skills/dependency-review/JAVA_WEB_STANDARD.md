# Dependency Agent Java Web 代码规范

适用专家：Dependency Agent

适用范围：Maven / Gradle 依赖、插件、dependencyManagement、CVE、license、版本冲突、供应链风险和大版本升级。

排除范围：代码实现 bug、业务领域设计、Redis、前端、数据库 DDL 和普通测试覆盖。

## 输出要求

每个依赖 finding 必须包含 groupId、artifactId、当前版本、目标版本或处理方案、风险依据。优先引用 Dependency-Check、osv-scanner、Dependabot、license scanner 证据。

## DEP-CVE-001 高危 CVE 依赖必须阻断

### 规范说明

新增或升级后的依赖若存在 HIGH/CRITICAL CVE，必须输出 high/critical finding。

### 检查点

- pom.xml / build.gradle 新增依赖。
- lockfile 或 dependency tree 中版本变化。
- Dependency-Check / osv-scanner 命中。

### 如何检查

1. 解析 Maven / Gradle 坐标。
2. 比对 CVE 报告。
3. 检查是否已有项目级例外。

### 反例

```xml
<dependency>
  <groupId>com.alibaba</groupId>
  <artifactId>fastjson</artifactId>
  <version>1.2.47</version>
</dependency>
```

### 正例

```xml
<dependency>
  <groupId>com.alibaba.fastjson2</groupId>
  <artifactId>fastjson2</artifactId>
  <version>2.0.53</version>
</dependency>
```

## DEP-LICENSE-002 强传染性 license 必须显式审批

### 规范说明

新增 GPL、AGPL、LGPL、SSPL 等高风险 license 必须标红并要求项目管理员确认。

### 检查点

- 新增依赖 license。
- transitive dependency license。
- 是否已有组织级白名单。

### 如何检查

1. License Finder / ScanCode 解析。
2. 对照项目 license policy。
3. 输出审批建议。

### 反例

新增 AGPL 依赖但无审批记录。

### 正例

新增 Apache-2.0 / MIT 依赖，或 AGPL 依赖已有法务审批记录。

## DEP-VERSION-003 大版本升级必须评估 breaking change

### 规范说明

主版本升级、Spring Boot 版本升级、Jackson/Hibernate/MyBatis 等核心组件升级必须评估兼容性。

### 检查点

- major version 变化。
- Spring Boot / Spring Cloud BOM 变化。
- 插件版本变化影响构建。
- 代码是否同步适配 API 变化。

### 如何检查

1. 比对 old/new version。
2. 检查 release notes 或 known breaking changes。
3. 检查代码 import 和 API 使用。

### 反例

```xml
<version>2.7.18</version>
```

直接升级到：

```xml
<version>3.2.5</version>
```

但未处理 Jakarta 包迁移。

### 正例

升级方案包含 Jakarta 迁移、测试报告和兼容性说明。

## DEP-CONVERGE-004 依赖版本必须收敛

### 规范说明

同一 artifact 不应出现多个版本，核心依赖应由 BOM 或 dependencyManagement 管理。

### 检查点

- Maven dependency tree 中同 artifact 多版本。
- 直接依赖覆盖 BOM。
- Gradle conflict resolution 非预期。

### 如何检查

1. 解析 dependency tree。
2. 检查 dependencyManagement。
3. 输出冲突路径。

### 反例

同时引入 `jackson-databind:2.13.0` 和 `2.15.4`。

### 正例

```xml
<dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>com.fasterxml.jackson</groupId>
      <artifactId>jackson-bom</artifactId>
      <version>2.15.4</version>
      <type>pom</type>
      <scope>import</scope>
    </dependency>
  </dependencies>
</dependencyManagement>
```

## DEP-SCOPE-005 依赖 scope 必须最小化

### 规范说明

测试依赖不得进入运行时，编译期工具不得打入生产包。

### 检查点

- junit/mockito/testcontainers scope 是否 test。
- lombok 是否 provided/compileOnly。
- servlet api 是否 provided。

### 如何检查

1. 解析新增 dependency scope。
2. 检查打包产物风险。
3. 检查运行时 classpath。

### 反例

```xml
<dependency>
  <groupId>org.testcontainers</groupId>
  <artifactId>junit-jupiter</artifactId>
</dependency>
```

### 正例

```xml
<dependency>
  <groupId>org.testcontainers</groupId>
  <artifactId>junit-jupiter</artifactId>
  <scope>test</scope>
</dependency>
```

## DEP-REMOVE-006 移除依赖必须确认代码不再引用

### 规范说明

删除依赖时必须确认源码、测试、配置和插件不再引用对应包或功能。

### 检查点

- import 是否仍存在。
- 配置类是否仍引用。
- starter 移除是否影响 auto configuration。

### 如何检查

1. 比对被移除依赖。
2. 搜索对应 package import。
3. 检查启动配置和测试。

### 反例

移除 `spring-boot-starter-validation`，但 Controller 仍使用 `@Valid`。

### 正例

移除依赖同时删除或替换相关 import，并有启动测试。
