# Security Python Standard

## 规范说明
适用于 Python Web/API/脚本安全检视。

## 检查点
- 禁止 `eval`、`exec`、shell 拼接和不安全反序列化。
- SQL/ORM 查询不得拼接外部输入。
- token、secret、password 不得写入源码、日志或异常。

## 如何检查
1. 搜索 `eval/exec/subprocess/yaml.load/pickle`。
2. 检查外部输入到 SQL、命令和文件路径的流向。
3. 结合 bandit/ruff 观察确认。

## 反例
```python
subprocess.run("rm -rf " + user_path, shell=True)
```

## 正例
```python
subprocess.run(["rm", "-rf", safe_path], check=True)
```
