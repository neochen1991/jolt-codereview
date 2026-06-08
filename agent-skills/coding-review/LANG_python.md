# Coding Python Standard

## 规范说明
适用于 Python 服务、脚本和自动化代码的通用正确性检视。

## 检查点
- 文件、网络、数据库连接必须使用上下文管理或显式关闭。
- 异常不得裸 `except Exception` 后静默吞掉。
- 可变默认参数、全局状态和隐式 None 返回必须谨慎处理。

## 如何检查
1. 搜索 `except`、`open`、请求/DB 调用和默认参数。
2. 检查失败路径是否记录并向上暴露。
3. 确认资源释放和超时设置。

## 反例
```python
def append_item(item, items=[]):
    items.append(item)
```

## 正例
```python
def append_item(item, items=None):
    result = [] if items is None else list(items)
    result.append(item)
    return result
```
