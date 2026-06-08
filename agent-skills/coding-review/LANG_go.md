# Coding Go Standard

## 规范说明
适用于 Go 服务代码的通用正确性检视。

## 检查点
- 所有 `error` 必须处理，不得 `_` 丢弃。
- goroutine 必须有退出条件和 context。
- defer/close 必须覆盖文件、响应体和锁。

## 如何检查
1. 搜索 `go func`、`err`、`defer`、`Close`。
2. 检查 context 是否向下传递。
3. 检查错误返回是否保留上下文。

## 反例
```go
resp, _ := http.Get(url)
```

## 正例
```go
resp, err := client.Do(req)
if err != nil { return fmt.Errorf("call upstream: %w", err) }
defer resp.Body.Close()
```
