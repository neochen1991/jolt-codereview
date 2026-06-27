# Security Core Standard

## 规范说明
只报告会造成越权、注入、敏感信息泄露、信任边界绕过或供应链暴露的安全问题。

## 检查点
- 新增入口是否有认证、授权和资源归属校验。
- 外部输入是否进入 SQL、命令、模板、反序列化、重定向或文件路径。
- 密钥、密码、token、内部地址是否进入源码、配置、日志或错误响应。

## 如何检查
1. 从 diff 找入口方法和外部输入。
2. 追踪输入到敏感 sink。
3. 查找认证授权证据和工具观察。
4. 仅在有可复现代码位置时输出 finding。

## 反例
```java
statement.executeQuery("select * from users where id=" + request.getId());
```

## 正例
```java
jdbcTemplate.query("select * from users where id=?", mapper, request.getId());
```
